"""Host firewall allow-list for the local LLM port.

llama-server must bind ``0.0.0.0`` so that **both** host-loopback clients
(127.0.0.1 — the assistant and the direct-to-model demo calls) **and** the Dify
containers (which reach the host via their compose-network gateway, e.g.
172.18.0.1) can talk to it. A single ``--host`` address cannot cover both without
also covering physical Wi-Fi/LAN/mobile interfaces.

So we keep the wide bind but *narrow the network at the firewall*: an nftables
allow-list that accepts the LLM port only from loopback and the Docker private
range (172.16.0.0/12) and drops it everywhere else. This is the real "network
narrow allow list" — it fails safe on external interfaces while leaving the
loopback + container paths intact.

The rule lives in its own ``inet localcounsel`` table so it can be applied
idempotently (atomic delete+recreate) without touching Docker's own iptables
rules, and removed cleanly.
"""

from __future__ import annotations

import shutil
import subprocess

from .config import PORT

_TABLE = "localcounsel"


def _ruleset(port: int) -> str:
    # add+delete+add makes re-applying idempotent whether or not the table exists.
    return f"""\
add table inet {_TABLE}
delete table inet {_TABLE}
table inet {_TABLE} {{
    chain llm_guard {{
        type filter hook input priority filter; policy accept;
        tcp dport {port} iif "lo" accept
        tcp dport {port} ip saddr 172.16.0.0/12 accept
        tcp dport {port} drop
    }}
}}
"""


def _run_nft(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess | None:
    """Run nft directly, then via passwordless sudo. None if nft is absent."""
    if not shutil.which("nft"):
        return None
    attempts = [["nft", *args]]
    if shutil.which("sudo"):
        attempts.append(["sudo", "-n", "nft", *args])
    result: subprocess.CompletedProcess | None = None
    for cmd in attempts:
        result = subprocess.run(cmd, input=stdin, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            return result
    return result  # last failure (surfaces stderr to callers)


def is_llm_port_firewalled(port: int = PORT) -> bool:
    """True if our allow-list table is installed for ``port``."""
    res = _run_nft(["list", "table", "inet", _TABLE])
    return bool(res and res.returncode == 0 and f"dport {port}" in res.stdout)


def ensure_llm_port_firewall(port: int = PORT) -> bool:
    """Idempotently install the allow-list. True on success.

    Requires root or passwordless sudo (loading nft rules needs CAP_NET_ADMIN).
    Returns False — never raises — so callers can warn without aborting a boot.
    """
    res = _run_nft(["-f", "-"], stdin=_ruleset(port))
    return bool(res and res.returncode == 0)


def remove_llm_port_firewall() -> bool:
    """Remove the allow-list table (no-op if absent)."""
    res = _run_nft(["delete", "table", "inet", _TABLE])
    return bool(res and res.returncode == 0)
