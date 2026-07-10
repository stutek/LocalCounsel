"""Local, encrypted openEHR medical repository.

The storage half of the health sync engine (``docs/longevity-coach/health-integration-architecture.md``
§5): a per-user, passphrase-encrypted SQLite database of openEHR compositions.

* :mod:`.crypto` — envelope encryption (scrypt KEK wrapping an AES-256-GCM DEK).
* :mod:`.store` — :class:`EncryptedOpenEhrStore`, the per-user repository.
* :mod:`.mapper` — BIA measurements → openEHR compositions.
"""

from __future__ import annotations

from .crypto import CryptoError, DecryptionError, InvalidPassphrase
from .mapper import bia_to_composition, composition_to_measurement, composition_uid
from .store import EncryptedOpenEhrStore, default_base_dir

__all__ = [
    "EncryptedOpenEhrStore",
    "default_base_dir",
    "bia_to_composition",
    "composition_to_measurement",
    "composition_uid",
    "CryptoError",
    "InvalidPassphrase",
    "DecryptionError",
]
