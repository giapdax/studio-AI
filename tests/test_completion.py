import importlib.util
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from studio import backup, cloud, drive, media, quality
from studio.errors import StudioError
from studio.jobs import Runner
from studio.providers import MODELS, RealProvider, clip_duration
from studio.storage import Store
from studio.worker import eligible_jobs


BASE = Path(__file__).resolve().parents[1]


def save_fake_image(content, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return '.png'


class Provider:
    paid = False

    def __init__(self):
        self.inputs = []
        self.references = []

    def analyze(self, products, background):
        return {'color': 'blue'}

    def reference(self, products, background, anchor, text, output, index):
        self.references.append(index)
        output.write_bytes(f'ref-{index}-{len(self.references)}'.encode())

    def video(self, reference, text, output, seconds, state, width, height, **kwargs):
        self.inputs.append((output.name, reference.name, kwargs))
        output.write_bytes(b'clip')


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.seed_scripts(BASE / 'scripts.json')
        self.image_patch = patch('studio.storage.save_image', side_effect=save_fake_image)
        self.image_patch.start()
        self.addCleanup(self.image_patch.stop)
        self.quality_patch = patch('studio.jobs.quality.inspect_references', side_effect=lambda refs, bg, mode: {'status': 'unverified', 'issues': [], 'reference_hashes': quality.reference_signature(refs)})
        self.quality_patch.start()
        self.addCleanup(self.quality_patch.stop)
        self.media_patch = patch('studio.jobs.media.check')
        self.media_patch.start()
        self.addCleanup(self.media_patch.stop)
        self.assemble_patch = patch('studio.jobs.media.assemble', side_effect=lambda clips, out: out.write_bytes(b'final'))
        self.assemble_patch.start()
        self.addCleanup(self.assemble_patch.stop)
        self.video_check_patch = patch('studio.jobs.media.validate_video', return_value={'codec': 'h264', 'test_double': True})
        self.video_check_patch.start()
        self.addCleanup(self.video_check_patch.stop)
        bg_id = self.store.add_background('Room', b'bg')
        self.bg = self.store.rows('SELECT * FROM backgrounds WHERE id=?', (bg_id,))[0]
        self.script = next(s for s in self.store.scripts() if s['id'] == 'classic')
        self.runner = Runner(self.store)

    def tearDown(self):
        self.runner.pool.shutdown(wait=True)
        self.temp.cleanup()

    def job(self, **options):
        config = dict(mode='mock', width=90, height=160)
        config.update(options)
        return self.store.create_job([b'product'], self.bg, self.script, config)

    def test_review_gate_blocks_video_until_matching_images_approved(self):
        identity = self.job(review_before_video=True)
        provider = Provider()
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'awaiting_review')
        self.assertEqual(provider.inputs, [])
        self.runner.approve_references(identity, True, 'Checked garment and room')
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'complete')
        self.assertEqual(len(provider.references), 5)
        self.assertEqual(len(provider.inputs), 4)

    def test_review_hash_invalidated_after_reference_regeneration(self):
        identity = self.job(review_before_video=True)
        provider = Provider()
        self.runner.run(identity, provider=provider)
        self.runner.approve_references(identity, True)
        self.runner.run(identity, provider=provider)
        self.runner.retry_reference(identity, 3)
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'awaiting_review')
        self.assertEqual(provider.references.count(2), 2)
        self.assertEqual(provider.references.count(0), 1)
        self.assertEqual(len(provider.inputs), 4)
        folder = self.store.path(f'jobs/{identity}')
        self.assertFalse((folder / f'final_{identity}.mp4').exists())
        self.assertTrue(list((folder / 'history').rglob('scene_01.mp4')))

    def test_regenerating_anchor_rebuilds_all_five_views(self):
        identity = self.job()
        provider = Provider()
        self.runner.run(identity, provider=provider)
        self.runner.retry_reference(identity, 1)
        self.runner.run(identity, provider=provider)
        self.assertEqual(provider.references, [0, 1, 2, 3, 4] * 2)

    def test_continuity_uses_trimmed_previous_frame_and_invalidates_tail(self):
        identity = self.job(video_conditioning='continuity')
        provider = Provider()
        with patch('studio.jobs.media.last_frame', side_effect=lambda src, out: out.write_bytes(b'frame')):
            self.runner.run(identity, provider=provider)
            self.assertEqual(provider.inputs[1][1], 'last_frame_01.png')
            self.runner.retry_scene(identity, 2)
            self.runner.run(identity, provider=provider)
        names = [entry[0] for entry in provider.inputs]
        self.assertEqual(names.count('scene_01.mp4'), 1)
        for scene in (2, 3, 4):
            self.assertEqual(names.count(f'scene_{scene:02}.mp4'), 2)

    def test_pause_stops_before_next_expensive_step(self):
        identity = self.job()
        provider = Provider()
        original = provider.analyze
        def analyze(products, background):
            self.store.pause(identity)
            return original(products, background)
        provider.analyze = analyze
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'paused')
        self.assertEqual(provider.references, [])
        self.assertTrue(self.store.path(f'jobs/{identity}/identity.json').exists())

    def test_paused_queue_cannot_be_claimed_implicitly(self):
        identity = self.job()
        self.store.pause(identity)
        self.assertFalse(self.store.claim(identity, 'worker'))
        self.assertEqual(eligible_jobs(self.store), [])

    def test_maintenance_blocks_claim_edit_and_concurrent_backup(self):
        identity = self.job()
        with self.store.maintenance():
            self.assertFalse(self.store.claim(identity, 'worker'))
            with self.assertRaises(StudioError):
                with self.store.maintenance():
                    pass
        self.assertTrue(self.store.claim(identity, 'worker'))
        with self.assertRaises(StudioError):
            backup.export_backup(self.store)

    def test_global_concurrency_applies_across_runner_instances(self):
        first, second = self.job(), self.job()
        self.assertTrue(self.store.claim(first, 'one', concurrency=1))
        self.assertFalse(self.store.claim(second, 'two', concurrency=1))

    def test_edit_guard_blocks_running_job(self):
        identity = self.job()
        self.store.claim(identity, 'worker')
        with self.assertRaises(StudioError):
            self.runner.retry_reference(identity, 1)

    def test_limits_change_preserves_used_amount_and_requires_consent(self):
        identity = self.job(mode='real', authorized=True, max_calls=10, budget_usd=5, analysis_cost=0.1, image_cost=0.1, video_cost=0.1)
        self.store.reserve(identity, 0.2)
        self.store.execute("UPDATE jobs SET status='failed' WHERE id=?", (identity,))
        with self.assertRaises(StudioError):
            self.store.update_limits(identity, 10, 20)
        with self.assertRaises(StudioError):
            self.store.update_limits(identity, 0.1, 20, authorized=True)
        self.store.update_limits(identity, 10, 20, authorized=True)
        job = self.store.job(identity)
        self.assertEqual(job['reserved_usd'], 0.2)
        self.assertEqual(job['calls'], 1)
        self.assertEqual(json.loads(job['snapshot'])['options']['budget_usd'], 10)
        self.assertEqual(job['status'], 'interrupted')  # Failed guarded edit requires explicit resume.

    def test_worker_does_not_select_paid_jobs_by_default(self):
        mock = self.job()
        real = self.job(mode='real', authorized=True, max_calls=10, budget_usd=5, analysis_cost=0.1, image_cost=0.1, video_cost=0.1)
        unauthorized = self.job(mode='real', authorized=False, max_calls=10, budget_usd=5, analysis_cost=0.1, image_cost=0.1, video_cost=0.1)
        self.assertEqual({job['id'] for job in eligible_jobs(self.store)}, {mock})
        self.assertEqual({job['id'] for job in eligible_jobs(self.store, allow_paid=True)}, {mock, real})
        self.assertNotIn(unauthorized, {job['id'] for job in eligible_jobs(self.store, allow_paid=True)})

    def test_disk_backup_roundtrip_has_no_stale_lease(self):
        identity = self.job()
        target = self.root / 'export.zip'
        self.assertEqual(backup.export_backup(self.store, destination=target), target)
        restored = Store(backup.restore_backup(target, self.root / 'restores'))
        self.assertEqual(restored.rows('SELECT * FROM leases'), [])
        self.assertEqual(restored.job(identity)['status'], 'interrupted')

    def test_gcs_download_validates_size_generation_and_uses_atomic_path(self):
        client = Mock()
        blob = client.bucket.return_value.blob.return_value
        blob.size = 3
        blob.generation = 7
        blob.download_to_filename.side_effect = lambda filename, **kw: Path(filename).write_bytes(b'mp4')
        destination = self.root / 'video.mp4'
        cloud.download_video('gs://fashion-bucket/clip.mp4', destination, 'test', client)
        self.assertEqual(destination.read_bytes(), b'mp4')
        self.assertEqual(blob.download_to_filename.call_args.kwargs['if_generation_match'], 7)
        self.assertEqual(blob.download_to_filename.call_args.kwargs['checksum'], 'auto')
        blob.size = cloud.MAX_VIDEO_BYTES + 1
        blob.download_to_filename.reset_mock()
        with self.assertRaises(StudioError):
            cloud.download_video('gs://fashion-bucket/clip.mp4', destination, 'test', client)
        blob.download_to_filename.assert_not_called()

    def test_gcs_rejects_http_and_credential_urls(self):
        for uri in ('https://example.com/a', 'gs://user:password@bucket/a', 'gs://bucket', 'gs://bucket/a?token=secret'):
            with self.subTest(uri=uri), self.assertRaises(StudioError):
                cloud.gcs_location(uri)

    def test_duration_estimate_matches_asset_reference_requests(self):
        self.assertEqual([clip_duration(n) for n in (1, 4, 5, 7)], [4, 4, 6, 8])
        self.assertEqual([clip_duration(n, 'asset_references') for n in (1, 4, 5, 7)], [8] * 4)

    def test_ai_quality_review_does_not_repeat_when_images_unchanged(self):
        identity = self.job(mode='real', authorized=True, max_calls=30, budget_usd=10, analysis_cost=0.1, image_cost=0.1, video_cost=0.1, ai_quality_review=True, review_cost=0.1)
        provider = Provider()
        provider.paid = True
        provider.review = Mock(return_value={'status': 'flagged', 'checks': []})
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'awaiting_review')
        self.assertEqual(provider.inputs, [])
        calls_before = self.store.job(identity)['calls']
        self.runner.approve_references(identity, True)
        self.runner.run(identity, provider=provider)
        self.assertEqual(provider.review.call_count, 1)
        self.assertEqual(self.store.job(identity)['calls'], calls_before + 4)

    def test_source_tampering_is_blocked_before_generation(self):
        identity = self.job()
        snapshot = json.loads(self.store.job(identity)['snapshot'])
        self.store.path(snapshot['products'][0]).write_bytes(b'changed product')
        provider = Provider()
        self.runner.run(identity, provider=provider)
        self.assertEqual(self.store.job(identity)['status'], 'failed')
        self.assertIn('Ảnh nguồn đã thay đổi', self.store.job(identity)['error'])
        self.assertEqual(provider.references, [])

    def test_library_roundtrip_preserves_version_family_and_originals(self):
        self.store.add_background('Room v2', b'new original bytes', family=self.bg['family'])
        content = backup.export_backup(self.store, backgrounds_only=True)
        target = Store(self.root / 'other-library')
        self.assertEqual(backup.import_backgrounds(target, content), 2)
        rows = target.rows('SELECT * FROM backgrounds ORDER BY version')
        self.assertEqual([row['version'] for row in rows], [1, 2])
        self.assertEqual(rows[0]['family'], rows[1]['family'])
        manifest = json.loads(rows[1]['manifest'])
        self.assertEqual(target.path(manifest['original_file']).read_bytes(), b'new original bytes')

    def test_metadata_validation_rejects_wrong_output(self):
        self.video_check_patch.stop()
        good = {'size': [1080, 1920], 'fps': 30, 'duration': 15, 'codec': 'h264'}
        for override in ({'size': [1920, 1080]}, {'fps': 24}, {'duration': 14}, {'codec': 'mpeg4'}):
            with self.subTest(override=override), patch('studio.media.probe', return_value=dict(good, **override)), self.assertRaises(StudioError):
                media.validate_video(self.root / 'video.mp4', 1080, 1920, 15)

    def test_invalid_assembled_video_is_not_published_as_final(self):
        identity = self.job()
        with patch('studio.jobs.media.validate_video', side_effect=StudioError('Video failed validation')):
            self.runner.run(identity, provider=Provider())
        self.assertEqual(self.store.job(identity)['status'], 'failed')
        self.assertFalse(self.store.path(f'jobs/{identity}/final_{identity}.mp4').exists())

    def test_drive_account_switch_blocks_old_mapping(self):
        self.store.set_setting('drive_mapping', {'account': 'old@example.invalid', 'folders': drive.DEFAULT_MAPPING})
        with patch('studio.drive.service', return_value=Mock()), patch('studio.drive.account', return_value={'emailAddress': 'new@example.invalid'}), patch('studio.drive.verify_mapping') as verify:
            with self.assertRaises(StudioError):
                drive.configured_service(self.store)
            verify.assert_not_called()

    def test_veo_assets_use_three_images_and_gcs_result_without_resubmit(self):
        options = dict(mode='real', analysis_model=MODELS['analysis'][0], image_provider='openai', image_model=MODELS['openai_image'][0], video_model=MODELS['video'][0], cloud_project='test-project', video_conditioning='asset_references', output_gcs_uri='gs://fashion-bucket/output/')
        provider = RealProvider(options, '', '')
        operation = types.SimpleNamespace(name='operation/test', done=True, error=None, response=types.SimpleNamespace(generated_videos=[types.SimpleNamespace(video=types.SimpleNamespace(video_bytes=None, uri='gs://fashion-bucket/video.mp4'))]))
        client = Mock()
        client.models.generate_videos.return_value = operation
        sdk_types = types.ModuleType('google.genai.types')
        for name in ('Image', 'GenerateVideosConfig', 'GenerateVideosOperation', 'HttpOptions', 'HttpRetryOptions', 'VideoGenerationReferenceImage'):
            setattr(sdk_types, name, lambda **kw: types.SimpleNamespace(**kw))
        genai = types.ModuleType('google.genai')
        genai.Client = Mock(return_value=client)
        genai.types = sdk_types
        google = types.ModuleType('google')
        google.genai = genai
        modules = {'google': google, 'google.genai': genai, 'google.genai.types': sdk_types}
        assets = [self.root / f'asset_{n}.png' for n in range(3)]
        for asset in assets:
            asset.write_bytes(b'image')
        output, state = self.root / 'scene.mp4', self.root / 'operation.json'
        with patch.dict('sys.modules', modules), patch('studio.providers.cloud.download_video', side_effect=lambda uri, out, project: out.write_bytes(b'raw')), patch('studio.providers.media.normalize'):
            provider.video(assets[0], 'English prompt', output, 3, state, 1080, 1920, asset_references=assets)
            arguments = client.models.generate_videos.call_args.kwargs
            self.assertNotIn('image', arguments)
            self.assertEqual(arguments['config'].duration_seconds, 8)
            self.assertEqual(len(arguments['config'].reference_images), 3)
            self.assertEqual(arguments['config'].output_gcs_uri, options['output_gcs_uri'])
            provider.video(assets[0], 'English prompt', output, 3, state, 1080, 1920, asset_references=assets)
            self.assertEqual(client.models.generate_videos.call_count, 1)


@unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow is not installed.')
class QualityImageTests(unittest.TestCase):
    def test_blank_images_flagged_without_semantic_claim(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refs = [root / f'{i}.png' for i in range(5)]
            for path in refs:
                Image.new('RGB', (540, 960), 'black').save(path)
            report = quality.inspect_references(refs, refs[0])
            self.assertEqual(report['status'], 'flagged')
            self.assertFalse(report['semantic_identity_verified'])
            self.assertTrue(any(issue['code'] == 'near_blank' for issue in report['issues']))


if __name__ == '__main__':
    unittest.main()
