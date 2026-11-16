"""Optional Drive storage. OAuth credentials live only in the OS vault."""
from .errors import StudioError
import hashlib
import io
import json
import mimetypes

from . import secrets

DEFAULT_MAPPING = {
    'Root': '1gv07p8bIPpiPxsza2eSGDFJdeibB_sk0',
    'Products': '13cFcSbmFW4yhHmsObH4YW8ZPW517xjk7',
    'Backgrounds': '1VvRKrZu5SP2Amm3QB2IXrZL1fOHPXSR5',
    'References': '12juANeUnJmivfnV8dGM0v4ojn6jBVgIZ',
    'Clips': '1-CbtekRfGtAzv3PDAFuTEWUyBW4n4xuT',
    'Final': '1q7G-52w4HKDjtaMM-DmpdyU9Mmlp_Koe',
    'Projects': '1ac9YF8AleSX4K0csjH_pkSVI_R3oQGKG',
    'Backups': '1wcQNT94ApMhsXjFjLMzQgdFeC0BkrLDK',
}
SCOPES = ['https://www.googleapis.com/auth/drive.file']


def connect(client_json=None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    secrets.vault()  # Fail before browser OAuth if secure storage is unavailable.
    token = secrets.read('drive_token')
    cred = Credentials.from_authorized_user_info(json.loads(token), SCOPES) if token else None
    if cred and cred.expired and cred.refresh_token:
        cred.refresh(Request())
    if not cred or not cred.valid:
        config = client_json or secrets.read('drive_client')
        if not config:
            raise StudioError('Chọn JSON OAuth Desktop trong cài đặt Drive.')
        parsed = json.loads(config)
        if 'installed' not in parsed:
            raise StudioError('Cần OAuth loại Desktop.')
        cred = InstalledAppFlow.from_client_config(parsed, SCOPES).run_local_server(port=0, timeout_seconds=180)
        secrets.save('drive_client', config)
    secrets.save('drive_token', cred.to_json())
    return service(cred)


def service(credentials=None):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_httplib2 import AuthorizedHttp
    import httplib2
    if credentials is None:
        token = secrets.read('drive_token')
        if not token:
            raise StudioError('Chưa kết nối Google Drive.')
        credentials = Credentials.from_authorized_user_info(json.loads(token), SCOPES)
    return build('drive', 'v3', http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=60)), cache_discovery=False)


def account(svc):
    return svc.about().get(fields='user(emailAddress,displayName)').execute()['user']


def create_mapping(svc):
    mapping = {}
    for name in DEFAULT_MAPPING:
        metadata = {'name': 'Fashion AI Studio' if name == 'Root' else name, 'mimeType': 'application/vnd.google-apps.folder'}
        if name != 'Root':
            metadata['parents'] = [mapping['Root']]
        mapping[name] = svc.files().create(body=metadata, fields='id').execute()['id']
    return mapping


def verify_mapping(svc, mapping):
    if set(mapping) != set(DEFAULT_MAPPING):
        raise StudioError('Mapping cần đủ tám thư mục như mapping mẫu.')
    for name, identity in mapping.items():
        if not isinstance(identity, str) or not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identity):
            raise StudioError('ID thư mục không hợp lệ.')
        metadata = svc.files().get(fileId=identity, fields='id,mimeType,trashed,capabilities(canAddChildren)').execute()
        if metadata.get('trashed') or metadata['mimeType'] != 'application/vnd.google-apps.folder' or not metadata.get('capabilities', {}).get('canAddChildren'):
            raise StudioError(f'Không có quyền ghi thư mục {name}.')


def upload(svc, mapping, relative, content, category):
    from googleapiclient.http import MediaIoBaseUpload
    parent = mapping[category]
    identity = hashlib.sha256(relative.encode()).hexdigest()
    digest = hashlib.sha256(content).hexdigest()
    existing = svc.files().list(q=f"'{parent}' in parents and trashed=false and appProperties has {{ key='studio_path' and value='{identity}' }}", fields='files(id,appProperties)', pageSize=100).execute().get('files', [])
    if existing and existing[0].get('appProperties', {}).get('sha256') == digest:
        return existing[0]['id']
    metadata = {'name': relative.replace('/', '__'), 'appProperties': {'studio_path': identity, 'sha256': digest}}
    mime = 'application/zip' if relative.lower().endswith('.zip') else mimetypes.guess_type(relative)[0] or 'application/octet-stream'
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime, resumable=True)
    if existing:
        return svc.files().update(fileId=existing[0]['id'], body=metadata, media_body=media, fields='id').execute()['id']
    metadata['parents'] = [parent]
    return svc.files().create(body=metadata, media_body=media, fields='id').execute()['id']


def upload_path(svc, mapping, relative, path, category):
    from googleapiclient.http import MediaFileUpload
    from .quality import fingerprint
    parent = mapping[category]
    identity = hashlib.sha256(relative.encode()).hexdigest()
    digest = fingerprint(path)
    existing = svc.files().list(q=f"'{parent}' in parents and trashed=false and appProperties has {{ key='studio_path' and value='{identity}' }}", fields='files(id,appProperties)', pageSize=100).execute().get('files', [])
    if existing and existing[0].get('appProperties', {}).get('sha256') == digest:
        return existing[0]['id']
    metadata = {'name': relative.replace('/', '__'), 'appProperties': {'studio_path': identity, 'sha256': digest}}
    mime = 'application/zip' if relative.lower().endswith('.zip') else mimetypes.guess_type(relative)[0] or 'application/octet-stream'
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
    if existing:
        return svc.files().update(fileId=existing[0]['id'], body=metadata, media_body=media, fields='id').execute()['id']
    metadata['parents'] = [parent]
    return svc.files().create(body=metadata, media_body=media, fields='id').execute()['id']


def configured_service(store):
    svc = service()
    configured = store.setting('drive_mapping')
    if not configured or configured['account'] != account(svc)['emailAddress']:
        raise StudioError('Tài khoản khác mapping đã lưu. Chọn mapping mới trước khi chuyển dữ liệu.')
    verify_mapping(svc, configured['folders'])
    return svc, configured['folders']


def list_backups(store):
    svc, mapping = configured_service(store)
    results, page = [], None
    while True:
        response = svc.files().list(q=f"'{mapping['Backups']}' in parents and trashed=false and (mimeType='application/zip' or mimeType='application/x-zip-compressed')", fields='nextPageToken,files(id,name,size,modifiedTime)', pageSize=100, pageToken=page, orderBy='modifiedTime desc').execute()
        results.extend(response.get('files', []))
        page = response.get('nextPageToken')
        if not page or len(results) >= 1000:
            return results


def restore_remote_backup(store, identity, parent):
    from googleapiclient.http import MediaIoBaseDownload
    from .backup import MAX_ARCHIVE, restore_backup
    from .quality import fingerprint
    from .storage import uid
    svc, mapping = configured_service(store)
    metadata = svc.files().get(fileId=identity, fields='id,size,mimeType,parents,trashed,appProperties').execute()
    if mapping['Backups'] not in metadata.get('parents', []) or metadata.get('trashed') or metadata.get('mimeType') not in {'application/zip', 'application/x-zip-compressed'} or not 0 < int(metadata.get('size', 0)) <= MAX_ARCHIVE:
        raise StudioError('Tệp không thuộc thư mục Backups hoặc vượt giới hạn 4 GB.')
    temporary = store.path(f'downloads/{uid()}.zip')
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open('wb') as handle:
            download = MediaIoBaseDownload(handle, svc.files().get_media(fileId=identity), chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = download.next_chunk(num_retries=0)
                if handle.tell() > MAX_ARCHIVE:
                    raise StudioError('Bản sao lưu tải về vượt giới hạn 4 GB.')
        digest = metadata.get('appProperties', {}).get('sha256')
        if temporary.stat().st_size != int(metadata['size']) or (digest and fingerprint(temporary) != digest):
            raise StudioError('Bản sao lưu tải về không khớp kích thước hoặc checksum.')
        return restore_backup(temporary, parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync(store):
    with store.maintenance():
        return _sync(store)


def _sync(store):
    svc, mapping = configured_service(store)
    count, failures = 0, 0
    for directory in ('jobs', 'backgrounds'):
        root = store.root / directory
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(store.root) or path.suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.mp4', '.json', '.txt'} or '.partial.' in path.name:
                continue
            category = 'Projects'
            if directory == 'backgrounds' or path.name == 'background.png':
                category = 'Backgrounds'
            elif path.name.startswith(('product', 'original')) and path.suffix != '.json':
                category = 'Products'
            elif path.name.startswith('reference'):
                category = 'References'
            elif path.name.startswith('final'):
                category = 'Final'
            elif path.suffix == '.mp4':
                category = 'Clips'
            try:
                upload_path(svc, mapping, store.relative(path), path, category)
                count += 1
            except Exception:
                failures += 1
    from .backup import export_backup
    path = export_backup(store, destination=store.path('exports/drive_backup.zip'), _already_locked=True)
    upload_path(svc, mapping, 'studio_backup.zip', path, 'Backups')
    return count, failures
