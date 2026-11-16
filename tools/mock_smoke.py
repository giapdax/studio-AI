"""Generate a real mock MP4 without any network call. Requires Pillow + FFmpeg."""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from studio.jobs import Runner
from studio.media import probe
from studio.storage import Store


def image(color):
    buffer = io.BytesIO()
    Image.new('RGB', (400, 600), color).save(buffer, 'PNG')
    return buffer.getvalue()


store = Store(Path(__file__).resolve().parents[1] / '.test-data' / 'smoke')
store.seed_scripts(Path(__file__).resolve().parents[1] / 'scripts.json')
background_id = store.add_background('Mock room', image('lightgray'), 'Plain gray test room')
bg = store.rows('SELECT * FROM backgrounds WHERE id=?', (background_id,))[0]
script = next(s for s in store.scripts() if s['id'] == 'classic')
job_id = store.create_job([image('navy')], bg, script, {'mode': 'mock', 'width': 1080, 'height': 1920})
runner = Runner(store)
runner.run(job_id)
job = store.job(job_id)
print(json.dumps({'id': job_id, 'status': job['status'], 'error': job['error'], 'output': str(store.path(f'jobs/{job_id}/final_{job_id}.mp4'))}, ensure_ascii=False))
if job['status'] == 'complete':
    print(json.dumps(probe(store.path(f'jobs/{job_id}/final_{job_id}.mp4'))))
runner.pool.shutdown()
sys.exit(0 if job['status'] == 'complete' else 1)
