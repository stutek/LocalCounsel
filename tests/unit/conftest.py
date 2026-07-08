"""Test setup for the fast, LLM-free unit suite.

Puts the repo ROOT on sys.path so the ops-side ``pipeline`` package (a sibling of
noxfile.py, not part of the installed ``local_counsel`` distribution) is
importable from the tests. ``pipeline`` modules never import nox at module level,
so no stubbing is needed and this suite stays stdlib + pytest only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
