from .errors import StudioError
import contextlib
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate_script(script):
    durations, actions = script.get('durations'), script.get('actions')
    if not isinstance(durations, list) or not isinstance(actions, list) or not 1 <= len(actions) <= 12:
        raise StudioError('Kịch bản cần 1–12 cảnh.')
    if len(durations) != len(actions) or any(type(n) is not int or not 1 <= n <= 8 for n in durations):
        raise StudioError('Mỗi cảnh cần thời lượng nguyên 1–8 giây và một hành động.')
    if not str(script.get('name', '')).strip() or any(not isinstance(a, str) or not a.strip() or len(a) > 2000 for a in actions):
        raise StudioError('Tên và hành động không được trống; mỗi hành động tối đa 2000 ký tự.')
    return script


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'studio.sqlite3'
        self.migrate()

    @contextlib.contextmanager
    def connect(self):
        c = sqlite3.connect(self.database, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA busy_timeout=30000')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def migrate(self):
        with self.connect() as c:
            if c.execute('PRAGMA user_version').fetchone()[0] > 3:
                raise StudioError('Dữ liệu được tạo bởi bản ứng dụng mới hơn; cần nâng cấp ứng dụng.')
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
                CREATE TABLE IF NOT EXISTS backgrounds(id TEXT PRIMARY KEY, name TEXT, file TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, product TEXT, background_id TEXT, script_id TEXT, status TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS scripts(id TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id TEXT, stage TEXT, code TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
            ''')
            migrations = {
                'backgrounds': {'family': 'TEXT', 'version': 'INTEGER DEFAULT 1', 'manifest': "TEXT DEFAULT '{}'", 'deleted': 'INTEGER DEFAULT 0'},
                'jobs': {'mode': "TEXT DEFAULT 'legacy'", 'snapshot': "TEXT DEFAULT '{}'", 'error': "TEXT DEFAULT ''", 'attempts': 'INTEGER DEFAULT 0', 'calls': 'INTEGER DEFAULT 0', 'reserved_usd': 'REAL DEFAULT 0', 'heartbeat': 'REAL DEFAULT 0', 'owner': 'TEXT', 'stage': "TEXT DEFAULT 'created'", 'pause_requested': 'INTEGER DEFAULT 0'},
            }
            for table, fields in migrations.items():
                existing = {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}
                for name, declaration in fields.items():
                    if name not in existing:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
            c.execute('UPDATE backgrounds SET family=id WHERE family IS NULL')
            # Rebase old absolute data paths when moving an existing installation.
            for table, column in [('backgrounds', 'file'), ('jobs', 'product')]:
                for row in c.execute(f'SELECT id,{column} FROM {table}').fetchall():
                    value = row[column]
                    if not value:
                        continue
                    parts = value.replace(chr(92), '/').split('/')
                    candidate = Path(value)
                    if not candidate.is_absolute():
                        candidate = self.root / candidate
                    if not candidate.resolve().is_relative_to(self.root) and 'data' in parts:
                        candidate = self.root.joinpath(*parts[parts.index('data') + 1:])
                    if candidate.resolve().is_relative_to(self.root) and candidate.exists():
                        c.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (candidate.resolve().relative_to(self.root).as_posix(), row['id']))
            c.execute('CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status,created)')
            c.execute('PRAGMA user_version=3')

    def rows(self, sql, args=()):
        with self.connect() as c:
            return [dict(row) for row in c.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as c:
            return c.execute(sql, args).rowcount

    def path(self, relative):
        raw = Path(relative)
        target = (self.root / raw).resolve()
        if not target.is_relative_to(self.root):
            raise StudioError('Đường dẫn nằm ngoài thư mục dữ liệu.')
        return target

    def relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def setting(self, key, default=None):
        rows = self.rows('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def set_setting(self, key, value):
        if key not in {'drive_mapping'}:
            raise StudioError('Không cho phép lưu thông tin bí mật vào SQLite.')
        self.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))

    def seed_scripts(self, source):
        for script in json.loads(Path(source).read_text(encoding='utf-8')):
            self.execute('INSERT OR IGNORE INTO scripts VALUES(?,1,?)', (script['id'], json.dumps(validate_script(script), ensure_ascii=False)))

    def scripts(self):
        return [dict(json.loads(r['body']), version=r['version']) for r in self.rows('SELECT * FROM scripts ORDER BY id, version DESC')]

    def save_script(self, script):
        body = dict(validate_script(script))
        body.pop('version', None)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            version = c.execute('SELECT COALESCE(MAX(version),0)+1 FROM scripts WHERE id=?', (body['id'],)).fetchone()[0]
            c.execute('INSERT INTO scripts VALUES(?,?,?)', (body['id'], version, json.dumps(body, ensure_ascii=False)))
        return version

    def add_background(self, name, image, description='', family=None):
        if not name.strip() or len(name) > 120:
            raise StudioError('Tên phông nền cần 1–120 ký tự.')
        identity = uid()
        path = self.path(f'backgrounds/{identity}.png')
        if hasattr(image, 'getvalue'):
            image = image.getvalue()
        extension = save_image(image, path)
        original = path.with_name(path.stem + '_original' + extension)
        original.write_bytes(image)
        family = family or identity
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            version = c.execute('SELECT COALESCE(MAX(version),0)+1 FROM backgrounds WHERE family=?', (family,)).fetchone()[0]
            manifest = {'id': identity, 'family': family, 'version': version, 'name': name, 'environment': description[:4000], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'consistency': 'unverified', 'locked_elements': ['room layout', 'rack', 'props', 'lighting', 'hanger', 'same hand']}
            manifest.update(original_file=self.relative(original), original_sha256=hashlib.sha256(image).hexdigest())
            c.execute('INSERT INTO backgrounds(id,name,file,family,version,manifest) VALUES(?,?,?,?,?,?)', (identity, name.strip(), self.relative(path), family, version, json.dumps(manifest, ensure_ascii=False)))
        dump(path.with_suffix('.json'), manifest)
        return identity

    def create_job(self, images, background, script, options):
        validate_script(script)
        if not 1 <= len(images) <= 30:
            raise StudioError('Một sản phẩm cần 1–30 ảnh.')
        allowed = {'mode', 'analysis_model', 'image_provider', 'image_model', 'video_model', 'width', 'height', 'extra_prompt', 'max_calls', 'budget_usd', 'analysis_cost', 'image_cost', 'video_cost', 'cloud_project', 'authorized', 'video_conditioning', 'output_gcs_uri', 'review_before_video', 'ai_quality_review', 'review_cost', 'external_worker'}
        if set(options) - allowed or options.get('mode') not in {'mock', 'real'}:
            raise StudioError('Cấu hình không hợp lệ hoặc có trường bí mật không được phép lưu.')
        if options.get('video_conditioning', 'first_frame') not in {'first_frame', 'continuity', 'asset_references'}:
            raise StudioError('Chế độ tham chiếu video không hợp lệ.')
        if options.get('video_conditioning') == 'asset_references' and options.get('video_model') != 'veo-3.1-generate-001':
            raise StudioError('Bộ tham chiếu hiện chỉ được bật cho Veo 3.1 Generate tiêu chuẩn.')
        if options.get('output_gcs_uri'):
            from .cloud import gcs_location
            gcs_location(options['output_gcs_uri'], prefix=True)
        if options.get('ai_quality_review') and (not isinstance(options.get('review_cost'), (int, float)) or not math.isfinite(options['review_cost']) or options['review_cost'] <= 0):
            raise StudioError('Cần đơn giá ước tính dương cho đánh giá AI.')
        if options['mode'] == 'real':
            for field in ('budget_usd', 'analysis_cost', 'image_cost', 'video_cost'):
                value = options.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise StudioError('Giá và ngân sách phải là số dương hữu hạn.')
            if type(options.get('max_calls')) is not int or not 1 <= options['max_calls'] <= 100:
                raise StudioError('Giới hạn yêu cầu cần từ 1 đến 100.')
        identity = uid()
        folder = self.path(f'jobs/{identity}')
        folder.mkdir(parents=True)
        products, originals = [], []
        for i, content in enumerate(images):
            path = folder / f'product_{i:02}.png'
            extension = save_image(content, path)
            original = folder / f'original_{i:02}{extension}'
            original.write_bytes(content)
            originals.append({'file': self.relative(original), 'sha256': hashlib.sha256(content).hexdigest()})
            products.append(self.relative(path))
        if not products:
            raise StudioError('Cần ít nhất một ảnh sản phẩm.')
        # Freeze source assets and script; later library edits cannot change this job.
        bg = folder / 'background.png'
        bg.write_bytes(self.path(background['file']).read_bytes())
        snapshot = {'schema': 2, 'id': identity, 'products': products, 'originals': originals, 'background_file': self.relative(bg), 'background': json.loads(background['manifest']), 'script': script, 'options': options, 'consistency': {'status': 'unverified', 'warning': 'Cần kiểm tra sai lệch logo, vải và phông nền; không đảm bảo đồng nhất tuyệt đối.'}}
        snapshot['source_hashes'] = {self.relative(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [*(self.path(p) for p in products), bg]}
        dump(folder / 'manifest.json', snapshot)
        self.execute('INSERT INTO jobs(id,product,background_id,script_id,status,mode,snapshot) VALUES(?,?,?,?,?,?,?)', (identity, products[0], background['id'], script['id'], 'queued', options['mode'], json.dumps(snapshot, ensure_ascii=False)))
        return identity

    def job(self, identity):
        rows = self.rows('SELECT * FROM jobs WHERE id=?', (identity,))
        if not rows:
            raise StudioError('Không tìm thấy công việc.')
        return rows[0]

    def claim(self, identity, owner, concurrency=3):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM leases WHERE name='maintenance' AND expires>?", (time.time(),)).fetchone():
                return False
            if c.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] >= concurrency:
                return False
            return c.execute("UPDATE jobs SET status='running',owner=?,heartbeat=?,attempts=attempts+1,error='',pause_requested=0 WHERE id=? AND status IN ('queued','failed','interrupted') AND mode!='legacy'", (owner, time.time(), identity)).rowcount == 1

    def recover(self, seconds=120):
        # Never automatically repeat a paid request after an uncertain shutdown.
        self.execute("UPDATE jobs SET status='interrupted',owner=NULL,error='Ứng dụng bị ngắt. Kiểm tra yêu cầu đang xử lý trước khi tiếp tục.' WHERE status IN ('running','editing') AND heartbeat<?", (time.time() - seconds,))

    def pause(self, identity):
        with self.connect() as c:
            c.execute("UPDATE jobs SET status='paused',pause_requested=1 WHERE id=? AND status='queued'", (identity,))
            c.execute("UPDATE jobs SET pause_requested=1 WHERE id=? AND status='running'", (identity,))

    @contextlib.contextmanager
    def edit_job(self, identity):
        """Exclude workers while changing a stopped job's files or configuration."""
        owner = uid()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM leases WHERE name='maintenance' AND expires>?", (time.time(),)).fetchone():
                raise StudioError('Đang sao lưu/đồng bộ; chờ hoàn tất trước khi thay đổi công việc.')
            row = c.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchone()
            if row is None or row['status'] not in {'failed', 'interrupted', 'complete', 'awaiting_review', 'paused'}:
                raise StudioError('Tạm dừng công việc trước khi thay đổi dữ liệu hoặc hạn mức.')
            job = dict(row)
            c.execute("UPDATE jobs SET status='editing',owner=?,heartbeat=? WHERE id=?", (owner, time.time(), identity))
        try:
            yield job
        except BaseException:
            self.execute("UPDATE jobs SET status='interrupted',owner=NULL WHERE id=? AND owner=? AND status='editing'", (identity, owner))
            raise
        else:
            self.execute("UPDATE jobs SET status=?,owner=NULL WHERE id=? AND owner=? AND status='editing'", (job['status'], identity, owner))

    def update_limits(self, identity, budget_usd, max_calls, authorized=False):
        if type(max_calls) is not int or not 1 <= max_calls <= 100 or not isinstance(budget_usd, (int, float)) or not math.isfinite(budget_usd) or not 0 < budget_usd <= 1000:
            raise StudioError('Hạn mức cần 1–100 yêu cầu và ngân sách dương tối đa 1000 USD.')
        with self.edit_job(identity) as job:
            if job['mode'] != 'real' or not authorized:
                raise StudioError('Cần xác nhận thay đổi hạn mức công việc API thật.')
            if max_calls < job['calls'] or budget_usd < job['reserved_usd']:
                raise StudioError('Hạn mức mới không được nhỏ hơn số đã giữ.')
            snapshot = json.loads(job['snapshot'])
            snapshot['options'].update(budget_usd=budget_usd, max_calls=max_calls)
            dump(self.path(f'jobs/{identity}/manifest.json'), snapshot)
            self.execute('UPDATE jobs SET snapshot=? WHERE id=?', (json.dumps(snapshot, ensure_ascii=False), identity))
            self.execute('INSERT INTO events(job_id,stage,code) VALUES(?,?,?)', (identity, 'limits', 'updated'))

    @contextlib.contextmanager
    def maintenance(self):
        """Quiesce workers and edits across UI/CLI processes while exporting files."""
        owner = uid()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','editing') LIMIT 1").fetchone():
                raise StudioError('Cần tạm dừng hoặc chờ các công việc đang xử lý trước khi sao lưu/đồng bộ.')
            active = c.execute("SELECT 1 FROM leases WHERE name='maintenance' AND expires>?", (time.time(),)).fetchone()
            if active:
                raise StudioError('Một phiên khác đang sao lưu/đồng bộ. Vui lòng chờ.')
            c.execute("INSERT OR REPLACE INTO leases VALUES('maintenance',?,?)", (owner, time.time() + 120))
        stop = threading.Event()
        def renew():
            while not stop.wait(10):
                self.execute("UPDATE leases SET expires=? WHERE name='maintenance' AND owner=?", (time.time() + 120, owner))
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=2)
            self.execute("DELETE FROM leases WHERE name='maintenance' AND owner=?", (owner,))

    def reserve(self, identity, cost):
        if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0:
            raise StudioError('Chi phí dự kiến không hợp lệ.')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = dict(c.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchone())
            opt = json.loads(row['snapshot'])['options']
            if not opt.get('authorized') or opt.get('mode') != 'real':
                raise StudioError('Chưa xác nhận sử dụng API có phí.')
            if row['calls'] >= opt['max_calls'] or row['reserved_usd'] + cost > opt['budget_usd']:
                raise StudioError('Đã chạm giới hạn số yêu cầu hoặc ngân sách ước tính.')
            c.execute('UPDATE jobs SET calls=calls+1,reserved_usd=reserved_usd+? WHERE id=?', (cost, identity))


def save_image(content, destination):
    import io
    from PIL import Image, ImageOps
    if hasattr(content, 'getvalue'):
        content = content.getvalue()
    if len(content) > 20 * 1024 * 1024:
        raise StudioError('Ảnh vượt quá 20 MB.')
    with Image.open(io.BytesIO(content)) as im:
        extension = { 'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp' }.get(im.format)
        if extension is None:
            raise StudioError('Chỉ hỗ trợ ảnh PNG, JPEG và WebP.')
        if im.width * im.height > 40_000_000:
            raise StudioError('Ảnh vượt quá 40 megapixel.')
        im = ImageOps.exif_transpose(im).convert('RGB')
        im.thumbnail((2048, 2048))
        destination.parent.mkdir(parents=True, exist_ok=True)
        im.save(destination, 'PNG')
    return extension
