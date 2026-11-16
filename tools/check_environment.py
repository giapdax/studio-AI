import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.media import check

if sys.version_info < (3, 11):
    print('Can Python 3.11 tro len.')
    sys.exit(1)
def available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


missing = [name for name in ('streamlit', 'PIL', 'imageio_ffmpeg', 'openai', 'google.genai', 'google.cloud.storage', 'keyring') if not available(name)]
if missing:
    print('Thieu thu vien:', ', '.join(missing))
    sys.exit(1)
try:
    print(check())
except Exception:
    print('Thieu FFmpeg. Cai imageio-ffmpeg hoac them ffmpeg vao PATH.')
    sys.exit(1)
print('Moi truong san sang. Khong goi API co phi.')
try:
    from google.genai import types
    from openai import OpenAI
    types.HttpOptions(timeout=20000, retry_options=types.HttpRetryOptions(attempts=1))
    types.GenerateVideosConfig(aspect_ratio='9:16', number_of_videos=1, duration_seconds=8, resolution='1080p', generate_audio=False, reference_images=[types.VideoGenerationReferenceImage(image=types.Image(image_bytes=b'contract-test', mime_type='image/png'), reference_type='asset')])
    with OpenAI(api_key='offline-contract-test') as client:
        assert callable(client.responses.create) and callable(client.images.edit)
    print('SDK ho tro cac truong API dang dung; chua xac minh quyen tai khoan/model.')
except Exception as error:
    print('SDK khong tuong thich:', type(error).__name__, '- hay cai lai requirements.txt.')
    sys.exit(1)
