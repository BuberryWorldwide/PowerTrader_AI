"""
PowerTrader AI — Credential encryption at rest.

Uses Fernet + PBKDF2 (480k iterations, SHA256) to encrypt/decrypt
the Coinbase API key and secret.

Encrypted files:
  cb_credentials.enc  — Fernet-encrypted JSON payload
  cb_credentials.salt — 16-byte PBKDF2 salt (hex-encoded)

Plaintext fallback:
  cb_key.txt / cb_secret.txt — read if .enc is absent
"""

import os
import json
import getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64


_SALT_FILE = "cb_credentials.salt"
_ENC_FILE = "cb_credentials.enc"
_KEY_FILE = "cb_key.txt"
_SECRET_FILE = "cb_secret.txt"

_PBKDF2_ITERATIONS = 480_000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_credentials(base_dir: str, passphrase: str, key: str, secret: str) -> None:
    """Encrypt key+secret and write .enc + .salt files."""
    salt = os.urandom(16)
    fernet_key = _derive_key(passphrase, salt)
    f = Fernet(fernet_key)

    payload = json.dumps({"key": key, "secret": secret}).encode("utf-8")
    token = f.encrypt(payload)

    salt_path = os.path.join(base_dir, _SALT_FILE)
    enc_path = os.path.join(base_dir, _ENC_FILE)

    with open(salt_path, "w", encoding="utf-8") as fh:
        fh.write(salt.hex())

    with open(enc_path, "wb") as fh:
        fh.write(token)


def decrypt_credentials(base_dir: str, passphrase: str) -> tuple:
    """Decrypt .enc file and return (key, secret)."""
    salt_path = os.path.join(base_dir, _SALT_FILE)
    enc_path = os.path.join(base_dir, _ENC_FILE)

    with open(salt_path, "r", encoding="utf-8") as fh:
        salt = bytes.fromhex(fh.read().strip())

    with open(enc_path, "rb") as fh:
        token = fh.read()

    fernet_key = _derive_key(passphrase, salt)
    f = Fernet(fernet_key)
    payload = f.decrypt(token)
    data = json.loads(payload.decode("utf-8"))
    return data["key"], data["secret"]


def has_encrypted_credentials(base_dir: str) -> bool:
    """Check if encrypted credential files exist."""
    return (
        os.path.isfile(os.path.join(base_dir, _ENC_FILE))
        and os.path.isfile(os.path.join(base_dir, _SALT_FILE))
    )


def has_plaintext_credentials(base_dir: str) -> bool:
    """Check if plaintext credential files exist."""
    return (
        os.path.isfile(os.path.join(base_dir, _KEY_FILE))
        and os.path.isfile(os.path.join(base_dir, _SECRET_FILE))
    )


def load_credentials(base_dir: str) -> tuple:
    """
    Load credentials, trying encrypted first then plaintext fallback.

    For encrypted creds, checks POWERTRADER_PASSPHRASE env var first,
    then prompts via getpass if running in a terminal.

    Returns (key, secret).
    Raises RuntimeError if no credentials found or decryption fails.
    """
    # Try encrypted first
    if has_encrypted_credentials(base_dir):
        passphrase = os.environ.get("POWERTRADER_PASSPHRASE", "").strip()
        if not passphrase:
            try:
                passphrase = getpass.getpass("Enter PowerTrader passphrase: ")
            except (EOFError, OSError):
                raise RuntimeError(
                    "Encrypted credentials found but no passphrase available. "
                    "Set POWERTRADER_PASSPHRASE env var or run in a terminal."
                )
        return decrypt_credentials(base_dir, passphrase)

    # Fallback to plaintext
    if has_plaintext_credentials(base_dir):
        key_path = os.path.join(base_dir, _KEY_FILE)
        secret_path = os.path.join(base_dir, _SECRET_FILE)

        with open(key_path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
        with open(secret_path, "r", encoding="utf-8") as fh:
            secret = fh.read().strip()

        return key, secret

    raise RuntimeError(
        "No Coinbase API credentials found. "
        "Open the GUI and go to Settings -> Coinbase API -> Setup."
    )


def delete_plaintext_credentials(base_dir: str) -> None:
    """Remove plaintext credential files after encryption."""
    for name in (_KEY_FILE, _SECRET_FILE):
        path = os.path.join(base_dir, name)
        if os.path.isfile(path):
            os.remove(path)
