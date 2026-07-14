"""Helpers for the browser demos: an interactive narration overlay + local LLM call.

The :class:`Narrator` injects a bottom overlay with **Play/Pause** and **Next**
buttons. Each ``step()`` shows the current intention and then blocks the Python
test until the presenter advances — either automatically after a countdown
(pauseable) or, in ``--manual`` mode, only when **Next** is clicked. All pacing
logic lives in the browser; Python waits on a JS flag the buttons set.

When the browser is headless (the ``e2e`` validation stage), the narrator is
non-interactive: steps don't block, so the pipeline never waits for a human.

The model is called over the local OpenAI-compatible endpoint with stdlib
``urllib`` (no ``openai`` dependency).
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

DEMO_PAGE = Path(__file__).parent / "demo_page.html"
# Follow the address llama-server actually bound to (boot_llm publishes it as
# LC_LLM_HOST); falls back to loopback for a standalone run.
LLM_BASE = f"http://{os.getenv('LC_LLM_HOST', '127.0.0.1')}:8080/v1"

# Injected once per page: overlay markup, control state, and the tick loop.
_INSTALL_JS = r"""
() => {
  if (window.__demoCtl) return;
  const ctl = window.__demoCtl = { paused: false, advance: false, remaining: 0, total: 1, manual: false };
  const el = document.createElement('div');
  el.id = 'demo-narrator';
  el.style.cssText =
    'position:fixed;top:24px;left:50%;transform:translateX(-50%);z-index:2147483647;pointer-events:none;'
    + 'width:min(720px,92vw);padding:14px 18px 12px;border-radius:14px;color:#fff;'
    + 'background:rgba(20,26,34,.96);box-shadow:0 12px 40px rgba(0,0,0,.55);'
    + 'font:15px/1.45 system-ui,sans-serif;backdrop-filter:blur(6px)';
  el.innerHTML =
    '<div style="display:flex;align-items:flex-start;gap:14px">'
    + '<div style="flex:1"><div id="dn-title" style="font-weight:700"></div>'
    + '<div id="dn-detail" style="opacity:.9;margin-top:2px"></div></div>'
    + '<div style="display:flex;gap:8px;flex-shrink:0">'
    + '<button id="dn-toggle" title="Auto Play / Pause">▶ Auto Play</button>'
    + '<button id="dn-next" title="Next step">⏭ Next</button></div></div>'
    + '<div style="height:4px;margin-top:10px;background:#ffffff22;border-radius:3px;overflow:hidden">'
    + '<div id="dn-bar" style="height:100%;width:0;background:#58a6ff;transition:width .1s linear"></div></div>';
  document.body.appendChild(el);
  for (const b of el.querySelectorAll('button')) {
    b.style.cssText = 'pointer-events:auto;cursor:pointer;border:1px solid #ffffff33;background:#ffffff14;color:#fff;'
      + 'border-radius:9px;padding:6px 12px;font:600 14px system-ui';
  }
  const toggle = el.querySelector('#dn-toggle');
  toggle.onclick = () => { ctl.paused = !ctl.paused; toggle.textContent = ctl.paused ? '▶ Auto Play' : '⏸ Pause'; };
  el.querySelector('#dn-next').onclick = () => { ctl.advance = true; };
  setInterval(() => {
    const bar = document.getElementById('dn-bar');
    if (ctl.manual || ctl.paused) return;
    if (ctl.remaining > 0) {
      ctl.remaining -= 100;
      if (bar) bar.style.width = Math.max(0, 100 * (1 - ctl.remaining / ctl.total)) + '%';
      if (ctl.remaining <= 0) ctl.advance = true;
    }
  }, 100);
  window.__demoStep = (t, d, ms, manual, startPaused) => {
    document.getElementById('dn-title').textContent = t;
    document.getElementById('dn-detail').textContent = (manual || startPaused) ? d + '   ·   (click “Next” or “Auto Play”)' : d;
    ctl.total = ms || 1; ctl.remaining = ms; ctl.manual = manual; ctl.advance = false; ctl.paused = startPaused || manual;
    toggle.textContent = ctl.paused ? '▶ Auto Play' : '⏸ Pause';
    const bar = document.getElementById('dn-bar'); if (bar) bar.style.width = '0';
  };
}
"""


class Narrator:
    """On-screen, presenter-controlled step narration (headed) / no-op (headless)."""

    def __init__(self, page: Any, *, interactive: bool = True, manual: bool = False, start_paused: bool = False):
        self.page = page
        self.interactive = interactive
        self.manual = manual
        self.start_paused = start_paused or manual
        if interactive:
            page.evaluate(_INSTALL_JS)

    def step(self, title: str, detail: str, *, seconds: float = 3.0) -> None:
        if not self.interactive:
            self.page.wait_for_timeout(120)  # keep validation fast; never block on a human
            return
        self.page.evaluate(
            "([t, d, ms, manual, startPaused]) => window.__demoStep(t, d, ms, manual, startPaused)",
            [title, detail, int(seconds * 1000), self.manual, self.start_paused],
        )
        # Block until Play/Pause countdown elapses or the presenter clicks Next.
        self.page.wait_for_function("() => window.__demoCtl && window.__demoCtl.advance === true", timeout=0)
        self.page.evaluate("() => { window.__demoCtl.advance = false; }")

    # Convenience so existing call sites read naturally.
    __call__ = step

    def hold_open(self) -> None:
        """Keep a headed demo window open until the presenter closes it.

        No-op when headless so the pipeline's ``e2e`` stage finishes normally.
        """
        if not self.interactive:
            return
        self.page.evaluate(
            """() => {
                const t = document.getElementById('dn-title');
                const d = document.getElementById('dn-detail');
                const bar = document.getElementById('dn-bar');
                if (t) t.textContent = '✅ Demo complete';
                if (d) d.textContent = 'Close the browser window when you are done.';
                if (bar) bar.style.width = '100%';
                for (const id of ['dn-next', 'dn-toggle']) {
                    const b = document.getElementById(id); if (b) b.style.display = 'none';
                }
                if (window.__demoCtl) window.__demoCtl.manual = true;
            }"""
        )
        try:
            self.page.wait_for_event("close", timeout=0)  # blocks until the user closes the window
        except Exception:
            pass  # browser/context torn down elsewhere — fine


def make_narrator(page: Any, request: Any) -> Narrator:
    """Build a Narrator from pytest config: interactive only when headed."""
    return Narrator(
        page,
        interactive=bool(request.config.getoption("--headed")),
        manual=bool(request.config.getoption("--manual", False)),
        start_paused=bool(request.config.getoption("--start-paused", False)),
    )


def _http_json(url: str, payload: dict | None = None, timeout: float = 300.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def served_model() -> str:
    try:
        return _http_json(f"{LLM_BASE}/models")["data"][0]["id"]
    except Exception as exc:  # pragma: no cover - demo convenience
        return f"<model endpoint unavailable: {exc}>"


def ask_local_llm(prompt: str) -> str:
    """Direct call to the local model (reference/fallback; bypasses Dify)."""
    body = {"model": "gemma", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 256}
    resp = _http_json(f"{LLM_BASE}/chat/completions", body, timeout=120.0)
    return resp["choices"][0]["message"]["content"]


# Files written by pipeline.dify_setup once the Dify app is provisioned.
_DIFY_DIR = Path(__file__).resolve().parents[2] / "build" / "dify"


def ask_via_dify(prompt: str, *, user: str = "demo") -> str:
    """Ask through the **Dify** app API (Dify -> local Gemma), or fallback directly to local model."""
    key_file = _DIFY_DIR / "api_key.txt"
    base_file = _DIFY_DIR / "api_base.txt"
    if not key_file.exists():
        return ask_local_llm(prompt)
    api_key = key_file.read_text(encoding="utf-8").strip()
    api_base = (base_file.read_text(encoding="utf-8").strip() if base_file.exists() else "http://localhost/v1")
    body = {"inputs": {}, "query": prompt, "response_mode": "blocking", "user": user}
    req = urllib.request.Request(
        f"{api_base}/chat-messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode())
        return data.get("answer") or data.get("data", {}).get("outputs", {}).get("text", "") or ask_local_llm(prompt)
    except Exception as exc:
        print(f"⚠️ Dify request failed or timed out ({exc}); falling back to direct local LLM completion.")
        return ask_local_llm(prompt)

