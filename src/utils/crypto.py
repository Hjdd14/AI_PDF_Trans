"""Machine-bound symmetric encryption for sensitive config values."""

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _get_machine_key() -> bytes:
    raw = (os.environ.get("COMPUTERNAME", "") + os.environ.get("USERNAME", "")).encode()
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()[:32])


def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    f = Fernet(_get_machine_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    f = Fernet(_get_machine_key())
    return f.decrypt(ciphertext.encode()).decode()
