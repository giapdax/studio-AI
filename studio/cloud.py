"""Strict GCS URI validation and ADC-authenticated, bounded downloads."""
import re
from urllib.parse import urlsplit

from .errors import StudioError

MAX_VIDEO_BYTES = 1024 ** 3


def gcs_location(uri, prefix=False):
    if not isinstance(uri, str) or any(ord(c) < 32 for c in uri):
        raise StudioError('URI GCS không hợp lệ.')
    parsed = urlsplit(uri)
    if parsed.scheme != 'gs' or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', parsed.netloc) or parsed.query or parsed.fragment or '@' in parsed.netloc:
        raise StudioError('Cần URI gs://bucket/object hợp lệ, không dùng URL HTTP.')
    name = parsed.path.lstrip('/')
    if not prefix and not name:
        raise StudioError('URI GCS cần tên đối tượng.')
    return parsed.netloc, name


def download_video(uri, destination, project, client=None):
    bucket_name, object_name = gcs_location(uri)
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=project)
    blob = client.bucket(bucket_name).blob(object_name)
    blob.reload(timeout=60, retry=None)
    if blob.size is None or not 0 < blob.size <= MAX_VIDEO_BYTES:
        raise StudioError('Video GCS trống hoặc vượt giới hạn tải 1 GB.')
    temporary = destination.with_name(destination.stem + '.download.partial.mp4')
    try:
        # Pin the generation to avoid downloading an object changed after metadata check.
        blob.download_to_filename(str(temporary), timeout=(15, 180), retry=None, checksum='auto', if_generation_match=blob.generation)
        if temporary.stat().st_size != blob.size:
            raise StudioError('Video tải từ GCS không khớp kích thước.')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
