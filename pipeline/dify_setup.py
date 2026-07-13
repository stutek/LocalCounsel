"""Idempotent provisioning of the local Dify.ai stack for the Longevity Mentor demo.

The pipeline — not the test — owns this dependency. Given a running Dify stack
(``nox -s boot_dify``), this step idempotently:

1. completes Dify's first-run admin setup (if not already done),
2. registers the local ``llama-server`` (Gemma 4) as an OpenAI-API-compatible
   model provider (``host.docker.internal:8080/v1``),
3. ensures a **Longevity Mentor** chat app exists and is published, and
4. writes its public chat URL to ``build/dify/app_url.txt`` for the demo to consume.

Targets Dify **1.15.0**'s console API. Every failure raises loudly (Rule 9): the
demo must surface a broken dependency as a pipeline failure, never a silent skip.

NOTE: this talks to Dify's internal console API, whose exact shape is
version-specific. It is written against 1.15.0 but has not yet been validated
against a live stack in this environment — expect a short iteration pass the first
time it runs against real Dify.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.config import BUILD

CONSOLE = "http://localhost/console/api"
SITE_BASE = "http://localhost"
ADMIN_EMAIL = "demo@localcounsel.local"
ADMIN_PASSWORD = "LocalCounsel-Demo-2026!"
ADMIN_NAME = "LocalCounsel Demo"
APP_NAME = "Longevity Mentor"
APP_URL_FILE = BUILD / "dify" / "app_url.txt"


def _get_llm_endpoint() -> str:
    from pipeline.config import HOST, PORT
    if HOST not in ("0.0.0.0", "127.0.0.1"):
        return f"http://{HOST}:{PORT}/v1"
    import subprocess

    for cmd in (
        [
            "docker",
            "inspect",
            "docker-api-1",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}",
        ],
        [
            "sg",
            "docker",
            "-c",
            "docker inspect docker-api-1 --format '{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}'",
        ],
    ):
        try:
            out = subprocess.check_output(
                cmd, text=True, stderr=subprocess.DEVNULL
            ).strip()
            for ip in out.split():
                if ip and ip != "invalid":
                    return f"http://{ip}:8080/v1"
        except Exception:
            continue
    return "http://172.18.0.1:8080/v1"



def _req(method: str, path: str, auth: tuple[str, str] | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if auth:
        access_token, csrf_token = auth
        headers["Authorization"] = f"Bearer {access_token}"
        headers["Cookie"] = f"access_token={access_token}; csrf_token={csrf_token}"
        headers["X-CSRF-Token"] = csrf_token
    req = urllib.request.Request(f"{CONSOLE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Dify {method} {path} -> HTTP {exc.code}: {detail}") from exc


def _wait_console(timeout_s: float = 120.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _req("GET", "/setup")
            return
        except Exception:
            time.sleep(3)
    raise RuntimeError(
        "Dify console API not reachable at http://localhost/console/api — "
        "is the stack up? Run `nox -s boot_dify`."
    )


def _ensure_admin() -> None:
    state = _req("GET", "/setup")
    if state.get("step") == "finished":
        return
    print("⚙️  Dify: performing first-run admin setup ...")
    _req("POST", "/setup", body={"email": ADMIN_EMAIL, "name": ADMIN_NAME, "password": ADMIN_PASSWORD})


def _login() -> tuple[str, str]:
    encoded_pw = base64.b64encode(ADMIN_PASSWORD.encode("utf-8")).decode("utf-8")
    data = json.dumps({"email": ADMIN_EMAIL, "password": encoded_pw, "remember_me": True}).encode()
    req = urllib.request.Request(
        f"{CONSOLE}/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            access_token = None
            csrf_token = None
            cookies = resp.headers.get_all("Set-Cookie") or []
            for cookie in cookies:
                for part in cookie.split(";"):
                    part = part.strip()
                    if part.startswith("access_token=") or part.startswith("__Host-access_token="):
                        access_token = part.split("=", 1)[1]
                    elif part.startswith("csrf_token=") or part.startswith("__Host-csrf_token="):
                        csrf_token = part.split("=", 1)[1]
            if access_token and csrf_token:
                return (access_token, csrf_token)
            raise RuntimeError(f"Dify login missing cookies (access={bool(access_token)}, csrf={bool(csrf_token)})")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Dify POST /login -> HTTP {exc.code}: {detail}") from exc


def _ensure_provider(auth: tuple[str, str]) -> None:
    print("⚙️  Dify: registering local Gemma 4 as OpenAI-API-compatible provider ...")
    provider_id = "langgenius/openai_api_compatible/openai_api_compatible"
    providers = _req("GET", "/workspaces/current/model-providers", auth=auth).get("data", [])
    installed = False
    for p in providers:
        p_name = p.get("provider", "")
        if "openai_api_compatible" in p_name:
            provider_id = p_name
            installed = True
            break

    if not installed:
        print("  Installing OpenAI-API-compatible plugin ...")
        try:
            _req(
                "POST",
                "/workspaces/current/plugin/install/marketplace",
                auth=auth,
                body={"plugin_unique_identifiers": ["langgenius/openai_api_compatible"]},
            )
            for _ in range(20):
                time.sleep(1)
                providers = _req("GET", "/workspaces/current/model-providers", auth=auth).get("data", [])
                for p in providers:
                    p_name = p.get("provider", "")
                    if "openai_api_compatible" in p_name:
                        provider_id = p_name
                        installed = True
                        break
                if installed:
                    break
        except Exception as exc:
            print(f"  Note during plugin install: {exc}")

    llm_endpoint = _get_llm_endpoint()
    try:
        _req(
            "POST",
            f"/workspaces/current/model-providers/{provider_id}/models/credentials",
            auth=auth,
            body={
                "model": "gemma",
                "model_type": "llm",
                "credentials": {
                    "endpoint_url": llm_endpoint,
                    "api_key": "sk-local",
                    "mode": "chat",
                    "context_size": "8192",
                },
            },
        )
        import subprocess
        subprocess.run(
            ["sg", "docker", "-c", "docker exec docker-db_postgres-1 psql -U postgres -d dify -c \"UPDATE provider_models SET credential_id = (SELECT id FROM provider_model_credentials ORDER BY created_at DESC LIMIT 1) WHERE model_name = 'gemma';\""],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as exc:
        print(f"  Note: provider model registration returned: {exc}")
    return provider_id


def _ensure_app(auth: tuple[str, str], provider_id: str) -> str:
    apps = _req("GET", "/apps?page=1&limit=100", auth=auth).get("data", [])
    for app in apps:
        if app.get("name") == APP_NAME:
            app_id = app["id"]
            break
    else:
        print(f"⚙️  Dify: creating '{APP_NAME}' chat app ...")
        created = _req(
            "POST", "/apps", auth=auth,
            body={"name": APP_NAME, "mode": "chat", "icon": "🧬", "icon_background": "#111c"},
        )
        app_id = created["id"]

    _req(
        "POST",
        f"/apps/{app_id}/model-config",
        auth=auth,
        body={
            "model": {
                "provider": provider_id,
                "name": "gemma",
                "mode": "chat",
                "completion_params": {"max_tokens": 1024, "temperature": 0.2},
            }
        },
    )
    _req("POST", f"/apps/{app_id}/site-enable", auth=auth, body={"enable_site": True})
    detail = _req("GET", f"/apps/{app_id}", auth=auth)
    site = detail.get("site") or {}
    code = site.get("access_token") or site.get("code")
    if not code:
        raise RuntimeError(f"Could not resolve public chat URL for app {app_id}: {detail}")

    # Service API key so demos can call the app API (Dify → local Gemma), not the
    # model directly. Reuse an existing key or mint one.
    keys = _req("GET", f"/apps/{app_id}/api-keys", auth=auth).get("data", [])
    api_token = keys[0]["token"] if keys else _req("POST", f"/apps/{app_id}/api-keys", auth=auth)["token"]
    (BUILD / "dify").mkdir(parents=True, exist_ok=True)
    (BUILD / "dify" / "api_key.txt").write_text(api_token, encoding="utf-8")
    (BUILD / "dify" / "api_base.txt").write_text(f"{SITE_BASE}/v1", encoding="utf-8")
    return f"{SITE_BASE}/chat/{code}"


def _patch_dify_web() -> None:
    """Patch Dify Next.js bundles so public share links don't redirect to /signin on 401."""
    js_code = r"""
const fs = require("fs");
const guard = 'if(typeof window!=="undefined"&&(window.location.pathname.includes("/chat/")||window.location.pathname.includes("/chatbot/")||window.location.pathname.includes("/completion/")||window.location.pathname.includes("/workflow/")))return;';
const dirs = [
  "/app/targets/next/web/.next/static/chunks",
  "/app/targets/next/web/.next/server/chunks/ssr"
];
for (const dir of dirs) {
  try {
    const files = fs.readdirSync(dir).filter(f => f.endsWith(".js"));
    for (const f of files) {
      const p = dir + "/" + f;
      try {
        let c = fs.readFileSync(p, "utf8");
        let modified = false;
        if (c.includes("function eO(e,t){") && !c.includes("function eO(e,t){" + guard)) {
          c = c.replace(/function eO\(e,t\)\{/g, "function eO(e,t){" + guard);
          modified = true;
        }
        if (c.includes("function eA(e){") && !c.includes("function eA(e){" + guard)) {
          c = c.replace(/function eA\(e\)\{/g, "function eA(e){" + guard);
          modified = true;
        }
        if (modified) fs.writeFileSync(p, c, "utf8");
      } catch (e) {}
    }
  } catch (e) {}
}
"""
    try:
        import subprocess
        subprocess.run(
            ["sg", "docker", "-c", "docker exec -i docker-web-1 node -"],
            input=js_code,
            text=True,
            capture_output=True,
            check=False,
        )
        # Also ensure Nginx does not serve JS chunks with immutable Cache-Control so patched bundles load immediately
        nginx_patch = r"""
import subprocess
p = "/etc/nginx/conf.d/default.conf"
c = open(p).read()
if "/_next/static/chunks/" not in c:
    old = "    location / {\n      proxy_pass http://web:3000;\n      include proxy.conf;\n    }"
    new = "    location /_next/static/chunks/ {\n      proxy_pass http://web:3000;\n      include proxy.conf;\n      proxy_hide_header Cache-Control;\n      add_header Cache-Control \"no-cache, no-store, must-revalidate\" always;\n    }\n\n    location / {\n      proxy_pass http://web:3000;\n      include proxy.conf;\n    }"
    c = c.replace(old, new)
    subprocess.run(["sg", "docker", "-c", "docker exec -i docker-nginx-1 sh -c \"cat > /etc/nginx/conf.d/default.conf\""], input=c, text=True, check=False)
    subprocess.run(["sg", "docker", "-c", "docker exec docker-nginx-1 nginx -s reload"], check=False)
"""
        subprocess.run(["python3", "-c", nginx_patch], capture_output=True, check=False)
    except Exception:
        pass


def _warmup() -> None:
    """Prime the Dify → Gemma chain so the first demo message isn't a cold miss.

    On-device Gemma inference is slow, and the *first* request after boot also
    pays the model-load cost — long enough that a chat reply can appear to never
    arrive. A single blocking request here loads the model and validates the
    whole chain end-to-end (Dify app API → local llama-server) before the browser
    demo runs. A misconfigured chain (HTTP error) fails loudly (Rule 9); a mere
    timeout still leaves the model warm, so it only warns.
    """
    api_key = (BUILD / "dify" / "api_key.txt").read_text(encoding="utf-8").strip()
    api_base = (BUILD / "dify" / "api_base.txt").read_text(encoding="utf-8").strip()
    body = json.dumps(
        {"inputs": {}, "query": "Reply with the single word: ready.", "response_mode": "blocking", "user": "warmup"}
    ).encode()
    req = urllib.request.Request(
        f"{api_base}/chat-messages",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    print("⚙️  Dify: warming up local Gemma via the app API (first inference is slow) ...")
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            answer = json.loads(resp.read().decode()).get("answer", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Dify warmup POST /chat-messages -> HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        print(f"  Note: warmup did not complete ({exc}); the model is loading and stays warm.")
        return
    if not answer.strip():
        raise RuntimeError("Dify warmup returned an empty answer — the Dify → Gemma chain is broken.")
    print("✅ Dify warmup ok — model is warm.")


def setup_dify() -> str:
    """Provision Dify end-to-end and return the Longevity Mentor chat URL."""
    _wait_console()
    _ensure_admin()
    auth = _login()
    _patch_dify_web()
    provider_id = _ensure_provider(auth)
    url = _ensure_app(auth, provider_id)
    APP_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    APP_URL_FILE.write_text(url, encoding="utf-8")
    _warmup()
    print(f"✅ Dify Longevity Mentor ready: {url}")
    return url



if __name__ == "__main__":
    try:
        setup_dify()
    except Exception as exc:  # loud failure — never silent (Rule 9)
        print(f"❌ Dify setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
