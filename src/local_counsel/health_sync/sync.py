"""The BIA retrieval trigger — the entry point for a Google Health sync run.

This is where the **passphrase gateway** lives. Retrieval cannot start until the
per-user encrypted repository is unlocked, because the Google Health API key is
itself stored encrypted under the same key (see ``openehr.store.put_secret``):

    unlock (passphrase)  ->  decrypt API key  ->  fetch BIA  ->  map  ->  store

A wrong passphrase fails to unlock the store and the run aborts before any
network/credential access. A missing credential aborts with
:class:`MissingCredentialError`.
"""

from __future__ import annotations

from typing import Callable

from ..openehr import EncryptedOpenEhrStore, bia_to_composition
from .mock_google import MockGoogleHealthConnector

# Name under which the Google Health / Fit credential is stored in the encrypted
# repository. Provision it once via ``store.put_secret(GOOGLE_HEALTH_API_KEY, ...)``.
GOOGLE_HEALTH_API_KEY = "google_health_api_key"


class MissingCredentialError(RuntimeError):
    """Raised when no Google Health credential is present in the unlocked store."""


def trigger_bia_sync(
    user_id: str,
    passphrase: str,
    *,
    base_dir: str | None = None,
    months: int = 12,
    connector_factory: Callable[[str], MockGoogleHealthConnector] | None = None,
) -> EncryptedOpenEhrStore:
    """Run a BIA sync: unlock, decrypt credential, retrieve, map, and persist.

    Returns the **open** store (caller closes it, e.g. via ``with``). The
    passphrase is validated by :meth:`EncryptedOpenEhrStore.open` — the retrieval
    trigger's gateway — before any data is fetched.

    ``connector_factory`` receives the decrypted API key and returns a connector;
    it defaults to the mock connector. Swap it for the live Google Fit connector
    without touching the trigger logic.
    """
    # --- GATEWAY: passphrase must unlock the store, or we never retrieve. ---
    store = EncryptedOpenEhrStore.open(user_id, passphrase, base_dir=base_dir)
    try:
        api_key = store.get_secret(GOOGLE_HEALTH_API_KEY)
        if not api_key:
            raise MissingCredentialError(
                f"no {GOOGLE_HEALTH_API_KEY!r} stored for user {user_id!r}; "
                "provision it with store.put_secret() before syncing"
            )

        factory = connector_factory or (
            lambda key: MockGoogleHealthConnector(months=months, api_key=key)
        )
        connector = factory(api_key)

        for measurement in connector.fetch_bia_measurements():
            store.put_composition(bia_to_composition(measurement))
    except Exception:
        store.close()
        raise

    return store
