# Agent Team Analysis Tool — Project Context

## What this is

A CLI tool (Python 3.12+, `uv`) that analyzes Claude Code multi-agent sessions. It reads session transcript files (`~/.claude/projects/`) and produces analysis artifacts: unified event streams, D3.js timelines, Mermaid collaboration graphs, and comparative reports.

## Architecture

Three commands, clean separation:

| Command | When | What |
|---------|------|------|
| `collect --session-id=X` | Post-session (Sub-agent mode) | Copies JSONL/meta/task/mailbox data into `analysis/raw/` |
| `watch --team-name=X` | During session (Agent Team mode) | kqueue-based realtime monitoring of mailbox/task file changes |
| `analyze --session-dir=X` | After collect or watch | Parses raw data → unified events → timeline/graph/report |

**Key design decisions:**
- Collect and analyze are separated. Raw data is reusable; analysis logic is independently iterable.
- kqueue (not eslogger) for watch — Agent Team writes are lock-serialized, so kqueue's event coalescing risk is negligible. No sudo required.
- The JSONL transcript is the authoritative data source. All tool calls (SendMessage, TaskUpdate, Agent spawn) are recorded there. Mailbox and task files are just the implementation mechanism.

## File map

```
pyproject.toml                     # uv, ruff, pyright, pytest config
src/analysis_tool/
    __init__.py
    models.py                      # UnifiedEvent, EventType, EventSource, StateTransition, etc.
    cli.py                         # Click entry point (collect/watch/analyze commands)
    collect.py                     # collect_session() — copy raw data from ~/.claude/
    watch.py                       # KqueueWatcher — kqueue-based file monitoring
    parser.py                      # parse_jsonl(), parse_raw_dir() — JSONL → UnifiedEvent[]
    state_machine.py               # build_state_machines(), detect_anomalies()
    graph.py                       # build_collaboration_graph(), to_mermaid()
    comparator.py                  # compare(), session_summary()
    timeline.py                    # build_timeline_data(), render_html()
    templates/
        timeline.html.j2           # D3.js v7 interactive timeline
tests/
    conftest.py                    # fixtures_dir fixture
    fixtures/                      # Mock session data for unit tests
    test_*.py                      # One test file per module
docs/
    superpowers/
        specs/2026-06-18-agent-team-analysis-design.md
        plans/2026-06-18-agent-team-analysis-plan.md
```

## Data flow

```
~/.claude/projects/{project}/{session-id}.jsonl         # Main transcript (append-only JSONL)
~/.claude/projects/{project}/{session-id}/subagents/    # Sidechain transcripts + meta.json
~/.claude/teams/{team}/inboxes/{agent}.json             # Agent mailboxes (live)
~/.claude/tasks/{team}/{id}.json                        # Task state files (live)
                          │
                          ▼
              analysis/raw/                             # Collected raw data
                          │
                          ▼
              parser.py → UnifiedEvent[]                # Typed event stream
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    events.jsonl    graph.mermaid    report.md
    timeline.html
```

## Parsing details

The parser handles these JSONL content block types:

| Tool call name | Event type emitted | Key data |
|---------------|-------------------|----------|
| `Agent` | `agent_spawn` | `tool_use_id`, `agent_type`, `child_agent_id` |
| `SendMessage` | `message_send` | `from`, `to`, `summary`, `message_type` |
| `TaskCreate` | `task_create` | `task_id` (backfilled from tool_result), `subject` |
| `TaskUpdate` | `task_update` | `task_id`, `new_status`, `owner` |
| text blocks | `agent_message` | `role`, `content_summary` (truncated 200 chars), `token_usage`, `tool_calls` |

`TaskCreate` events get their `task_id` from subsequent `tool_result` blocks — the parser does a two-pass extraction: first scanning tool_results for `id` fields, then backfilling TaskCreate events.

Sidechain association works via `meta.json` → `toolUseId` matching: the parser finds the parent `agent_spawn` event whose `tool_use_id` matches the meta's `toolUseId`, and sets `child_agent_id`.

## Dev commands

```bash
uv sync                           # Install deps
uv run pytest tests/ -v           # Run tests
uv run ruff check src/ tests/     # Lint (E, F, I, N, W, UP rules)
uv run pyright src/ tests/        # Type check (strict mode)
uv run analysis-tool --help       # CLI help
```

## Code conventions

- Python 3.12+ type hints (`str | None`, `dict[str, Any]`, `list[UnifiedEvent]`)
- `src` layout
- All public functions fully typed
- Frozen dataclasses for immutable event model (`@dataclass(frozen=True)`)
- `UnifiedEvent.create()` factory classmethod for constructing events (auto-generates UUID)
- File locking and append-only JSONL for all output formats
- kqueue with periodic poll catchup as defense against event coalescing
