#!/usr/bin/env python3
import sys
import os
import argparse
from urllib import request, error
import json


def _fail(message: str) -> None:
    """Print an error to stderr and exit non-zero so callers can detect failure."""
    print(message, file=sys.stderr)
    sys.exit(1)


def call_claude(prompt: str) -> str:
    api_key = None

    # 1. Local key file
    key_path = os.path.expanduser("~/.anthropic_key")
    if os.path.exists(key_path):
        try:
            with open(key_path, "r") as f:
                api_key = f.read().strip()
        except Exception:
            pass

    # 2. Environment variable
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        _fail(
            f"Error: ANTHROPIC_API_KEY is not set. Create {key_path} with your key "
            "or set the ANTHROPIC_API_KEY environment variable."
        )

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    req = request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["content"][0]["text"]
    except error.HTTPError as e:
        _fail(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        _fail(f"Error connecting to Anthropic API: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Query Claude via Anthropic API")
    parser.add_argument("--prompt", required=True, help="Prompt to send to Claude")
    args = parser.parse_args()

    print(call_claude(args.prompt))

if __name__ == "__main__":
    main()
