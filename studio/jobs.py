from .errors import StudioError
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import media, quality
from .providers import HANGER_VIEWS, VIEWS, MockProvider, RealProvider, clip_duration, prompt
from .storage import dump, uid


class JobPaused(Exception):
    pass


class Runner:
    def __init__(self, store, concurrency=1):
        self.store = store
        self.owner = uid()
        self.concurrency = max(1, min(int(concurrency), 3))
        self.pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix='studio')
        self.lock = threading.Lock()
        self.pending = set()

    def submit(self, identity, keys=('', ''), provider=None):
        with self.lock:
            if identity in self.pending:
                return False
            self.store.execute("UPDATE jobs SET status='queued',pause_requested=0 WHERE id=? AND status='paused'", (identity,))
            self.pending.add(identity)
        future = self.pool.submit(self.run, identity, keys, provider)
        future.add_done_callback(lambda _: self.discard(identity))
        return True

    def discard(self, identity):
        with self.lock:
            self.pending.discard(identity)

    def run(self, identity, keys=('', ''), provider=None):
        while not self.store.claim(identity, self.owner, self.concurrency):
            # Capacity/maintenance contention should not silently drop queued work.
            waiting = self.store.job(identity)
            if waiting['mode'] not in {'mock', 'real'} or waiting['status'] not in {'queued', 'failed', 'interrupted'}:
                return
            time.sleep(0.5)
        stop = threading.Event()

        def heartbeat():
            import time
            while not stop.wait(10):
                self.store.execute('UPDATE jobs SET heartbeat=? WHERE id=? AND owner=?', (time.time(), identity, self.owner))

        timer = threading.Thread(target=heartbeat, daemon=True)
        timer.start()
        stage = 'initialization'
        try:
            job = self.store.job(identity)
            snapshot = json.loads(job['snapshot'])
            options = snapshot['options']
            folder = self.store.path(f'jobs/{identity}')
            media.check()
            provider = provider or (MockProvider() if job['mode'] == 'mock' else RealProvider(options, *keys))
            if provider.paid and (job['mode'] != 'real' or not options.get('authorized')):
                raise StudioError('Chưa xác nhận sử dụng API có phí.')
            if isinstance(provider, RealProvider):
                provider.preflight()
            products = [self.store.path(p) for p in snapshot['products']]
            background = self.store.path(snapshot['background_file'])
            for relative, expected in snapshot.get('source_hashes', {}).items():
                if quality.fingerprint(self.store.path(relative)) != expected:
                    raise StudioError('Ảnh nguồn đã thay đổi sau khi tạo công việc. Tạo công việc mới để bảo toàn nhận diện sản phẩm.')
            stage = 'analysis'
            self.checkpoint(identity, stage)
            identity_file = folder / 'identity.json'
            if not identity_file.exists():
                self.reserve(provider, identity, options, 'analysis')
                dump(identity_file, provider.analyze(products, background))
            product_identity = json.loads(identity_file.read_text(encoding='utf-8'))
            dump(folder / 'product_manifest.json', {'source_files': snapshot['products'], 'identity': product_identity, 'unknown_details_policy': 'Do not invent unseen details.', 'mode': job['mode']})
            views = HANGER_VIEWS if snapshot['script']['id'] == 'hanger' else VIEWS
            references = []
            for i, action in enumerate(views):
                stage = f'reference_{i + 1}'
                self.checkpoint(identity, stage)
                output = folder / f'reference_{i + 1:02}.png'
                if not output.exists():
                    self.reserve(provider, identity, options, 'image')
                    temporary = folder / f'reference_{i + 1:02}.partial.png'
                    provider.reference(products, background, references[0] if references else None, prompt(snapshot, product_identity, action), temporary, i)
                    temporary.replace(output)
                references.append(output)
            stage = 'quality_review'
            self.checkpoint(identity, stage)
            report = quality.inspect_references(references, background, job['mode'])
            dump(folder / 'quality_report.json', report)
            ai_report = None
            if provider.paid and options.get('ai_quality_review'):
                ai_path = folder / 'ai_quality_report.json'
                if ai_path.exists():
                    cached = json.loads(ai_path.read_text(encoding='utf-8'))
                    if cached.get('reference_hashes') == report['reference_hashes']:
                        ai_report = cached
                if ai_report is None:
                    self.reserve(provider, identity, options, 'review')
                    ai_report = provider.review(products, background, references)
                    ai_report['reference_hashes'] = report['reference_hashes']
                    dump(ai_path, ai_report)
            needs_review = options.get('review_before_video') or report['status'] == 'flagged' or (ai_report is not None and ai_report['status'] != 'pass')
            if needs_review and not quality.review_is_current(folder, references):
                self.store.execute("UPDATE jobs SET status='awaiting_review',owner=NULL,stage='quality_review',error='Cần duyệt 5 ảnh tham chiếu trước khi tạo video.' WHERE id=? AND owner=?", (identity, self.owner))
                return
            clips = []
            for i, (seconds, action) in enumerate(zip(snapshot['script']['durations'], snapshot['script']['actions'])):
                stage = f'scene_{i + 1}'
                self.checkpoint(identity, stage)
                output = folder / f'scene_{i + 1:02}.mp4'
                state = folder / f'operation_{i + 1:02}.json'
                if not output.exists():
                    # Existing operation is polled, never submitted/billed a second time.
                    if not state.exists():
                        duration = clip_duration(seconds, options.get('video_conditioning', 'first_frame'))
                        self.reserve(provider, identity, options, 'video', duration)
                    reference = references[min(i, 4)]
                    extra = {}
                    if options.get('video_conditioning') == 'continuity' and clips:
                        reference = folder / f'last_frame_{i:02}.png'
                        if not reference.exists():
                            media.last_frame(clips[-1], reference)
                    if options.get('video_conditioning') == 'asset_references':
                        extra['asset_references'] = [products[0], background, references[min(i, 4)]]
                    provider.video(reference, prompt(snapshot, product_identity, action), output, seconds, state, options.get('width', 1080), options.get('height', 1920), **extra)
                clips.append(output)
            stage = 'assembly'
            self.checkpoint(identity, stage)
            candidate = folder / 'assembled.mp4'
            media.assemble(clips, candidate)
            metadata = media.validate_video(candidate, options.get('width', 1080), options.get('height', 1920), sum(snapshot['script']['durations']))
            dump(folder / 'video_metadata.json', metadata)
            candidate.replace(folder / f'final_{identity}.mp4')
            self.store.execute("UPDATE jobs SET status='complete',owner=NULL,error='',stage='complete' WHERE id=? AND owner=?", (identity, self.owner))
            self.store.execute('INSERT INTO events(job_id,stage,code) VALUES(?,?,?)', (identity, stage, 'complete'))
        except JobPaused:
            self.store.execute("UPDATE jobs SET status='paused',owner=NULL,error='Đã tạm dừng; kết quả các bước đã xong được giữ.' WHERE id=? AND owner=?", (identity, self.owner))
        except Exception as error:
            # Never persist provider exception strings: they can contain URLs, keys or prompts.
            code = type(error).__name__
            message = f'Lỗi tại {stage} ({code}). Kiểm tra kết nối, khóa, giới hạn chi phí và FFmpeg; sau đó thử lại.'
            if isinstance(error, StudioError):
                message = f'{stage}: {error}'
            self.store.execute("UPDATE jobs SET status='failed',owner=NULL,error=? WHERE id=? AND owner=?", (message, identity, self.owner))
            self.store.execute('INSERT INTO events(job_id,stage,code) VALUES(?,?,?)', (identity, stage, code))
        finally:
            stop.set()
            timer.join(timeout=2)

    def reserve(self, provider, identity, options, kind, seconds=1):
        if provider.paid:
            self.store.reserve(identity, options[f'{kind}_cost'] * seconds)

    def checkpoint(self, identity, stage):
        job = self.store.job(identity)
        if job['owner'] != self.owner or job['status'] != 'running' or job['pause_requested']:
            raise JobPaused()
        self.store.execute('UPDATE jobs SET stage=? WHERE id=? AND owner=?', (stage, identity, self.owner))

    def approve_references(self, identity, approved, note=''):
        with self.store.edit_job(identity):
            folder = self.store.path(f'jobs/{identity}')
            references = [folder / f'reference_{i:02}.png' for i in range(1, 6)]
            quality.save_review(folder, references, approved, note)
            if approved:
                self.store.execute("UPDATE jobs SET status='queued',owner=NULL,error='' WHERE id=?", (identity,))
            else:
                self.store.execute("UPDATE jobs SET status='awaiting_review',owner=NULL,error='Ảnh bị đánh dấu sai lệch; tạo lại ảnh cần sửa.' WHERE id=?", (identity,))

    def archive(self, folder, names):
        destination = folder / 'history' / uid()
        for name in names:
            path = folder / name
            if path.exists():
                destination.mkdir(parents=True, exist_ok=True)
                path.replace(destination / name)

    def retry_reference(self, identity, view):
        if type(view) is not int or not 1 <= view <= 5:
            raise StudioError('Góc tham chiếu cần từ 1 đến 5.')
        with self.store.edit_job(identity):
            folder = self.store.path(f'jobs/{identity}')
            views = range(1, 6) if view == 1 else [view]
            names = [f'reference_{i:02}.png' for i in views]
            names += [p.name for p in folder.iterdir() if p.is_file() and (p.name.startswith(('scene_', 'operation_', 'last_frame_', 'final_')) or p.name in {'quality_review.json', 'quality_report.json', 'ai_quality_report.json'})]
            self.archive(folder, names)
            self.store.execute("UPDATE jobs SET status='queued',owner=NULL,error='' WHERE id=?", (identity,))

    def retry_scene(self, identity, scene):
        with self.store.edit_job(identity) as job:
            snapshot = json.loads(job['snapshot'])
            if type(scene) is not int or not 1 <= scene <= len(snapshot['script']['actions']):
                raise StudioError('Số cảnh không hợp lệ.')
            folder = self.store.path(f'jobs/{identity}')
            scenes = range(scene, len(snapshot['script']['actions']) + 1) if snapshot['options'].get('video_conditioning') == 'continuity' else [scene]
            names = [f'final_{identity}.mp4']
            for i in scenes:
                names.extend([f'scene_{i:02}.mp4', f'scene_{i:02}_raw.mp4', f'operation_{i:02}.json', f'last_frame_{i:02}.png'])
            # Also remove the input last-frame for the retried scene itself.
            names.append(f'last_frame_{scene - 1:02}.png')
            self.archive(folder, list(dict.fromkeys(names)))
            self.store.execute("UPDATE jobs SET status='queued',owner=NULL,error='' WHERE id=?", (identity,))
