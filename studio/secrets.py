import os

SERVICE = 'fashion-ai-studio'
ALLOWED = {'openai', 'google', 'drive_token', 'drive_client'}


def vault():
    import keyring
    backend = keyring.get_keyring()
    module = type(backend).__module__
    if not module.startswith(('keyring.backends.Windows', 'keyring.backends.macOS', 'keyring.backends.SecretService')):
        raise RuntimeError('Không có kho bí mật hệ điều hành an toàn. Dùng biến môi trường hoặc khóa trong phiên.')
    return keyring


def save(name, value):
    if name not in ALLOWED:
        raise ValueError('Tên bí mật không hợp lệ.')
    vault().set_password(SERVICE, name, value)


def read(name):
    if name not in ALLOWED:
        raise ValueError('Tên bí mật không hợp lệ.')
    env = {'openai': 'OPENAI_API_KEY', 'google': 'GOOGLE_API_KEY'}.get(name)
    if env and os.getenv(env):
        return os.environ[env]
    try:
        return vault().get_password(SERVICE, name) or ''
    except Exception:
        return ''


def delete(name):
    backend = vault()
    if backend.get_password(SERVICE, name):
        backend.delete_password(SERVICE, name)
