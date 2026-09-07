import base64
import hashlib
import logging

from django.conf import settings
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)

DEFAULT_AES_KEY = None

def _get_secret_key(secret_key=None):
    """
    Return AES key bytes.
    """
    
    site_org = configuration_helpers.get_value("course_org_filter", settings.LMS_BASE)
    AES_SECRET_KEY = hashlib.sha256(site_org.encode()).hexdigest()
    logging.info("AES_SECRET_KEY: %s", AES_SECRET_KEY)

    if not AES_SECRET_KEY:
        raise ValueError("AES_SECRET_KEY is not configured in settings")
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