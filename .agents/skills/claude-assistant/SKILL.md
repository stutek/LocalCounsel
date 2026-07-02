---
name: claude-assistant
description: Use this skill to delegate complex coding tasks or queries to Claude (Anthropic). This runs a helper script that calls the Anthropic API using ANTHROPIC_API_KEY.
type: Skill
title: Claude Assistant Bridge
tags: [claude, subagent, assistant]
timestamp: 2026-07-02T23:53:00+02:00
---

# Claude Assistant Skill

Use this skill when the user explicitly requests to consult Claude, or for tasks that require Claude's specialized analysis or code generation.

## Usage

You can call the Claude subagent helper script using `run_command`:

```bash
python3 .agents/skills/claude-assistant/scripts/call_claude.py --prompt "Your prompt here"
```

The script will read the `ANTHROPIC_API_KEY` from the environment and print Claude's response.
