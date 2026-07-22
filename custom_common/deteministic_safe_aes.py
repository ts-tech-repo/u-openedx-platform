import base64
import hashlib

from django.conf import settings
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


DEFAULT_AES_KEY = "234a8193fae8d79f1ae03c2586f929b66c034a0f3428d95201105922fadb1568"

AES_SECRET_KEY = getattr(
    settings,
    "AES_SECRET_KEY",
    DEFAULT_AES_KEY,
)

if not AES_SECRET_KEY:
    raise ValueError("AES_SECRET_KEY is not configured")


def _get_secret_key(secret_key=None):
    """
    Return AES key bytes.
    """
    key = secret_key or AES_SECRET_KEY

    return bytes.fromhex(key)


def _deterministic_nonce(message: str) -> bytes:
    """
    Generate deterministic nonce from message
    """
    return hashlib.sha256(message.encode()).digest()[:16]


def encrypt(message: str, secret_key: str = None) -> str:
    nonce = _deterministic_nonce(message)

    key = _get_secret_key(secret_key)

    cipher = AES.new(key, AES.MODE_CBC, iv=nonce)

    ciphertext = cipher.encrypt(pad(message.encode(), AES.block_size))

    encrypted = nonce + ciphertext

    # URL-safe base64 (filename safe)
    return base64.urlsafe_b64encode(encrypted).decode().rstrip("=")


def decrypt(encrypted_message: str, secret_key: str = None) -> str:
    padding = "=" * (-len(encrypted_message) % 4)
    data = base64.urlsafe_b64decode(encrypted_message + padding)

    nonce = data[:16]
    ciphertext = data[16:]

    key = _get_secret_key(secret_key)

    cipher = AES.new(key, AES.MODE_CBC, iv=nonce)

    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)

    return plaintext.decode()