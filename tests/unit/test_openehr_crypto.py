"""Unit tests for the envelope-encryption primitives — no DB, no network."""

from __future__ import annotations

import pytest

from local_counsel.openehr import crypto
from local_counsel.openehr.crypto import (
    DecryptionError,
    InvalidPassphrase,
    KdfParams,
)

# Fast KDF params for tests — the production defaults are memory-hard and slow.
FAST = KdfParams(salt=b"0123456789abcdef", n=2**8, r=8, p=1)


def test_kek_is_deterministic_for_same_passphrase_and_salt():
    a = crypto.derive_kek("correct horse battery", FAST)
    b = crypto.derive_kek("correct horse battery", FAST)
    assert a == b and len(a) == crypto.KEY_BYTES


def test_kek_differs_by_passphrase_and_by_salt():
    base = crypto.derive_kek("passphrase-one", FAST)
    assert crypto.derive_kek("passphrase-two", FAST) != base
    other_salt = KdfParams(salt=b"fedcba9876543210", n=2**8, r=8, p=1)
    assert crypto.derive_kek("passphrase-one", other_salt) != base


def test_dek_wrap_unwrap_roundtrip():
    kek = crypto.derive_kek("unlock me please", FAST)
    dek = crypto.new_dek()
    assert crypto.unwrap_dek(kek, crypto.wrap_dek(kek, dek)) == dek


def test_wrong_passphrase_cannot_unwrap_dek():
    dek = crypto.new_dek()
    good = crypto.derive_kek("the-right-one", FAST)
    bad = crypto.derive_kek("the-wrong-one", FAST)
    wrapped = crypto.wrap_dek(good, dek)
    with pytest.raises(InvalidPassphrase):
        crypto.unwrap_dek(bad, wrapped)


def test_record_encrypt_decrypt_roundtrip_with_aad():
    dek = crypto.new_dek()
    blob = crypto.encrypt_record(dek, b"systolic 118", aad=b"uid-1")
    assert blob != b"systolic 118"
    assert crypto.decrypt_record(dek, blob, aad=b"uid-1") == b"systolic 118"


def test_record_bound_to_aad_cannot_be_replayed_under_other_uid():
    dek = crypto.new_dek()
    blob = crypto.encrypt_record(dek, b"secret", aad=b"uid-1")
    with pytest.raises(DecryptionError):
        crypto.decrypt_record(dek, blob, aad=b"uid-2")


def test_tampered_ciphertext_is_rejected():
    dek = crypto.new_dek()
    blob = bytearray(crypto.encrypt_record(dek, b"secret", aad=b"uid-1"))
    blob[-1] ^= 0x01  # flip a bit in the tag
    with pytest.raises(DecryptionError):
        crypto.decrypt_record(dek, bytes(blob), aad=b"uid-1")


def test_nonce_makes_ciphertexts_unique_per_encryption():
    dek = crypto.new_dek()
    a = crypto.encrypt_record(dek, b"same", aad=b"uid")
    b = crypto.encrypt_record(dek, b"same", aad=b"uid")
    assert a != b  # random nonce => distinct ciphertexts
