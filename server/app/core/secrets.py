import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


_ENCRYPTED_PREFIX = "fernet:"


def _cipher() -> Fernet:
    encryption_key = settings.ODOO_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    encrypted = _cipher().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_ENCRYPTED_PREFIX}{encrypted}"


def decrypt_secret(value: str) -> str:
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value
    try:
        token = value[len(_ENCRYPTED_PREFIX):].encode("ascii")
        return _cipher().decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as error:
        raise ValueError("No se pudo descifrar una credencial guardada") from error
