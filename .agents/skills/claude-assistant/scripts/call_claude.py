#!/usr/bin/env python3
import sys
import os
import argparse
from urllib import request, error
import json

def call_claude(prompt: str) -> str:
    api_key = None
    
    # 1. Try secure local file (completely invisible to the AI agent / Google)
    key_path = os.path.expanduser("~/.anthropic_key")
    if os.path.exists(key_path):
        try:
            with open(key_path, "r") as f:
                api_key = f.read().strip()
        except Exception:
            pass

    # 2. Fallback to environment variable
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        
    # 3. Fallback to stdin
    if not api_key and not sys.stdin.isatty():
        api_key = sys.stdin.read().strip()
            
    if not api_key:
        return f"Error: ANTHROPIC_API_KEY is not set. Please create {key_path} with your key, set the environment variable, or pipe the key."

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
        with request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["content"][0]["text"]
    except error.HTTPError as e:
        return f"HTTP Error {e.code}: {e.read().decode('utf-8')}"
    except Exception as e:
        return f"Error connecting to Anthropic API: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="Query Claude via Anthropic API")
    parser.add_argument("--prompt", required=True, help="Prompt to send to Claude")
    args = parser.parse_args()
    
    print(call_claude(args.prompt))

if __name__ == "__main__":
    main()
