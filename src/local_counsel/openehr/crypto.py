"""Encryption primitives for the local medical repository.

Medical data at rest is protected with **envelope encryption**:

* A **Key-Encryption Key (KEK)** is derived from the user's passphrase with
  ``scrypt`` (memory-hard KDF) and a per-database random salt. The passphrase and
  the KEK are *never* written to disk.
* A random 256-bit **Data-Encryption Key (DEK)** is generated once per database
  and encrypts every record with **AES-256-GCM** (authenticated). Only the DEK
  *wrapped by the KEK* is stored, alongside the salt and KDF parameters.

Consequences:

* Steal the database file without the passphrase → only ciphertext + a wrapped
  DEK that cannot be unwrapped. Nothing is recoverable.
* Wrong passphrase / different user → KEK is wrong → the GCM authentication tag
  fails and :class:`InvalidPassphrase` is raised before any data is touched.
* Passphrase rotation only re-wraps the DEK — records are never re-encrypted.

We deliberately reuse vetted primitives (stdlib ``hashlib.scrypt`` for the KDF,
``cryptography``'s ``AESGCM`` for AEAD) and ``secrets`` for all randomness — no
home-grown crypto.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --- Sizing -----------------------------------------------------------------
KEY_BYTES = 32          # 256-bit keys (KEK and DEK)
SALT_BYTES = 16         # 128-bit KDF salt
NONCE_BYTES = 12        # 96-bit GCM nonce (the AES-GCM standard)

# --- scrypt cost parameters (medical-grade, tunable, stored per DB) ---------
# 128 * N * r bytes of memory: 2**16 * 8 * 128 = 64 MiB, cost paid once per open.
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1

# Minimum passphrase length we will accept when creating a database. A strong
# passphrase is the root of the whole scheme; short ones are brute-forceable
# regardless of the KDF.
MIN_PASSPHRASE_LEN = 12


class CryptoError(Exception):
    """Base class for encryption/decryption failures."""


class InvalidPassphrase(CryptoError):
    """Raised when the passphrase cannot unwrap the DEK (wrong user/passphrase)."""


class DecryptionError(CryptoError):
    """Raised when a record fails authenticated decryption (tampering/corruption)."""


@dataclass(frozen=True)
class KdfParams:
    """scrypt parameters + salt, persisted so the KEK can be re-derived."""

    salt: bytes
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P

    @staticmethod
    def new() -> "KdfParams":
        # Read the module cost constants at call time so deployments (and tests)
        # can tune them; the chosen params are persisted alongside each database.
        return KdfParams(salt=secrets.token_bytes(SALT_BYTES), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)

    def _maxmem(self) -> int:
        # scrypt needs 128 * N * r bytes; give headroom so it never trips the limit.
        return 128 * self.n * self.r * 2


def derive_kek(passphrase: str, params: KdfParams) -> bytes:
    """Derive the 256-bit key-encryption key from the passphrase (memory-hard)."""
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=params.salt,
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=KEY_BYTES,
        maxmem=params._maxmem(),
    )


def new_dek() -> bytes:
    """Generate a fresh random 256-bit data-encryption key."""
    return secrets.token_bytes(KEY_BYTES)


def _seal(key: bytes, plaintext: bytes, aad: bytes | None) -> bytes:
    """AES-256-GCM encrypt, returning ``nonce || ciphertext(+tag)``."""
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def _open(key: bytes, blob: bytes, aad: bytes | None) -> bytes:
    nonce, ciphertext = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def wrap_dek(kek: bytes, dek: bytes) -> bytes:
    """Encrypt (wrap) the DEK under the KEK for storage."""
    return _seal(kek, dek, aad=b"local-counsel/dek-v1")


def unwrap_dek(kek: bytes, wrapped: bytes) -> bytes:
    """Decrypt the DEK; raises :class:`InvalidPassphrase` on the wrong KEK."""
    try:
        return _open(kek, wrapped, aad=b"local-counsel/dek-v1")
    except InvalidTag as exc:
        raise InvalidPassphrase("passphrase does not match this database") from exc


def encrypt_record(dek: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt one record. ``aad`` binds the ciphertext to its row (e.g. the UID)."""
    return _seal(dek, plaintext, aad)


def decrypt_record(dek: bytes, blob: bytes, aad: bytes) -> bytes:
    """Decrypt one record; raises :class:`DecryptionError` on tamper/corruption."""
    try:
        return _open(dek, blob, aad)
    except InvalidTag as exc:
        raise DecryptionError("record failed authentication (tampered or corrupt)") from exc
