"""Encrypted, per-user openEHR persistence on local SQLite.

Each user gets their **own** database file (no multi-tenant tables) at
``<base_dir>/<user_id>/openehr.db``, created ``0700``/``0600``. Compositions are
stored as **AES-256-GCM ciphertext** under a passphrase-derived envelope key (see
:mod:`.crypto`); the plaintext, the passphrase, and the data key never touch disk.

Only the composition **UID** (an opaque UUIDv5) and a row-insert timestamp are
stored in clear — everything clinical is inside the encrypted blob, with the UID
bound in as GCM associated data so rows cannot be swapped between records or
databases.

Idempotency: writing a composition is a ``PUT`` keyed by its deterministic UID
(``INSERT OR REPLACE``), so repeated syncs of the same reading are safe.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import crypto
from .crypto import InvalidPassphrase, KdfParams

SCHEMA_VERSION = 1


def default_base_dir() -> Path:
    """Root for per-user medical databases (env-overridable, git-ignored)."""
    return Path(os.getenv("LC_HEALTH_DATA_DIR", "local_cache/health"))


def _db_path(user_id: str, base_dir: Path) -> Path:
    if not user_id or "/" in user_id or "\\" in user_id or user_id in (".", ".."):
        raise ValueError(f"invalid user_id: {user_id!r}")
    return base_dir / user_id / "openehr.db"


class EncryptedOpenEhrStore:
    """A per-user, passphrase-encrypted openEHR composition repository."""

    def __init__(self, conn: sqlite3.Connection, dek: bytes, user_id: str, path: Path):
        self._conn = conn
        self._dek = dek
        self.user_id = user_id
        self.path = path

    # -- lifecycle ----------------------------------------------------------
    @classmethod
    def open(
        cls,
        user_id: str,
        passphrase: str,
        *,
        base_dir: Path | str | None = None,
    ) -> "EncryptedOpenEhrStore":
        """Open the user's database, creating + initializing it if absent.

        On an existing database the passphrase is verified by unwrapping the DEK;
        a wrong passphrase raises :class:`InvalidPassphrase` before any data
        access. On a new database the passphrase must be at least
        :data:`.crypto.MIN_PASSPHRASE_LEN` characters.
        """
        base = Path(base_dir) if base_dir is not None else default_base_dir()
        path = _db_path(user_id, base)
        existed = path.exists()

        if not existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            _chmod(path.parent, 0o700)

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            if existed:
                dek = cls._load_and_unlock(conn, passphrase)
            else:
                _chmod(path, 0o600)
                dek = cls._initialize(conn, user_id, passphrase)
            _ensure_schema(conn)
        except Exception:
            conn.close()
            raise

        return cls(conn, dek, user_id, path)

    @staticmethod
    def _initialize(conn: sqlite3.Connection, user_id: str, passphrase: str) -> bytes:
        if len(passphrase) < crypto.MIN_PASSPHRASE_LEN:
            raise ValueError(
                f"passphrase must be at least {crypto.MIN_PASSPHRASE_LEN} characters "
                "to protect medical data"
            )
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE composition (
                uid        TEXT PRIMARY KEY,
                ciphertext BLOB NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        params = KdfParams.new()
        kek = crypto.derive_kek(passphrase, params)
        dek = crypto.new_dek()
        wrapped = crypto.wrap_dek(kek, dek)

        meta = {
            "schema_version": str(SCHEMA_VERSION).encode(),
            "user_id": user_id.encode("utf-8"),
            "kdf_salt": params.salt,
            "kdf_n": str(params.n).encode(),
            "kdf_r": str(params.r).encode(),
            "kdf_p": str(params.p).encode(),
            "wrapped_dek": wrapped,
            "created_at": _now().encode(),
        }
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)", list(meta.items())
        )
        conn.commit()
        return dek

    @staticmethod
    def _read_meta(conn: sqlite3.Connection) -> dict[str, bytes]:
        return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}

    @classmethod
    def _load_and_unlock(cls, conn: sqlite3.Connection, passphrase: str) -> bytes:
        meta = cls._read_meta(conn)
        try:
            params = KdfParams(
                salt=meta["kdf_salt"],
                n=int(meta["kdf_n"]),
                r=int(meta["kdf_r"]),
                p=int(meta["kdf_p"]),
            )
            wrapped = meta["wrapped_dek"]
        except KeyError as exc:
            raise ValueError("database is missing encryption metadata") from exc

        kek = crypto.derive_kek(passphrase, params)
        return crypto.unwrap_dek(kek, wrapped)  # raises InvalidPassphrase on mismatch

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EncryptedOpenEhrStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- composition CRUD ---------------------------------------------------
    def put_composition(self, composition: dict[str, Any]) -> str:
        """Encrypt and store a composition (idempotent PUT keyed by its UID)."""
        uid = composition.get("uid")
        if not uid:
            raise ValueError("composition must carry a 'uid'")

        plaintext = json.dumps(composition, sort_keys=True, separators=(",", ":")).encode("utf-8")
        blob = crypto.encrypt_record(self._dek, plaintext, aad=uid.encode("utf-8"))
        self._conn.execute(
            "INSERT OR REPLACE INTO composition (uid, ciphertext, created_at) VALUES (?, ?, ?)",
            (uid, blob, _now()),
        )
        self._conn.commit()
        return uid

    def get_composition(self, uid: str) -> dict[str, Any] | None:
        """Fetch and decrypt one composition, or ``None`` if absent."""
        row = self._conn.execute(
            "SELECT ciphertext FROM composition WHERE uid = ?", (uid,)
        ).fetchone()
        if row is None:
            return None
        plaintext = crypto.decrypt_record(self._dek, row["ciphertext"], aad=uid.encode("utf-8"))
        return json.loads(plaintext)

    def list_uids(self) -> list[str]:
        return [r["uid"] for r in self._conn.execute("SELECT uid FROM composition ORDER BY uid")]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM composition").fetchone()["n"]

    def all_compositions(self) -> Iterator[dict[str, Any]]:
        """Decrypt and yield every composition (personal-scale, in-memory filter)."""
        for uid in self.list_uids():
            comp = self.get_composition(uid)
            if comp is not None:
                yield comp

    # -- encrypted secrets (API keys / OAuth tokens, same DEK) --------------
    def put_secret(self, name: str, value: str) -> None:
        """Store a credential (e.g. the Google Health API key) encrypted at rest.

        Uses the same AES-256-GCM data key as clinical records; the secret name is
        bound in as associated data. Unlocking the database (the passphrase) is
        therefore required to read any credential back.
        """
        blob = crypto.encrypt_record(self._dek, value.encode("utf-8"), aad=_secret_aad(name))
        self._conn.execute(
            "INSERT OR REPLACE INTO secret (name, ciphertext) VALUES (?, ?)", (name, blob)
        )
        self._conn.commit()

    def get_secret(self, name: str) -> str | None:
        """Decrypt and return a stored credential, or ``None`` if absent."""
        row = self._conn.execute(
            "SELECT ciphertext FROM secret WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return crypto.decrypt_record(self._dek, row["ciphertext"], aad=_secret_aad(name)).decode("utf-8")

    def list_secret_names(self) -> list[str]:
        return [r["name"] for r in self._conn.execute("SELECT name FROM secret ORDER BY name")]

    # -- key management -----------------------------------------------------
    def rotate_passphrase(self, old_passphrase: str, new_passphrase: str) -> None:
        """Re-wrap the DEK under a new passphrase; records are never re-encrypted.

        Verifies ``old_passphrase`` first, then generates a fresh salt and stores
        the DEK wrapped under the new key.
        """
        # Re-verify the old passphrase against the stored wrapping.
        self._load_and_unlock(self._conn, old_passphrase)

        if len(new_passphrase) < crypto.MIN_PASSPHRASE_LEN:
            raise ValueError(
                f"passphrase must be at least {crypto.MIN_PASSPHRASE_LEN} characters"
            )

        params = KdfParams.new()
        kek = crypto.derive_kek(new_passphrase, params)
        wrapped = crypto.wrap_dek(kek, self._dek)
        updates = {
            "kdf_salt": params.salt,
            "kdf_n": str(params.n).encode(),
            "kdf_r": str(params.r).encode(),
            "kdf_p": str(params.p).encode(),
            "wrapped_dek": wrapped,
        }
        self._conn.executemany(
            "UPDATE meta SET value = ? WHERE key = ?",
            [(v, k) for k, v in updates.items()],
        )
        self._conn.commit()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables that may post-date a database's creation (idempotent)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS secret (name TEXT PRIMARY KEY, ciphertext BLOB NOT NULL)"
    )
    conn.commit()


def _secret_aad(name: str) -> bytes:
    return b"secret:" + name.encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chmod(path: Path, mode: int) -> None:
    # Best-effort: POSIX honors this; on platforms without chmod semantics it's a no-op.
    try:
        path.chmod(mode)
    except (OSError, NotImplementedError):
        pass
