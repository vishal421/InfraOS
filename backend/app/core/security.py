"""
Encrypts/decrypts device credentials at rest using a Fernet key from settings.

This is explicitly a stand-in, not the real thing: the architecture doc
(Security Architecture, Section 24) calls for a proper secrets backend
(Vault or equivalent) with credential references stored in the DB rather
than encrypted blobs. That's the right design for a real deployment holding
keys to every firewall in an org. This module exists so that THIS pass
doesn't store firewall passwords in plaintext while that real integration
is still pending — treat CREDENTIALS_ENCRYPTION_KEY as a placeholder to be
replaced, not a production secrets story.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CredentialCipher:
    def __init__(self, key: str | None = None):
        settings = get_settings()
        key = key or settings.credentials_encryption_key
        if not key:
            raise RuntimeError(
                "CREDENTIALS_ENCRYPTION_KEY is not set. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Could not decrypt stored credential — wrong key or corrupted data") from exc


_cipher: CredentialCipher | None = None


def get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        _cipher = CredentialCipher()
    return _cipher
