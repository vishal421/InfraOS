"""
Secrets backend abstraction for device credentials.

The architecture doc calls for a proper secrets backend (Vault or
equivalent) rather than encrypted blobs sitting directly in the app
database — this module is that abstraction. Two implementations:

  - FernetSecretsBackend: the original approach (Section 24's "stand-in").
    The device row's credential field IS the encrypted ciphertext.
  - VaultSecretsBackend: writes the plaintext secret to Vault's KV v2 engine
    and stores only a *reference* (the Vault path) in the device row. The
    plaintext never touches Postgres at all with this backend.

Both implement the same interface, so device_service.py doesn't need to
know or care which one is active — that's the point of the abstraction.
Selected via SECRETS_BACKEND=fernet|vault.

Testing note: this was verified against a mocked hvac client (no real Vault
server was available in the sandbox this was built in). The interface and
the Fernet backend are both exercised end-to-end against a real database;
the Vault backend's actual network behavior against a real Vault server has
NOT been verified and should be smoke-tested before relying on it in a real
deployment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.core.security import get_cipher


class SecretsBackendError(Exception):
    pass


class SecretsBackend(ABC):
    @abstractmethod
    def store(self, device_id: str, label: str, plaintext: str) -> str:
        """Stores a secret, returns an opaque reference to persist in the DB."""

    @abstractmethod
    def retrieve(self, reference: str) -> str:
        """Resolves a stored reference back to the plaintext secret."""

    @abstractmethod
    def delete(self, reference: str) -> None:
        """Best-effort cleanup when a device/credential is deleted."""


class FernetSecretsBackend(SecretsBackend):
    """The reference IS the ciphertext — no external store involved. This is
    the backend used unless SECRETS_BACKEND=vault is explicitly set."""

    def store(self, device_id: str, label: str, plaintext: str) -> str:
        return get_cipher().encrypt(plaintext)

    def retrieve(self, reference: str) -> str:
        return get_cipher().decrypt(reference)

    def delete(self, reference: str) -> None:
        return None  # nothing external to clean up


class VaultSecretsBackend(SecretsBackend):
    """
    Stores secrets under Vault's KV v2 engine at
    `<mount_point>/<path_prefix>/<device_id>/<label>`. The DB reference
    stored is that path string, not a Vault token or the secret itself.
    """

    def __init__(self, vault_addr: str, vault_token: str, mount_point: str = "secret", path_prefix: str = "infraos"):
        import hvac  # imported lazily so environments without hvac installed

        self._client = hvac.Client(url=vault_addr, token=vault_token)
        self._mount_point = mount_point
        self._path_prefix = path_prefix

    def _path_for(self, device_id: str, label: str) -> str:
        return f"{self._path_prefix}/{device_id}/{label}"

    def store(self, device_id: str, label: str, plaintext: str) -> str:
        path = self._path_for(device_id, label)
        try:
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path, secret={"value": plaintext}, mount_point=self._mount_point
            )
        except Exception as exc:  # hvac raises its own exception hierarchy
            raise SecretsBackendError(f"Failed to store secret at {path}: {exc}") from exc
        return path

    def retrieve(self, reference: str) -> str:
        try:
            result = self._client.secrets.kv.v2.read_secret_version(path=reference, mount_point=self._mount_point)
        except Exception as exc:
            raise SecretsBackendError(f"Failed to retrieve secret at {reference}: {exc}") from exc
        try:
            return result["data"]["data"]["value"]
        except (KeyError, TypeError) as exc:
            raise SecretsBackendError(f"Unexpected Vault response shape at {reference}") from exc

    def delete(self, reference: str) -> None:
        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(path=reference, mount_point=self._mount_point)
        except Exception:
            pass  # best-effort — don't fail a device deletion over Vault cleanup


_backend: SecretsBackend | None = None


def get_secrets_backend() -> SecretsBackend:
    global _backend
    if _backend is not None:
        return _backend

    settings = get_settings()
    if settings.secrets_backend == "vault":
        if not settings.vault_addr or not settings.vault_token:
            raise SecretsBackendError("SECRETS_BACKEND=vault requires VAULT_ADDR and VAULT_TOKEN to be set")
        _backend = VaultSecretsBackend(settings.vault_addr, settings.vault_token, settings.vault_mount_point)
    else:
        _backend = FernetSecretsBackend()
    return _backend


def reset_secrets_backend_cache() -> None:
    """Test-only hook to force re-reading settings between tests."""
    global _backend
    _backend = None
