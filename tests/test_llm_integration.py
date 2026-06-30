"""Integration test against the local LLM sandbox.

Requires a running ``llama-server`` (the nox ``test`` session boots it first via
``nox -s test``). It verifies the OpenAI-compatible endpoint answers a ping.
"""

from __future__ import annotations

from local_counsel.assistant import ask


def test_model_identification() -> None:
    prompt = (
        "Hello! Please acknowledge this ping and confirm you are ready to "
        "review compliance documents."
    )
    response = ask(prompt)
    assert response is not None, "Response should not be null"
    assert response.strip(), "Response should not be empty"
