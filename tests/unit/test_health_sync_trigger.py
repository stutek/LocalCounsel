"""Unit tests for the BIA retrieval trigger + encrypted credential storage.

Covers the two coupled requirements: the passphrase gateway sits at the retrieval
trigger, and the Google Health API key is encrypted under the same data key.
"""

from __future__ import annotations

import pytest

from local_counsel.health_sync import (
    GOOGLE_HEALTH_API_KEY,
    MissingCredentialError,
    trigger_bia_sync,
)
from local_counsel.openehr import EncryptedOpenEhrStore, InvalidPassphrase, crypto

GOOD_PASS = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    monkeypatch.setattr(crypto, "SCRYPT_N", 2**8)


def _provision(tmp_path, api_key="secret-google-token"):
    with EncryptedOpenEhrStore.open("alice", GOOD_PASS, base_dir=tmp_path) as store:
        store.put_secret(GOOGLE_HEALTH_API_KEY, api_key)


def test_secret_roundtrips_under_same_key(tmp_path):
    _provision(tmp_path, api_key="token-123")
    with EncryptedOpenEhrStore.open("alice", GOOD_PASS, base_dir=tmp_path) as store:
        assert store.get_secret(GOOGLE_HEALTH_API_KEY) == "token-123"
        assert store.get_secret("nonexistent") is None


def test_stored_api_key_is_encrypted_on_disk(tmp_path):
    _provision(tmp_path, api_key="super-secret-token-9000")
    with EncryptedOpenEhrStore.open("alice", GOOD_PASS, base_dir=tmp_path) as store:
        db_path = store.path
    assert b"super-secret-token-9000" not in db_path.read_bytes()


def test_wrong_passphrase_cannot_read_secret(tmp_path):
    _provision(tmp_path)
    with pytest.raises(InvalidPassphrase):
        EncryptedOpenEhrStore.open("alice", "totally-wrong-passphrase", base_dir=tmp_path)


def test_trigger_gateway_rejects_wrong_passphrase_before_retrieval(tmp_path):
    _provision(tmp_path)
    with pytest.raises(InvalidPassphrase):
        trigger_bia_sync("alice", "wrong-passphrase-value", base_dir=str(tmp_path))


def test_trigger_requires_stored_credential(tmp_path):
    # Create the store but do NOT provision an API key.
    with EncryptedOpenEhrStore.open("alice", GOOD_PASS, base_dir=tmp_path):
        pass
    with pytest.raises(MissingCredentialError):
        trigger_bia_sync("alice", GOOD_PASS, base_dir=str(tmp_path))


def test_trigger_syncs_and_persists_when_unlocked(tmp_path):
    _provision(tmp_path)
    with trigger_bia_sync("alice", GOOD_PASS, base_dir=str(tmp_path), months=12) as store:
        assert store.count() == 12


def test_trigger_passes_decrypted_key_to_connector(tmp_path):
    _provision(tmp_path, api_key="the-real-key")
    seen = {}

    def factory(api_key):
        seen["api_key"] = api_key
        from local_counsel.health_sync import MockGoogleHealthConnector

        return MockGoogleHealthConnector(months=3, api_key=api_key)

    with trigger_bia_sync(
        "alice", GOOD_PASS, base_dir=str(tmp_path), connector_factory=factory
    ) as store:
        assert store.count() == 3
    assert seen["api_key"] == "the-real-key"
