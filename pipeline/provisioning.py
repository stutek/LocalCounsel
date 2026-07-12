"""Verified artifact downloads and llama.cpp extraction for the pipeline."""

from __future__ import annotations

import hashlib
import tarfile
import urllib.request
from pathlib import Path

from .config import (
    DIFY_DIR,
    DIFY_SHA256,
    DIFY_TAR,
    DIFY_URL,
    LLAMA_DIR,
    LLAMA_SHA256,
    LLAMA_TAR,
    LLAMA_URL,
    MODEL_FILE,
    MODEL_SHA256,
    MODEL_URL,
    require_supported_platform,
)


def sha256_file(path: Path) -> str:
    """Stream-hash a file with SHA-256 (constant memory, large files ok)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(dest: Path, expected: str) -> None:
    """Verify ``dest`` against ``expected``; abort loudly on mismatch."""
    actual = sha256_file(dest)
    if actual.lower() != expected.lower():
        raise SystemExit(
            f"✗ SHA-256 mismatch for {dest.name}\n"
            f"    expected: {expected}\n"
            f"    actual:   {actual}\n"
            "    Refusing to use a corrupt/tampered artifact. Delete it and re-run, "
            "or correct the expected hash."
        )
    print(f"✓ SHA-256 verified for {dest.name}")


def download(url: str, dest: Path, sha256: str | None = None, tofu: bool = False) -> None:
    """Idempotently stream a URL to ``dest`` with optional integrity verification.

    Verification runs whether the file was just downloaded or already present:
      - ``sha256`` given: verify against it; abort on mismatch.
      - ``tofu=True`` (trust-on-first-use): for unpinned "latest" URLs that have no
        stable versioned form. On first fetch we record the digest to a ``.sha256``
        sidecar and pin every later run to it. The URL is mutable, so we always warn.
      - neither: we cannot verify — print a LOUD warning (never fail silently), per
        the project's fallback rule.
    """
    tofu_file = dest.with_name(dest.name + ".sha256")
    if tofu and sha256 is None and tofu_file.exists():
        sha256 = tofu_file.read_text().strip().split()[0]  # pinned on a prior run

    if dest.exists() and dest.stat().st_size > 0:
        print(f"✓ {dest.name} already present")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"↓ downloading {url}\n    → {dest}")
        req = urllib.request.Request(url, headers={"User-Agent": "local-counsel/0.1"})
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            read = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                read += len(chunk)
                if total:
                    pct = read * 100 // total
                    print(f"\r    {pct:3d}%  ({read >> 20} / {total >> 20} MiB)", end="", flush=True)
            if total:
                print()
        tmp.replace(dest)

    # --- Integrity verification (idempotency rule) --- #
    if tofu:
        if sha256 is not None:
            verify_sha256(dest, sha256)
            print(
                f"⚠️  WARNING: {dest.name} comes from an UNPINNED 'latest' URL "
                f"({url}); verified against the recorded trust-on-first-use hash."
            )
        else:
            digest = sha256_file(dest)
            tofu_file.write_text(f"{digest}  {dest.name}\n")
            print(
                f"⚠️  WARNING: {dest.name} comes from an UNPINNED 'latest' URL "
                f"({url}); no stable versioned URL exists.\n"
                f"    Trust-on-first-use: recorded SHA-256 {digest} to "
                f"{tofu_file.name}; future runs will verify against it."
            )
    elif sha256:
        verify_sha256(dest, sha256)
    else:
        print(
            f"⚠️  WARNING: no SHA-256 configured for {dest.name} — downloaded "
            "WITHOUT integrity verification (set the corresponding LC_*_SHA256)."
        )


def extract_llama() -> None:
    """Extract the llama.cpp tarball (POSIX targets only — Linux/macOS).

    Python's tarfile extracts natively, handling symlinks and platform files.
    """
    server = find_server()
    if server is not None:
        print("✓ llama.cpp already extracted")
        return
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    print("⇲ extracting llama.cpp ...")
    with tarfile.open(LLAMA_TAR, "r:gz") as tar:
        try:
            tar.extractall(LLAMA_DIR, filter="data")  # py3.12+ safe filter
        except TypeError:
            tar.extractall(LLAMA_DIR)


def find_server() -> Path | None:
    if not LLAMA_DIR.exists():
        return None
    names = ("llama-server", "server")
    for name in names:
        for path in LLAMA_DIR.rglob(name):
            if path.is_file():
                return path
    return None


def find_dify() -> Path | None:
    if not DIFY_DIR.exists():
        return None
    for path in DIFY_DIR.rglob("docker-compose.yaml"):
        if path.is_file() and path.parent.name == "docker":
            return path.parent
    return None


def extract_dify() -> None:
    """Extract the Dify tarball into build/dify."""
    docker_dir = find_dify()
    if docker_dir is not None:
        print("✓ Dify already extracted")
        return
    DIFY_DIR.mkdir(parents=True, exist_ok=True)
    print("⇲ extracting Dify ...")
    with tarfile.open(DIFY_TAR, "r:gz") as tar:
        try:
            tar.extractall(DIFY_DIR, filter="data")
        except TypeError:
            tar.extractall(DIFY_DIR)


def provision() -> None:
    require_supported_platform()
    download(MODEL_URL, MODEL_FILE, sha256=MODEL_SHA256)
    download(LLAMA_URL, LLAMA_TAR, sha256=LLAMA_SHA256)
    extract_llama()
    download(DIFY_URL, DIFY_TAR, sha256=DIFY_SHA256, tofu=True)
    extract_dify()
