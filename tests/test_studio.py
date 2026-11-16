import io
from contextlib import closing
import json
import sqlite3
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from studio import backup, media, quality, secrets
from studio.jobs import Runner
from studio.providers import HANGER_VIEWS, MODELS, MockProvider, RealProvider, prompt
from studio.storage import Store, dump, validate_script

BASE = Path(__file__).resolve().parents[1]


def fake_image(content, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return '.png'


class FakeProvider:
    paid = False

    def __init__(self, fail_scene=None):
        self.analysis = 0
        self.references = 0
        self.videos = []
        self.fail_scene = fail_scene

    def analyze(self, products, background):
        self.analysis += 1
        return {'color': 'navy', 'unknown_details': 'unknown'}

    def reference(self, products, background, anchor, text, output, index):
        self.references += 1
        output.write_bytes(b'reference')

    def video(self, reference, text, output, seconds, state, width, height):
        self.videos.append(output.name)
        if output.name == self.fail_scene:
            raise RuntimeError('provider-secret-must-never-be-logged')
        output.write_bytes(b'clip')


def fake_assemble(clips, output):
    if not all(p.exists() for p in clips):
        raise AssertionError('Missing clip')
    output.write_bytes(b'mock-mp4-test-double')


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.seed_scripts(BASE / 'scripts.json')
        self.image_patch = patch('studio.storage.save_image', side_effect=fake_image)
        self.image_patch.start()
        self.quality_patch = patch('studio.jobs.quality.inspect_references', side_effect=lambda refs, bg, mode: {'status': 'unverified', 'issues': [], 'reference_hashes': quality.reference_signature(refs)})
        self.quality_patch.start()
        self.video_check_patch = patch('studio.jobs.media.validate_video', return_value={'codec': 'h264', 'test_double': True})
        self.video_check_patch.start()
        identity = self.store.add_background('Test room', b'bg', 'White room, fixed rack')
        self.background = self.store.rows('SELECT * FROM backgrounds WHERE id=?', (identity,))[0]
        self.script = next(s for s in self.store.scripts() if s['id'] == 'fabric')
        self.options = {'mode': 'mock', 'width': 90, 'height': 160}
        self.runners = []

    def tearDown(self):
        for runner in self.runners:
            runner.pool.shutdown(wait=True)
        self.image_patch.stop()
        self.quality_patch.stop()
        self.video_check_patch.stop()
        self.temp.cleanup()

    def job(self, options=None):
        return self.store.create_job([b'product'], self.background, self.script, options or self.options)

    def runner(self):
        runner = Runner(self.store)
        self.runners.append(runner)
        return runner

    def real_options(self):
        return {'mode': 'real', 'authorized': True, 'max_calls': 2, 'budget_usd': 1, 'analysis_cost': 0.1, 'image_cost': 0.2, 'video_cost': 0.5}

    def test_default_script_durations_and_seed_idempotence(self):
        expected = {'fabric': [3, 2, 3, 3, 2, 2], 'hanger': [3, 3, 4, 3, 2], 'fast': [2, 3, 3, 3, 4], 'logo': [3, 3, 4, 3, 2], 'premium': [4, 4, 4, 4, 4], 'classic': [3, 3, 3, 3]}
        self.store.seed_scripts(BASE / 'scripts.json')
        self.assertEqual({s['id']: s['durations'] for s in self.store.scripts()}, expected)

    def test_script_validation(self):
        for durations, actions in [([0], ['x']), ([9], ['x']), ([True], ['x']), ([2, 3], ['x']), ([2], [''])]:
            with self.subTest(durations=durations, actions=actions), self.assertRaises(ValueError):
                validate_script({'name': 'test', 'durations': durations, 'actions': actions})

    def test_versioned_script_does_not_mutate_job(self):
        identity = self.job()
        script = dict(self.script, name='Changed', durations=[1], actions=['New action'])
        self.assertEqual(self.store.save_script(script), 2)
        snapshot = json.loads(self.store.job(identity)['snapshot'])
        self.assertEqual(snapshot['script']['durations'], [3, 2, 3, 3, 2, 2])
        self.assertEqual(len([s for s in self.store.scripts() if s['id'] == 'fabric']), 2)

    def test_background_version_and_source_snapshot(self):
        identity = self.job()
        newer = self.store.add_background('New', b'new-image', family=self.background['family'])
        self.assertEqual(self.store.rows('SELECT version FROM backgrounds WHERE id=?', (newer,))[0]['version'], 2)
        self.store.execute('UPDATE backgrounds SET deleted=1 WHERE id=?', (self.background['id'],))
        snap = json.loads(self.store.job(identity)['snapshot'])
        self.assertEqual(self.store.path(snap['background_file']).read_bytes(), b'bg')

    def test_grouping_and_original_preservation(self):
        identity = self.store.create_job([b'front', b'side'], self.background, self.script, self.options)
        snap = json.loads(self.store.job(identity)['snapshot'])
        self.assertEqual(len(snap['products']), 2)
        self.assertEqual(self.store.path(snap['originals'][1]['file']).read_bytes(), b'side')
        self.assertEqual(len(self.store.rows('SELECT * FROM jobs')), 1)

    def test_paths_reject_escape(self):
        for value in ('../outside', str(self.root / 'outside')):
            with self.assertRaises(ValueError):
                self.store.path(value)

    def test_settings_and_options_reject_secrets(self):
        with self.assertRaises(ValueError):
            self.store.set_setting('api_key', 'secret')
        with self.assertRaises(ValueError):
            self.job(dict(self.options, api_key='secret'))

    def test_single_atomic_claim(self):
        identity = self.job()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: self.store.claim(identity, str(n)), range(6)))
        self.assertEqual(sum(results), 1)

    def test_recovery_does_not_requeue_paid_job(self):
        identity = self.job(self.real_options())
        self.store.claim(identity, 'old-worker')
        self.store.execute('UPDATE jobs SET heartbeat=0 WHERE id=?', (identity,))
        self.store.recover()
        self.assertEqual(self.store.job(identity)['status'], 'interrupted')
        self.assertEqual(self.store.job(identity)['calls'], 0)

    def test_active_heartbeat_not_recovered(self):
        identity = self.job()
        self.store.claim(identity, 'alive')
        self.store.recover()
        self.assertEqual(self.store.job(identity)['status'], 'running')

    def test_cost_limit_and_call_limit(self):
        identity = self.job(self.real_options())
        self.store.reserve(identity, 0.2)
        self.store.reserve(identity, 0.3)
        with self.assertRaises(ValueError):
            self.store.reserve(identity, 0.1)
        self.assertEqual(self.store.job(identity)['calls'], 2)
        other = self.job(self.real_options())
        with self.assertRaises(ValueError):
            self.store.reserve(other, 1.1)
        self.assertEqual(self.store.job(other)['reserved_usd'], 0)

    def test_unauthorized_paid_calls_blocked(self):
        identity = self.job(dict(self.real_options(), authorized=False))
        with self.assertRaises(ValueError):
            self.store.reserve(identity, 0.1)
        self.assertEqual(self.store.job(identity)['calls'], 0)

    def test_nonfinite_cost_rejected(self):
        for value in (float('nan'), float('inf'), -1, 0):
            with self.assertRaises(ValueError):
                self.job(dict(self.real_options(), budget_usd=value))

    def test_mock_orchestration_and_resume_skips_completed_steps(self):
        identity = self.job()
        provider = FakeProvider(fail_scene='scene_03.mp4')
        runner = self.runner()
        with patch('studio.jobs.media.check'), patch('studio.jobs.media.assemble', side_effect=fake_assemble):
            runner.run(identity, provider=provider)
            self.assertEqual(self.store.job(identity)['status'], 'failed')
            self.assertNotIn('provider-secret', self.store.job(identity)['error'])
            provider.fail_scene = None
            runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'complete')
        self.assertEqual(provider.analysis, 1)
        self.assertEqual(provider.references, 5)
        self.assertEqual(provider.videos.count('scene_01.mp4'), 1)
        self.assertEqual(provider.videos.count('scene_03.mp4'), 2)
        self.assertEqual(self.store.job(identity)['calls'], 0)

    def test_independent_failure_does_not_block_other_product(self):
        first, second = self.job(), self.job()
        runner = self.runner()
        with patch('studio.jobs.media.check'), patch('studio.jobs.media.assemble', side_effect=fake_assemble):
            runner.run(first, provider=FakeProvider(fail_scene='scene_01.mp4'))
            runner.run(second, provider=FakeProvider())
        self.assertEqual(self.store.job(first)['status'], 'failed')
        self.assertEqual(self.store.job(second)['status'], 'complete')

    def test_retry_only_one_scene_archives_old_output(self):
        identity = self.job()
        provider = FakeProvider()
        runner = self.runner()
        with patch('studio.jobs.media.check'), patch('studio.jobs.media.assemble', side_effect=fake_assemble):
            runner.run(identity, provider=provider)
            runner.retry_scene(identity, 2)
            runner.run(identity, provider=provider)
        self.assertEqual(provider.videos.count('scene_02.mp4'), 2)
        self.assertEqual(provider.videos.count('scene_01.mp4'), 1)
        self.assertTrue(list(self.store.path(f'jobs/{identity}/history').rglob('scene_02.mp4')))

    def test_backup_roundtrip_credentials_excluded(self):
        identity = self.job()
        (self.store.root / '.private').mkdir()
        (self.store.root / '.private/token.json').write_text('secret')
        (self.store.root / '.env').write_text('secret')
        content = backup.export_backup(self.store)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any('.private' in n or '.env' in n for n in archive.namelist()))
        destination = backup.restore_backup(content, self.root / 'restores')
        other = Store(destination)
        self.assertEqual(other.job(identity)['status'], 'interrupted')
        snap = json.loads(other.job(identity)['snapshot'])
        self.assertTrue(other.path(snap['products'][0]).exists())
        self.assertNotEqual(destination, self.store.root)

    def test_background_export_import(self):
        content = backup.export_backup(self.store, backgrounds_only=True)
        self.assertEqual(backup.import_backgrounds(self.store, content), 1)
        self.assertEqual(len(self.store.rows('SELECT * FROM backgrounds')), 2)

    def test_zip_traversal_and_unknown_files_rejected(self):
        for name in ('../escape.txt', '/absolute', 'C:/windows', 'jobs/../../outside', 'jobs\\escape', '.private/token.json', 'jobs/.. /escape', 'jobs/CON.txt'):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('backup.json', '{"schema":2,"kind":"full"}')
                entry = zipfile.ZipInfo('safe')
                entry.filename = name  # Avoid ZipInfo normalizing backslashes on Windows.
                archive.writestr(entry, 'evil')
            with self.subTest(name=name), self.assertRaises(ValueError):
                backup.validated_archive(buffer.getvalue())

    def test_legacy_migration_preserves_data(self):
        legacy = self.root / 'legacy'
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / 'studio.sqlite3')) as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, product TEXT, background_id TEXT, script_id TEXT, status TEXT, created TEXT)')
            c.execute("INSERT INTO jobs VALUES('old','product.png','bg','fabric','complete','yesterday')")
            c.commit()
        migrated = Store(legacy)
        self.assertEqual(migrated.job('old')['status'], 'complete')
        self.assertEqual(migrated.job('old')['mode'], 'legacy')
        Store(legacy)  # Migrations can run repeatedly.

    def test_hanger_prompts_never_request_touching_fabric(self):
        identity = self.job()
        snap = json.loads(self.store.job(identity)['snapshot'])
        snap['script']['id'] = 'hanger'
        for action in HANGER_VIEWS:
            self.assertIn('never touch or pinch fabric', prompt(snap, {}, action))
        self.assertFalse(MockProvider().paid)

    def test_video_duration_normalization_uses_explicit_ffmpeg_args(self):
        folder = self.root / 'media'
        folder.mkdir()
        output = folder / 'result.mp4'
        def run(arguments):
            self.assertIn('libx264', arguments)
            self.assertIn('yuv420p', arguments)
            self.assertIn('3', [str(x) for x in arguments])
            self.assertTrue(any('fps=30' in str(x) for x in arguments))
            Path(arguments[-1]).write_bytes(b'normalized')
        with patch('studio.media.run', side_effect=run), patch('studio.media.encoder_options', return_value=['-c:v', 'libx264', '-preset', 'fast']):
            media.normalize(folder / 'raw.mp4', output, 3)
        self.assertEqual(output.read_bytes(), b'normalized')

    def test_vault_rejects_plaintext_backend(self):
        import types
        backend = types.SimpleNamespace(get_keyring=lambda: object())
        with patch.dict('sys.modules', {'keyring': backend}):
            with self.assertRaises(RuntimeError):
                secrets.vault()

    def test_paid_provider_cannot_run_under_mock_job(self):
        identity = self.job()
        provider = FakeProvider()
        provider.paid = True
        with patch('studio.jobs.media.check'):
            self.runner().run(identity, provider=provider)
        self.assertEqual(provider.analysis, 0)
        self.assertEqual(self.store.job(identity)['status'], 'failed')

    def test_veo_adapter_duration_and_resume_contract_without_network(self):
        import types
        from unittest.mock import Mock
        options = dict(self.real_options(), analysis_model=MODELS['analysis'][0], image_provider='openai', image_model=MODELS['openai_image'][0], video_model=MODELS['video'][0], cloud_project='test-project')
        provider = RealProvider(options, '', '')
        operation = types.SimpleNamespace(name='projects/test/operations/saved', done=True, error=None, response=types.SimpleNamespace(generated_videos=[types.SimpleNamespace(video=types.SimpleNamespace(video_bytes=b'mp4'))]))
        client = Mock()
        client.models.generate_videos.return_value = operation
        client.operations.get.return_value = operation
        sdk_types = types.ModuleType('google.genai.types')
        for name in ('Image', 'GenerateVideosConfig', 'GenerateVideosOperation', 'HttpOptions', 'HttpRetryOptions'):
            setattr(sdk_types, name, lambda **kwargs: types.SimpleNamespace(**kwargs))
        genai = types.ModuleType('google.genai')
        genai.Client = Mock(return_value=client)
        genai.types = sdk_types
        google = types.ModuleType('google')
        google.genai = genai
        modules = {'google': google, 'google.genai': genai, 'google.genai.types': sdk_types}
        reference = self.root / 'ref.png'
        reference.write_bytes(b'ref')
        with patch.dict('sys.modules', modules), patch('studio.providers.media.normalize'):
            for requested, supported in [(2, 4), (5, 6), (8, 8)]:
                state = self.root / f'op_{requested}.json'
                output = self.root / f'clip_{requested}.mp4'
                provider.video(reference, 'English prompt', output, requested, state, 1080, 1920)
                config = client.models.generate_videos.call_args.kwargs['config']
                self.assertEqual(config.duration_seconds, supported)
                self.assertEqual(config.aspect_ratio, '9:16')
                self.assertEqual(json.loads(state.read_text())['name'], operation.name)
            submitted = client.models.generate_videos.call_count
            output.with_name(output.stem + '_raw.mp4').unlink()
            provider.video(reference, 'English prompt', output, requested, state, 1080, 1920)
            self.assertEqual(client.models.generate_videos.call_count, submitted)
            self.assertTrue(client.operations.get.called)
            self.assertTrue(genai.Client.call_args.kwargs['vertexai'])

    def test_unsupported_models_blocked_before_network(self):
        options = dict(self.real_options(), analysis_model='invented', image_provider='openai', image_model=MODELS['openai_image'][0], video_model=MODELS['video'][0])
        with self.assertRaises(ValueError):
            RealProvider(options, '', '')


class RealMockMediaTests(unittest.TestCase):
    def test_mock_mp4_with_real_ffmpeg(self):
        try:
            from PIL import Image
            media.check()
        except (ImportError, RuntimeError, FileNotFoundError):
            self.skipTest('Requires Pillow and FFmpeg; no network/paid API is used.')
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'data')
            store.seed_scripts(BASE / 'scripts.json')
            buffer = io.BytesIO()
            Image.new('RGB', (100, 150), 'blue').save(buffer, 'PNG')
            content = buffer.getvalue()
            background_id = store.add_background('Room', content)
            bg = store.rows('SELECT * FROM backgrounds WHERE id=?', (background_id,))[0]
            script = next(s for s in store.scripts() if s['id'] == 'classic')
            identity = store.create_job([content], bg, script, {'mode': 'mock', 'width': 90, 'height': 160})
            runner = Runner(store)
            try:
                runner.run(identity)
            finally:
                runner.pool.shutdown()
            self.assertEqual(store.job(identity)['status'], 'complete', store.job(identity)['error'])
            final = store.path(f'jobs/{identity}/final_{identity}.mp4')
            self.assertIn(b'ftyp', final.read_bytes()[:32])
            self.assertEqual(len(list(final.parent.glob('reference_*.png'))), 5)
            # Decode through FFmpeg to validate the container/frames rather than file extension.
            media.run(['-i', final, '-f', 'null', '-'])


if __name__ == '__main__':
    unittest.main()
