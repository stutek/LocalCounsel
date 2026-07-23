"""Unit tests for the encrypted, per-user openEHR store — local files, no network.

Uses tiny scrypt parameters via monkeypatch so the memory-hard KDF doesn't slow
the suite; the security properties under test are independent of the cost factor.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from local_counsel.health_sync import generate_bia_series
from local_counsel.openehr import (
    EncryptedOpenEhrStore,
    InvalidPassphrase,
    bia_to_composition,
)
from local_counsel.openehr import crypto

GOOD_PASS = "correct-horse-battery-staple"
FIXED_END = datetime(2026, 7, 8, tzinfo=timezone.utc)
TEST_VENDOR = "test-bia-scale"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    monkeypatch.setattr(crypto, "SCRYPT_N", 2**8)


def _open(tmp_path, user="alice", passphrase=GOOD_PASS):
    return EncryptedOpenEhrStore.open(user, passphrase, base_dir=tmp_path)


def test_put_get_roundtrip(tmp_path):
    comp = bia_to_composition(generate_bia_series(1, end_date=FIXED_END)[0], vendor=TEST_VENDOR)
    with _open(tmp_path) as store:
        uid = store.put_composition(comp)
        assert store.get_composition(uid) == comp
        assert store.count() == 1


def test_put_is_idempotent_on_uid(tmp_path):
    m = generate_bia_series(1, end_date=FIXED_END)[0]
    comp = bia_to_composition(m, vendor=TEST_VENDOR)
    with _open(tmp_path) as store:
        store.put_composition(comp)
        store.put_composition(comp)  # same deterministic UID
        assert store.count() == 1


def test_persists_across_reopen_with_same_passphrase(tmp_path):
    comps = [bia_to_composition(m, vendor=TEST_VENDOR) for m in generate_bia_series(12, end_date=FIXED_END)]
    with _open(tmp_path) as store:
        for c in comps:
            store.put_composition(c)
    # Reopen: data survives, decrypts correctly.
    with _open(tmp_path) as store:
        assert store.count() == 12
        assert sorted(store.list_uids()) == sorted(c["uid"] for c in comps)


def test_wrong_passphrase_is_rejected_on_reopen(tmp_path):
    with _open(tmp_path) as store:
        store.put_composition(bia_to_composition(generate_bia_series(1)[0], vendor=TEST_VENDOR))
    with pytest.raises(InvalidPassphrase):
        _open(tmp_path, passphrase="not-the-passphrase-at-all")


def test_stolen_file_has_no_plaintext_medical_data(tmp_path):
    """The clinical values must not appear anywhere in the raw DB bytes."""
    m = generate_bia_series(1, end_date=FIXED_END)[0]
    with _open(tmp_path) as store:
        store.put_composition(bia_to_composition(m, vendor=TEST_VENDOR))
        db_file = store.path

    raw = db_file.read_bytes()
    # Distinctive clinical magnitudes and archetype names must be encrypted.
    assert str(m.basal_metabolic_rate_kcal).encode() not in raw
    assert b"body_weight" not in raw
    assert b"Skeletal muscle" not in raw
    assert b"magnitude" not in raw


def test_each_user_gets_a_separate_database_file(tmp_path):
    with _open(tmp_path, user="alice") as a, _open(tmp_path, user="bob") as b:
        assert a.path != b.path
        a.put_composition(bia_to_composition(generate_bia_series(1)[0], vendor=TEST_VENDOR))
        assert a.count() == 1
        assert b.count() == 0  # isolated


def test_short_passphrase_is_refused_on_create(tmp_path):
    with pytest.raises(ValueError):
        _open(tmp_path, passphrase="short")


def test_passphrase_rotation_keeps_data_and_changes_key(tmp_path):
    comp = bia_to_composition(generate_bia_series(1, end_date=FIXED_END)[0], vendor=TEST_VENDOR)
    with _open(tmp_path) as store:
        uid = store.put_composition(comp)
        store.rotate_passphrase(GOOD_PASS, "a-brand-new-strong-passphrase")

    # Old passphrase no longer works; new one does and data is intact.
    with pytest.raises(InvalidPassphrase):
        _open(tmp_path, passphrase=GOOD_PASS)
    with _open(tmp_path, passphrase="a-brand-new-strong-passphrase") as store:
        assert store.get_composition(uid) == comp


def test_rotation_requires_correct_old_passphrase(tmp_path):
    with _open(tmp_path) as store:
        with pytest.raises(InvalidPassphrase):
            store.rotate_passphrase("wrong-old-passphrase", "another-strong-one")
