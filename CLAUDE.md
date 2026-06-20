# Agent Anatomy — Project Context

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
src/agent_anatomy/
    __init__.py
    models.py                      # UnifiedEvent, EventType, EventSource (frozen event model)
    cli.py                         # Click entry point (collect/watch/analyze commands)
    collect.py                     # collect_session() — copy raw data from ~/.claude/
    watch.py                       # KqueueWatcher — kqueue-based file monitoring
    parser.py                      # parse_jsonl(), parse_raw_dir() — JSONL → UnifiedEvent[]
    roles.py                       # build_topology() — agent roles, spawn tree, mode (KEYSTONE)
    state_machine.py               # build_state_machines(), detect_anomalies()
    graph.py                       # build_collaboration_graph(), to_mermaid(), to_force_data()
    comparator.py                  # compare(), build_session_view(), session_summary(), view_to_dict()
    timeline.py                    # build_timeline_data(), render_html(), render_template()
    templates/
        timeline.html.j2           # D3.js v7 interactive timeline (role-coloured swimlanes)
        report.html.j2             # Single-file explainer: narrative + force graph + timeline
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
                          ▼
              roles.build_topology()                    # roles + spawn tree + mode
                          │
          ┌───────────────┼───────────────┬───────────────┐
          ▼               ▼               ▼               ▼
    events.jsonl    graph.mermaid    report.md       report.html
    timeline.html                                    (flagship explainer)
```

All human-facing artifacts derive from one `Topology` (`roles.py`): every agent
gets a role (lead / teammate / subagent / root) and a readable display name, the
spawn tree is reconstructed, and the session is classified
(Sub-agent / Agent Team / Hybrid) with the evidence recorded. The report reveals
the *mechanism*, not just event counts: a mode primer, a "who is who" cast, the
delegation tree, the shared task board (team) vs per-agent private to-do rollups
(sub-agent), and the communication log.

## Parsing details

The parser handles these JSONL content block types:

| Tool call name | Event type emitted | Key data |
|---------------|-------------------|----------|
| `Agent` | `agent_spawn` | `tool_use_id`, `agent_type`, `child_agent_id` |
| `SendMessage` | `message_send` | `from`, `to`, `summary`, `message_type` |
| `TaskCreate` | `task_create` | `task_id` (backfilled from tool_result), `subject` |
| `TaskUpdate` | `task_update` | `task_id`, `new_status`, `owner` |
| text blocks | `agent_message` | `role`, `content_summary` (truncated 200 chars, for compact displays), `text` (full untruncated output), `token_usage`, `tool_calls` |

A turn's `content` may be a list of blocks **or a bare string** — sub-agent prompts (the instruction each agent receives, i.e. the `Agent` call's `prompt`) are stored as string content. The parser emits these as `agent_message` (role `user`) too, so an agent's transcript starts with its instruction rather than its first reply.

`text` is the full output preserved for the per-agent transcripts: `analyze` writes one `analysis/agents/<id>-<slug>.md` per agent and embeds the same full text in `report.html`, where clicking any agent (graph node, timeline lane, or cast row) opens a drawer rendering its complete output as Markdown with code syntax highlighting (marked + highlight.js + DOMPurify, via CDN).

`TaskCreate` events get their `task_id` from subsequent `tool_result` blocks — the parser does a two-pass extraction: first scanning tool_results for `id` fields, then backfilling TaskCreate events. **Note:** the TaskCreate result is *plain text* (`"Task #N created successfully: …"`) and its `content` may be a bare string, not a list of blocks — the parser handles both forms and regex-extracts the id from the text (`_TASK_CREATED_RE`).

Task identity is mode-aware (`comparator._build_tasks`): in Agent Team mode tasks are a shared board keyed globally by id; in Sub-agent mode every agent reuses ids 1, 2, 3… for its own private to-do list, so tasks are keyed per-agent to avoid bogus cross-agent merges. Owner presence decides the hybrid case.

Sidechain association works via `meta.json` → `toolUseId` matching, done in **two phases**: `parse_raw_dir` first parses session.jsonl plus *every* sidechain into one event set, then resolves `child_agent_id`. A spawn's `tool_use` call can live in any transcript (a sub-agent that spawns another records it in its own sidechain), so linking against a partially-loaded event set would orphan nested spawns.

`team-config.json` (copied by `collect`) is loaded via `parser.load_team_config()` and passed to `build_topology` as **authoritative** role ground truth — the lead and named teammates come from `members[]` rather than heuristics. `parse_team_events` diffs `team-events.jsonl` snapshots **per file path** (mailboxes → message_send/read, task files → task_create/task_update); diffing against the globally-previous snapshot would compare unrelated files.

## Dev commands

```bash
uv sync                           # Install deps
uv run pytest tests/ -v           # Run tests
uv run ruff check src/ tests/     # Lint (E, F, I, N, W, UP rules)
uv run pyright src/ tests/        # Type check (strict mode)
uv run anatomy --help       # CLI help
```

## Code conventions

- Python 3.12+ type hints (`str | None`, `dict[str, Any]`, `list[UnifiedEvent]`)
- `src` layout
- All public functions fully typed
- Frozen dataclasses for immutable event model (`@dataclass(frozen=True)`)
- `UnifiedEvent.create()` factory classmethod for constructing events (auto-generates UUID)
- File locking and append-only JSONL for all output formats
- kqueue with periodic poll catchup as defense against event coalescing
