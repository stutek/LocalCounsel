"""LocalCounsel ops pipeline package.

The nox sessions in the root ``noxfile.py`` are thin wrappers around these
modules. Ops logic lives here (per the project rule: app logic in ``src/``,
ops logic in the pipeline); none of these modules may import ``nox`` at module
level — they must stay importable in plain Python (and in the unit tests).

Modules:
    config        paths, env-overridable settings, URLs, pinned SHA-256 digests
    util          tiny shared helpers (timestamping, latest-links, safe rmtree)
    provisioning  verified downloads (pin/TOFU) and llama.cpp extraction
    server        llama-server lifecycle (health polling, boot, stop)
    reporting     JUnit-XML -> Markdown test report rendering
    okf           deterministic OKF v0.1 bundle conformance checks
"""
