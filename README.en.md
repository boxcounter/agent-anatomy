# Agent Anatomy

[![CI](https://github.com/boxcounter/agent-anatomy/actions/workflows/ci.yml/badge.svg)](https://github.com/boxcounter/agent-anatomy/actions/workflows/ci.yml)

**English** | [中文](README.md)

Dissect Claude Code multi-agent sessions across all three collaboration modes — sub-agent, agent team, and workflow. It collects a session's raw data and produces a unified event stream, an interactive timeline, a collaboration graph, and a report that reveals *how* the agents actually worked together.

## Install

```bash
# Requires Python 3.12+
uv sync
```

## Commands

### `collect` — gather a Sub-agent / Workflow session (post-run)

Run after a session ends. Copies the JSONL transcript, sub-agent sidechains, and Workflow run journals (`workflows/wf_*.json`, the authoritative topology for Workflow mode) into one directory.

```bash
uv run anatomy collect --session-id=<session-id>

# Find a session ID
ls ~/.claude/projects/*/
```

### `watch` — monitor an Agent Team session (live)

Start **before** launching an Agent Team session; stop with Ctrl+C. Uses kqueue to watch mailbox and task file changes.

```bash
uv run anatomy watch --team-name=<team-name>
```

### `analyze` — generate the analysis

Turns collected/watched raw data into analysis artifacts.

```bash
uv run anatomy analyze --session-dir=<path-to-analysis-dir>
```

Outputs:
- `report.html` — single-file explainer (flagship): mode primer + collaboration graph + timeline + a clickable drawer with each agent's full output
- `report.md` — the same analysis as Markdown
- `timeline.html` — D3.js interactive timeline
- `graph.mermaid` — collaboration graph (Mermaid)
- `events.jsonl` — unified event stream
- `agents/` — one Markdown file per agent, complete untruncated output

> Note: `watch` relies on `select.kqueue`, so it is macOS-only. `collect` and `analyze` are pure file processing.

## Development

```bash
uv sync --extra dev            # install dev dependencies (pytest / ruff / pyright)
uv run pytest tests/ -v        # run tests
uv run ruff check src/ tests/  # lint
uv run pyright src/ tests/     # type check
```

### Stack

Python 3.12+, uv, Click, Jinja2, D3.js, pytest, ruff, pyright (strict mode).
