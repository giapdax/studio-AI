"""Credential-free portable archives. Restore to a NEW directory only."""
from .errors import StudioError
import io
from contextlib import closing
import json
import sqlite3
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .storage import uid

ALLOWED = {'backgrounds', 'jobs'}
MAX_ARCHIVE = 4 * 1024 ** 3


def export_backup(store, backgrounds_only=False, destination=None, _already_locked=False):
    from contextlib import nullcontext
    with (nullcontext() if _already_locked else store.maintenance()):
        return _export_backup(store, backgrounds_only, destination)


def _export_backup(store, backgrounds_only, destination):
    target = Path(destination).resolve() if destination is not None else None
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + '.partial.zip') if target else None
    buffer = temporary if target else io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('backup.json', json.dumps({'schema': 2, 'kind': 'backgrounds' if backgrounds_only else 'full'}))
        if backgrounds_only:
            archive.writestr('backgrounds.json', json.dumps(store.rows('SELECT * FROM backgrounds'), ensure_ascii=False))
        else:
            # SQLite backup API includes committed WAL transactions consistently.
            temp = store.root / f'backup_{uid()}.sqlite3'
            try:
                with store.connect() as source, closing(sqlite3.connect(temp)) as destination:
                    source.backup(destination)
                    destination.execute('DELETE FROM leases')
                    destination.commit()
                archive.write(temp, 'studio.sqlite3')
            finally:
                temp.unlink(missing_ok=True)
        for directory in ({'backgrounds'} if backgrounds_only else ALLOWED):
            root = store.root / directory
            if root.exists():
                for path in root.rglob('*'):
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(store.root) and '.partial.' not in path.name:
                        archive.write(path, path.relative_to(store.root).as_posix())
    if target:
        temporary.replace(target)
        return target
    return buffer.getvalue()


def validated_archive(content):
    is_file = isinstance(content, (str, Path))
    if (Path(content).stat().st_size if is_file else len(content)) > MAX_ARCHIVE:
        raise StudioError('Tệp sao lưu vượt 4 GB.')
    archive = zipfile.ZipFile(content if is_file else io.BytesIO(content))
    if sum(x.file_size for x in archive.infolist()) > MAX_ARCHIVE or len(archive.infolist()) > 50000:
        archive.close()
        raise StudioError('Sao lưu giải nén vượt giới hạn.')
    seen = set()
    for member in archive.infolist():
        name = member.orig_filename
        path = PurePosixPath(name)
        reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10)}
        bad_component = any(part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved for part in path.parts)
        normalized = path.as_posix().casefold()
        bad_character = any(ord(char) < 32 or char in '<>"|?*' for char in name)
        if normalized in seen or chr(92) in name or ':' in name or path.is_absolute() or '..' in path.parts or not path.parts or bad_component or bad_character or ((member.external_attr >> 16) & 0o170000) == 0o120000:
            archive.close()
            raise StudioError('Tệp ZIP có đường dẫn không an toàn.')
        seen.add(normalized)
        if path.parts[0] not in ALLOWED and name not in {'backup.json', 'backgrounds.json', 'studio.sqlite3'}:
            archive.close()
            raise StudioError('Sao lưu chứa loại tệp không được phép.')
        if name in {'backup.json', 'backgrounds.json'} and member.file_size > 4 * 1024 * 1024:
            archive.close()
            raise StudioError('Danh mục JSON sao lưu vượt 4 MB.')
    header = json.loads(archive.read('backup.json'))
    if header.get('schema') != 2:
        archive.close()
        raise StudioError('Phiên bản sao lưu không được hỗ trợ.')
    required = {'full': 'studio.sqlite3', 'backgrounds': 'backgrounds.json'}.get(header.get('kind'))
    if not required or required not in archive.namelist():
        archive.close()
        raise StudioError('Bản sao lưu thiếu cơ sở dữ liệu hoặc danh mục thư viện.')
    return archive, header


def restore_backup(content, parent):
    archive, header = validated_archive(content)
    if header['kind'] != 'full':
        archive.close()
        raise StudioError('Cần bản sao lưu đầy đủ.')
    destination = Path(parent) / f'restored_{uid()}'
    destination.mkdir(parents=True)
    with archive:
        for member in archive.infolist():
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    # Imported real jobs always require explicit resume on the new computer.
    from .storage import Store
    restored = Store(destination)
    restored.execute('DELETE FROM leases')
    restored.execute("UPDATE jobs SET status='interrupted',owner=NULL,heartbeat=0 WHERE status IN ('running','queued','editing')")
    return destination


def import_backgrounds(store, content):
    archive, header = validated_archive(content)
    if header['kind'] != 'backgrounds':
        archive.close()
        raise StudioError('Cần bản xuất thư viện phông nền.')
    with archive:
        rows = json.loads(archive.read('backgrounds.json'))
        if not isinstance(rows, list) or len(rows) > 10000:
            raise StudioError('Danh mục phông nền không hợp lệ hoặc quá lớn.')
        pending = []
        from .storage import save_image
        # Check every image before touching the library; preserve original bytes and families.
        with tempfile.TemporaryDirectory(prefix='studio-background-import-') as staging:
            for index, row in enumerate(sorted(rows, key=lambda r: (r.get('family') or r['id'], r.get('version', 1)))):
                manifest = json.loads(row['manifest'])
                if not isinstance(row.get('name'), str) or not row['name'].strip() or len(row['name']) > 120:
                    raise StudioError('Tên phông nền nhập không hợp lệ.')
                source = manifest.get('original_file', row['file'])
                if PurePosixPath(source).parts[0] != 'backgrounds':
                    raise StudioError('Ảnh thư viện phải nằm trong thư mục backgrounds.')
                if archive.getinfo(source).file_size > 20 * 1024 * 1024:
                    raise StudioError('Ảnh thư viện nhập vượt 20 MB.')
                image = archive.read(source)
                save_image(image, Path(staging) / f'{index}.png')
                pending.append((row, image, manifest))
        families = {}
        for row, image, manifest in pending:
            family = row.get('family') or row['id']
            identity = store.add_background(row['name'], image, manifest.get('environment', ''), families.get(family))
            families.setdefault(family, identity)
            if row.get('deleted'):
                store.execute('UPDATE backgrounds SET deleted=1 WHERE id=?', (identity,))
    return len(pending)


def videos_zip(store):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        for job in store.rows("SELECT id,mode FROM jobs WHERE status='complete'"):
            path = store.path(f"jobs/{job['id']}/final_{job['id']}.mp4")
            if path.exists():
                archive.write(path, f"{job['mode']}_{path.name}")
    return buffer.getvalue()
