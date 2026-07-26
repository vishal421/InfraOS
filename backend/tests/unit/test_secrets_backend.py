from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.secrets_backend import (
    FernetSecretsBackend,
    SecretsBackendError,
    VaultSecretsBackend,
    get_secrets_backend,
    reset_secrets_backend_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_secrets_backend_cache()
    yield
    reset_secrets_backend_cache()


def test_fernet_backend_round_trip():
    backend = FernetSecretsBackend()
    ref = backend.store("device-1", "password", "super-secret-value")
    assert ref != "super-secret-value"  # actually encrypted, not passed through
    assert backend.retrieve(ref) == "super-secret-value"


def test_fernet_backend_delete_is_noop():
    backend = FernetSecretsBackend()
    ref = backend.store("device-1", "password", "value")
    backend.delete(ref)  # should not raise
    assert backend.retrieve(ref) == "value"  # nothing external was actually deleted


def test_vault_backend_store_and_retrieve_with_mocked_client():
    """
    hvac's real network behavior against a live Vault server is NOT exercised
    here — there was no Vault server available to test against. This
    confirms the backend calls the expected hvac KV v2 methods with the
    expected path shape and correctly unwraps the response structure, which
    is the part of this integration under InfraOS's control.
    """
    with patch("hvac.Client") as MockClient:
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance

        backend = VaultSecretsBackend(vault_addr="http://vault:2100", vault_token="test-token", mount_point="secret")
        ref = backend.store("device-1", "password", "super-secret-value")

        assert ref == "infraos/device-1/password"
        mock_instance.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="infraos/device-1/password", secret={"value": "super-secret-value"}, mount_point="secret"
        )

        mock_instance.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"value": "super-secret-value"}}
        }
        retrieved = backend.retrieve(ref)
        assert retrieved == "super-secret-value"


def test_vault_backend_wraps_errors():
    with patch("hvac.Client") as MockClient:
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.secrets.kv.v2.create_or_update_secret.side_effect = RuntimeError("connection refused")

        backend = VaultSecretsBackend(vault_addr="http://vault:2100", vault_token="test-token")
        with pytest.raises(SecretsBackendError):
            backend.store("device-1", "password", "value")


def test_factory_defaults_to_fernet(monkeypatch):
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    backend = get_secrets_backend()
    assert isinstance(backend, FernetSecretsBackend)
    get_settings.cache_clear()


def test_factory_requires_vault_addr_and_token(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("SECRETS_BACKEND", "vault")
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    get_settings.cache_clear()

    with pytest.raises(SecretsBackendError):
        get_secrets_backend()

    get_settings.cache_clear()
