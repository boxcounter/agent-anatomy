from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from agent_anatomy.models import EventType, UnifiedEvent
from agent_anatomy.roles import AgentProfile, AgentRole, SessionMode, Topology, build_topology, canonical_id


@dataclass
class ComparisonReport:
    mode_a: str
    mode_b: str
    agent_count_a: int = 0
    agent_count_b: int = 0
    message_count_a: int = 0
    message_count_b: int = 0
    spawn_count_a: int = 0
    spawn_count_b: int = 0
    total_tokens_a: int = 0
    total_tokens_b: int = 0
    duration_seconds_a: float = 0.0
    duration_seconds_b: float = 0.0
    sections: list[str] = field(default_factory=lambda: [])


def compare(
    events_a: list[UnifiedEvent],
    mode_a: str,
    events_b: list[UnifiedEvent],
    mode_b: str,
) -> ComparisonReport:
    """Compare two sessions and produce a structured report."""
    report = ComparisonReport(mode_a=mode_a, mode_b=mode_b)

    agents_a = {e.agent_id for e in events_a}
    agents_b = {e.agent_id for e in events_b}
    report.agent_count_a = len(agents_a)
    report.agent_count_b = len(agents_b)

    report.message_count_a = sum(1 for e in events_a if e.type == EventType.MESSAGE_SEND)
    report.message_count_b = sum(1 for e in events_b if e.type == EventType.MESSAGE_SEND)

    report.spawn_count_a = sum(1 for e in events_a if e.type == EventType.AGENT_SPAWN)
    report.spawn_count_b = sum(1 for e in events_b if e.type == EventType.AGENT_SPAWN)

    for events, attr in [(events_a, "total_tokens_a"), (events_b, "total_tokens_b")]:
        total: int = 0
        for e in events:
            if e.type == EventType.AGENT_COMPLETE:
                total += int(e.data.get("tokens_used", 0))
            elif e.type == EventType.AGENT_MESSAGE:
                usage: object = e.data.get("token_usage", {})
                if isinstance(usage, dict):
                    total += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        setattr(report, attr, total)

    if events_a:
        report.duration_seconds_a = (events_a[-1].timestamp - events_a[0].timestamp).total_seconds()
    if events_b:
        report.duration_seconds_b = (events_b[-1].timestamp - events_b[0].timestamp).total_seconds()

    return report


# --------------------------------------------------------------------------
# Session anatomy — the structured view that both report.md and report.html
# render from, so the two never drift.
# --------------------------------------------------------------------------


@dataclass
class TaskView:
    task_id: str
    subject: str
    created_by: str  # display name
    owner: str  # display name ("" if unclaimed)
    transitions: list[tuple[str, str, float]]  # (status, actor display, offset_s)
    final_status: str


@dataclass
class MessageView:
    offset_s: float
    from_label: str
    to_label: str
    message_type: str
    summary: str


@dataclass
class PrivateTodoGroup:
    """A single agent's private to-do list, rolled up (sub-agent mode)."""
    owner_label: str
    total: int
    completed: int
    in_progress: int
    other: int


@dataclass
class AgentOutput:
    """One agent's complete text output — every text-bearing turn, untruncated."""
    agent_id: str
    label: str
    role: str
    messages: list[tuple[float, str, str]]  # (offset_s, role, full text)


@dataclass
class PhaseView:
    """One phase of a Workflow run — the analog of a shared task on the board."""
    index: int
    title: str
    agents: int
    tokens: int
    tool_calls: int
    duration_s: float


@dataclass
class SessionView:
    topology: Topology
    t0: datetime | None
    duration_s: float
    agents: list[AgentProfile]  # role-sorted (excludes synthetic phase nodes)
    tasks: list[TaskView]  # shared / team tasks
    private_todos: list[PrivateTodoGroup]  # per-agent private lists (sub-agent mode)
    messages: list[MessageView]
    anomalies: list[str]
    counts: dict[str, int]
    phases: list[PhaseView] = field(default_factory=list[PhaseView])  # Workflow mode
    workflow: dict[str, Any] | None = None  # Workflow run header (name/status/totals)


_ROLE_ORDER = {
    AgentRole.LEAD: 0,
    AgentRole.ROOT: 1,
    AgentRole.PHASE: 2,
    AgentRole.TEAMMATE: 3,
    AgentRole.SUBAGENT: 4,
    AgentRole.UNKNOWN: 5,
}

_MODE_TITLE = {
    SessionMode.SUBAGENT: "Sub-agent",
    SessionMode.AGENT_TEAM: "Agent Team",
    SessionMode.WORKFLOW: "Workflow",
    SessionMode.HYBRID: "Hybrid (Agent Team + sub-agents)",
    SessionMode.UNKNOWN: "Unknown",
}

_MODE_PRIMER = {
    SessionMode.SUBAGENT: (
        "The root session uses the **Agent** tool to spawn one-shot, unnamed sub-agents "
        "(`agent-<hash>`), each with a fresh context and its own sidechain transcript. A "
        "sub-agent runs to completion and returns its result up to whoever spawned it — there "
        "is no shared task board and no peer-to-peer messaging. Sub-agents may themselves "
        "spawn more sub-agents, so the structure is a **delegation tree**."
    ),
    SessionMode.AGENT_TEAM: (
        "A **team lead** coordinates persistent, *named* teammates that each have their own "
        "session and mailbox. Work is decentralised through shared files: the lead posts tasks "
        "to a shared **task board** and assigns them via `task_assignment` mailbox messages; a "
        "teammate **claims** a task (sets `owner`), moves it `in_progress → completed`, and "
        "reports back by message. Coordination is peer-to-peer and asynchronous, not a "
        "spawn-and-return tree."
    ),
    SessionMode.WORKFLOW: (
        "A deterministic **orchestrator script** (the Workflow tool) drives the run: it fans out "
        "one-shot, context-isolated agents in ordered **phases**, where each phase's output feeds "
        "the next. Agents don't message peers and there's no shared task board — each runs to "
        "completion and returns its result to the orchestrator, which merges and routes it. It is "
        "sub-agent semantics at scale, but the control flow is *scripted* (loops, fan-out, "
        "barriers) rather than decided turn-by-turn by a model. The **Phases** table below is the "
        "structural spine; the delegation tree shows orchestrator → phase → agents."
    ),
    SessionMode.HYBRID: (
        "Both mechanisms are in play: a named team coordinates via a shared task board and "
        "mailboxes, *and* agents also spawn one-shot sub-agents via the Agent tool for "
        "self-contained work. Read the delegation tree for the spawn relationships and the task "
        "board for the team coordination."
    ),
    SessionMode.UNKNOWN: (
        "Not enough signal to classify the collaboration mode (no spawns, task assignments, or "
        "named members were observed)."
    ),
}


def _jint(value: object) -> int:
    """Coerce a journal numeric field to int, tolerant of int / float / dict.

    The per-agent `tokens` field may be a single total (int) or a split
    ({input, output} dict); either way we want one number for the rollup.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, Mapping):
        return sum(_jint(v) for v in value.values())  # type: ignore[reportUnknownArgumentType]
    return 0


def _build_phases(
    journals: list[Mapping[str, object]] | None,
) -> tuple[list[PhaseView], dict[str, Any] | None]:
    """Roll up Workflow journal(s) into per-phase stats + a run header."""
    if not journals:
        return [], None
    # Aggregate agent stats per phase across all journals.
    by_phase: dict[int, dict[str, Any]] = {}
    for journal in journals:
        progress = journal.get("workflowProgress", [])
        if not isinstance(progress, list):
            continue
        for entry_raw in cast(list[object], progress):
            if not isinstance(entry_raw, dict):
                continue
            entry = cast(dict[str, Any], entry_raw)
            if entry.get("type") != "workflow_agent":
                continue
            idx_raw = entry.get("phaseIndex", 0)
            idx = idx_raw if isinstance(idx_raw, int) else 0
            slot = by_phase.setdefault(
                idx, {"title": str(entry.get("phaseTitle", "") or "(phase)"),
                      "agents": 0, "tokens": 0, "tool_calls": 0, "duration_ms": 0}
            )
            slot["agents"] += 1
            slot["tokens"] += _jint(entry.get("tokens"))
            slot["tool_calls"] += _jint(entry.get("toolCalls"))
            slot["duration_ms"] += _jint(entry.get("durationMs"))

    phases = [
        PhaseView(
            index=idx, title=slot["title"], agents=slot["agents"],
            tokens=slot["tokens"], tool_calls=slot["tool_calls"],
            duration_s=slot["duration_ms"] / 1000.0,
        )
        for idx, slot in sorted(by_phase.items())
    ]

    # Run header from the first (typically only) journal.
    j0 = journals[0]
    workflow = {
        "name": str(j0.get("workflowName", "") or ""),
        "status": str(j0.get("status", "") or ""),
        "agent_count": _jint(j0.get("agentCount")) or sum(p.agents for p in phases),
        "total_tokens": _jint(j0.get("totalTokens")) or sum(p.tokens for p in phases),
        "total_tool_calls": _jint(j0.get("totalToolCalls")) or sum(p.tool_calls for p in phases),
        "duration_s": _jint(j0.get("durationMs")) / 1000.0,
        "model": str(j0.get("defaultModel", "") or ""),
    }
    return phases, workflow


def build_session_view(
    events: list[UnifiedEvent],
    team_config: Mapping[str, object] | None = None,
    workflow_journals: list[Mapping[str, object]] | None = None,
) -> SessionView:
    """Reconstruct the human-facing anatomy of a session from its events."""
    topology = build_topology(events, team_config, workflow_journals)
    t0 = events[0].timestamp if events else None
    duration_s = (events[-1].timestamp - events[0].timestamp).total_seconds() if events else 0.0

    def offset(ts: datetime) -> float:
        return (ts - t0).total_seconds() if t0 else 0.0

    # The cast is the real agents — synthetic phase grouping nodes are structure,
    # surfaced separately in the Phases section, not the who-is-who roster.
    agents = sorted(
        (p for p in topology.profiles.values() if p.role != AgentRole.PHASE),
        key=lambda p: (_ROLE_ORDER.get(p.role, 9), p.first_seen or t0 or datetime.min),
    )

    phases, workflow = _build_phases(workflow_journals)

    tasks, private_todos, anomalies = _build_tasks(events, topology, offset)

    messages: list[MessageView] = []
    for e in events:
        if e.type != EventType.MESSAGE_SEND:
            continue
        messages.append(MessageView(
            offset_s=offset(e.timestamp),
            from_label=topology.label(str(e.data.get("from", e.agent_id))),
            to_label=topology.label(str(e.data.get("to", ""))),
            message_type=str(e.data.get("message_type", "message")),
            summary=str(e.data.get("summary", "")),
        ))

    counts = {
        "agents": len(agents),  # real agents; synthetic phase nodes excluded
        "spawns": sum(1 for e in events if e.type == EventType.AGENT_SPAWN),
        "messages": len(messages),
        "tasks": len(tasks),
        "events": len(events),
    }
    if phases:
        counts["phases"] = len(phases)

    return SessionView(
        topology=topology,
        t0=t0,
        duration_s=duration_s,
        agents=agents,
        tasks=tasks,
        private_todos=private_todos,
        messages=messages,
        anomalies=anomalies,
        counts=counts,
        phases=phases,
        workflow=workflow,
    )


def _task_sort_key(task_id: str) -> tuple[int, str]:
    return (int(task_id), "") if task_id.isdigit() else (1 << 30, task_id)


@dataclass
class _TaskAcc:
    task_id: str
    subject: str = ""
    created_by: str = ""
    creator_agent: str = ""
    owner: str = ""
    transitions: list[tuple[str, str, float]] = field(default_factory=list[tuple[str, str, float]])


def _build_tasks(
    events: list[UnifiedEvent],
    topology: Topology,
    offset: Callable[[datetime], float],
) -> tuple[list[TaskView], list[PrivateTodoGroup], list[str]]:
    """Reconstruct task lifecycles, distinguishing two cases:

    - **Shared / team tasks** — a task touched by more than one agent, or one
      that ever gets an `owner`. These are the agent-team coordination story
      and are keyed globally by task id.
    - **Private to-do lists** — a task only its own creator ever touches
      (sub-agent self-organisation). Many agents reuse ids 1, 2, 3…, so these
      are keyed per-agent to avoid bogus merges, then rolled up per agent.
    """
    # Pass 1: which task ids ever carry an owner (the agent-team claim signal).
    has_owner: dict[str, bool] = {}
    for e in events:
        if e.type == EventType.TASK_UPDATE and str(e.data.get("owner", "")):
            tid = str(e.data.get("task_id", ""))
            if tid:
                has_owner[tid] = True

    # Shared vs private is decided by mode, not by id collisions: in sub-agent
    # mode every agent reuses ids 1,2,3… for its own private to-do list, so a
    # shared-by-id heuristic would wrongly merge them. Owner presence is the
    # real team signal and decides the ambiguous hybrid case.
    def is_shared(tid: str) -> bool:
        if topology.mode == SessionMode.AGENT_TEAM:
            return True
        if topology.mode == SessionMode.SUBAGENT:
            return False
        return has_owner.get(tid, False)

    # Pass 2: accumulate per scoped key.
    accs: dict[str, _TaskAcc] = {}

    def key(tid: str, agent: str) -> str:
        return tid if is_shared(tid) else f"{canonical_id(agent)}␟{tid}"

    for e in events:
        if e.type == EventType.TASK_CREATE:
            tid = str(e.data.get("task_id", ""))
            if not tid:
                continue
            k = key(tid, e.agent_id)
            acc = accs.setdefault(k, _TaskAcc(task_id=tid))
            acc.subject = str(e.data.get("subject", "")) or acc.subject
            acc.created_by = topology.label(e.agent_id)
            acc.creator_agent = canonical_id(e.agent_id)
            acc.transitions.append(("pending", topology.label(e.agent_id), offset(e.timestamp)))
        elif e.type == EventType.TASK_UPDATE:
            tid = str(e.data.get("task_id", ""))
            if not tid:
                continue
            k = key(tid, e.agent_id)
            acc = accs.setdefault(k, _TaskAcc(task_id=tid))
            owner = str(e.data.get("owner", ""))
            if owner:
                acc.owner = topology.label(owner)
            # Attribute an update-only task (create not captured) to the agent
            # touching it — in sub-agent mode the updater is also the creator.
            if not acc.creator_agent:
                acc.creator_agent = canonical_id(e.agent_id)
                acc.created_by = topology.label(e.agent_id)
            status = str(e.data.get("new_status", "")) or "updated"
            acc.transitions.append((status, topology.label(e.agent_id), offset(e.timestamp)))

    shared_tasks: list[TaskView] = []
    private_groups: dict[str, list[str]] = {}  # owner_label -> [final_status,...]
    anomalies: list[str] = []

    for k, acc in accs.items():
        final = acc.transitions[-1][0] if acc.transitions else "unknown"
        if is_shared(acc.task_id):
            shared_tasks.append(TaskView(
                task_id=acc.task_id,
                subject=acc.subject,
                created_by=acc.created_by,
                owner=acc.owner,
                transitions=acc.transitions,
                final_status=final,
            ))
            has_create = any(s == "pending" for s, _, _ in acc.transitions)
            if not has_create:
                anomalies.append(f"Shared task #{acc.task_id} has updates but no create event")
            elif final == "in_progress":
                anomalies.append(f"Shared task #{acc.task_id} ended in_progress without completion")
        else:
            label = acc.created_by or topology.label(acc.creator_agent)
            private_groups.setdefault(label, []).append(final)

    shared_tasks.sort(key=lambda t: _task_sort_key(t.task_id))

    private_todos: list[PrivateTodoGroup] = []
    for label, finals in sorted(private_groups.items(), key=lambda kv: -len(kv[1])):
        completed = sum(1 for s in finals if s == "completed")
        in_progress = sum(1 for s in finals if s == "in_progress")
        private_todos.append(PrivateTodoGroup(
            owner_label=label,
            total=len(finals),
            completed=completed,
            in_progress=in_progress,
            other=len(finals) - completed - in_progress,
        ))

    return shared_tasks, private_todos, anomalies


def session_summary(events: list[UnifiedEvent], view: SessionView | None = None) -> str:
    """Render a session-anatomy report in Markdown that reveals the mechanism.

    Pass a prebuilt `view` to avoid rebuilding the topology when the caller
    already has one.
    """
    if view is None:
        view = build_session_view(events)
    topo = view.topology
    mode = topo.mode
    lines: list[str] = []

    lines.append(f"# Session Analysis — {_MODE_TITLE[mode]} mode")
    lines.append("")
    c = view.counts
    if view.phases:
        # Workflow runs have no peer messages or spawn events; lead with the
        # structure that actually matters (agents / phases / tokens).
        wf = view.workflow or {}
        total_tokens = int(wf.get("total_tokens", 0) or 0)
        lines.append(
            f"**{c['agents']} agents · {len(view.phases)} phases · "
            f"{total_tokens:,} tokens · {c['events']} events · {humantime(view.duration_s)}**"
        )
    else:
        lines.append(
            f"**{c['agents']} agents · {c['spawns']} spawns · {c['messages']} messages · "
            f"{c['tasks']} tasks · {c['events']} events · {humantime(view.duration_s)}**"
        )
    lines.append("")

    if topo.mode_signals:
        lines.append("Mode detected from:")
        for sig in topo.mode_signals:
            lines.append(f"- {sig}")
        lines.append("")

    lines.append("## How this mode works")
    lines.append("")
    lines.append(_MODE_PRIMER[mode])
    lines.append("")

    # Phases — the structural spine of a Workflow run (analog of the task board).
    if view.phases:
        wf = view.workflow or {}
        lines.append(f"## Phases ({len(view.phases)})")
        lines.append("")
        head_bits: list[str] = []
        if wf.get("name"):
            head_bits.append(f"workflow `{wf['name']}`")
        if wf.get("status"):
            head_bits.append(f"status: {wf['status']}")
        if wf.get("model"):
            head_bits.append(f"model: `{wf['model']}`")
        if head_bits:
            lines.append(" · ".join(head_bits))
            lines.append("")
        lines.append("| # | Phase | Agents | Tokens | Tool calls | Duration |")
        lines.append("|---|---|---|---|---|---|")
        for ph in view.phases:
            lines.append(
                f"| {ph.index} | {_md(ph.title)} | {ph.agents} | {ph.tokens:,} "
                f"| {ph.tool_calls} | {humantime(ph.duration_s)} |"
            )
        lines.append("")

    # Cast --------------------------------------------------------------
    lines.append(f"## Cast — who is who ({len(view.agents)} agents)")
    lines.append("")
    lines.append("| Agent | Role | Type | Spawned by | Events | Tokens in/out |")
    lines.append("|---|---|---|---|---|---|")
    for p in view.agents:
        spawned_by = topo.label(p.spawned_by) if p.spawned_by else "—"
        atype = p.agent_type or "—"
        lines.append(
            f"| {_md(p.display_name)} | {p.role.value} | {atype} | {_md(spawned_by)} "
            f"| {p.event_count} | {p.tokens_in:,}/{p.tokens_out:,} |"
        )
    lines.append("")

    # Delegation tree ---------------------------------------------------
    if topo.spawn_children:
        # Real roots (main/UUID sessions) anchor the tree; hex blobs that ended
        # up unspawned are sub-agents whose spawn link was not recorded.
        session_roots = [r for r in topo.roots
                         if (p := topo.profiles.get(r)) and p.role == AgentRole.ROOT]
        orphans = [r for r in topo.roots if r not in set(session_roots)]
        lines.append("## Delegation tree (who spawned whom)")
        lines.append("")
        lines.append("```")
        for root in session_roots:
            lines.extend(_render_tree(root, topo, prefix="", is_last=True, is_root=True))
        lines.append("```")
        lines.append("")
        if orphans:
            lines.append(
                f"_{len(orphans)} sub-agents appear without a recorded parent "
                f"(their spawn link was not captured); shown as roots of their own subtrees:_"
            )
            lines.append("")
            lines.append("```")
            for o in orphans:
                lines.extend(_render_tree(o, topo, prefix="", is_last=True, is_root=True))
            lines.append("```")
            lines.append("")

    # Shared task board -------------------------------------------------
    if view.tasks:
        lines.append(f"## Shared task board ({len(view.tasks)} team tasks)")
        lines.append("")
        for t in view.tasks:
            head = f"**#{t.task_id} {t.subject or '(no subject)'}**"
            meta_bits: list[str] = []
            if t.created_by:
                meta_bits.append(f"created by {t.created_by}")
            meta_bits.append(f"owner: {t.owner}" if t.owner else "unclaimed")
            lines.append(f"- {head} — {', '.join(meta_bits)}")
            path = " → ".join(
                f"{status} ({actor}, {_fmt_offset(off)})" for status, actor, off in t.transitions
            )
            lines.append(f"  - {path}")
        lines.append("")
        if view.anomalies:
            lines.append("**Anomalies:**")
            for a in view.anomalies:
                lines.append(f"- ⚠ {a}")
            lines.append("")

    # Private to-do lists (sub-agent self-organisation) -----------------
    if view.private_todos:
        total = sum(g.total for g in view.private_todos)
        lines.append(f"## Private to-do lists ({total} todos across {len(view.private_todos)} agents)")
        lines.append("")
        lines.append(
            "Each agent keeps its own private list (ids restart at 1 per agent), "
            "so these are rolled up rather than merged."
        )
        lines.append("")
        lines.append("| Agent | Todos | Completed | In progress | Other |")
        lines.append("|---|---|---|---|---|")
        for g in view.private_todos:
            lines.append(
                f"| {_md(g.owner_label)} | {g.total} | {g.completed} | {g.in_progress} | {g.other} |"
            )
        lines.append("")

    # Communication log -------------------------------------------------
    if view.messages:
        lines.append(f"## Communication log ({len(view.messages)} messages)")
        lines.append("")
        for m in view.messages:
            summary = m.summary[:160] + ("…" if len(m.summary) > 160 else "")
            lines.append(
                f"- `{_fmt_offset(m.offset_s)}` **{m.from_label} → {m.to_label}** "
                f"[{m.message_type}]: {summary}"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _render_tree(
    node: str, topo: Topology, prefix: str, is_last: bool, is_root: bool,
    visited: set[str] | None = None,
) -> list[str]:
    visited = visited if visited is not None else set()
    profile = topo.profiles.get(node)
    label = profile.display_name if profile else node
    role = profile.role if profile else None
    # Sub-agent labels already carry their type in brackets, so only annotate
    # the role for the others (root / lead / teammate).
    suffix = f"  [{role.value}]" if role and role != AgentRole.SUBAGENT else ""
    # Guard against cycles / a child reachable from two parents in malformed data.
    if node in visited:
        line = f"{label}{suffix} (already shown)"
        return [line] if is_root else [f"{prefix}{'└─ ' if is_last else '├─ '}{line}"]
    visited.add(node)
    if is_root:
        out = [f"{label}{suffix}"]
        child_prefix = ""
    else:
        connector = "└─ " if is_last else "├─ "
        out = [f"{prefix}{connector}{label}{suffix}"]
        child_prefix = prefix + ("   " if is_last else "│  ")
    children = topo.spawn_children.get(node, [])
    for i, child in enumerate(children):
        out.extend(_render_tree(
            child, topo, child_prefix, i == len(children) - 1, is_root=False, visited=visited
        ))
    return out


def _md(text: str) -> str:
    """Escape pipe characters so table cells don't break."""
    return text.replace("|", "\\|")


def humantime(seconds: float) -> str:
    """Seconds → human-readable duration, e.g. 44487 → '12h 21m', 1617 → '27m 0s', 45 → '45s'."""
    s = round(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _fmt_offset(seconds: float) -> str:
    """A time offset from session start, e.g. 1617 → '+27m 0s'."""
    return "+" + humantime(seconds)


def build_agent_outputs(events: list[UnifiedEvent], topology: Topology) -> list[AgentOutput]:
    """Collect each agent's complete, untruncated text output, time-ordered."""
    t0 = events[0].timestamp if events else None

    def offset(ts: datetime) -> float:
        return (ts - t0).total_seconds() if t0 else 0.0

    by_agent: dict[str, list[tuple[float, str, str]]] = {}
    for e in events:
        if e.type != EventType.AGENT_MESSAGE:
            continue
        text = str(e.data.get("text", "") or e.data.get("content_summary", ""))
        if not text.strip():
            continue
        # Harness-injected turns (slash-command / skill expansions, system
        # reminders) carry isMeta — they read like user turns but are neither
        # the parent's instruction nor the agent's own output, so label them
        # distinctly instead of "user".
        role = "injected" if e.data.get("is_meta") else str(e.data.get("role", ""))
        cid = canonical_id(e.agent_id)
        by_agent.setdefault(cid, []).append((offset(e.timestamp), role, text))

    outputs: list[AgentOutput] = []
    for cid, msgs in by_agent.items():
        p = topology.profiles.get(cid)
        role = p.role if p else AgentRole.UNKNOWN
        outputs.append(AgentOutput(
            agent_id=cid,
            label=p.display_name if p else cid,
            role=role.value,
            messages=sorted(msgs, key=lambda m: m[0]),
        ))
    outputs.sort(key=lambda o: (_ROLE_ORDER.get(AgentRole(o.role), 9), o.label))
    return outputs


def agent_output_markdown(o: AgentOutput) -> str:
    """Render one agent's complete output as a standalone Markdown transcript."""
    lines = [
        f"# {o.label}",
        "",
        f"- **Role:** {o.role}",
        f"- **Agent id:** `{o.agent_id}`",
        f"- **Messages:** {len(o.messages)}",
        "",
        "---",
        "",
    ]
    for off, role, text in o.messages:
        lines.append(f"## `{_fmt_offset(off)}` · {role}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines) + "\n"


def outputs_to_dicts(outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    """Flatten agent outputs for the HTML panel (keyed lookup happens in JS)."""
    return [
        {
            "id": o.agent_id,
            "label": o.label,
            "role": o.role,
            "messages": [
                {"offset_s": off, "role": role, "text": text}
                for off, role, text in o.messages
            ],
        }
        for o in outputs
    ]


def view_to_dict(view: SessionView) -> dict[str, Any]:
    """Flatten a SessionView into JSON-serialisable data for the HTML template."""
    topo = view.topology
    return {
        "mode": topo.mode.value,
        "mode_title": _MODE_TITLE[topo.mode],
        "mode_primer": _MODE_PRIMER[topo.mode],
        "mode_signals": list(topo.mode_signals),
        "counts": view.counts,
        "duration_s": view.duration_s,
        "workflow": view.workflow,
        "phases": [
            {
                "index": ph.index,
                "title": ph.title,
                "agents": ph.agents,
                "tokens": ph.tokens,
                "tool_calls": ph.tool_calls,
                "duration_s": ph.duration_s,
            }
            for ph in view.phases
        ],
        "agents": [
            {
                "id": p.agent_id,
                "role": p.role.value,
                "label": p.display_name,
                "agent_type": p.agent_type,
                "spawned_by": p.spawned_by,
                "spawned_by_label": topo.label(p.spawned_by) if p.spawned_by else "",
                "events": p.event_count,
                "tokens_in": p.tokens_in,
                "tokens_out": p.tokens_out,
            }
            for p in view.agents
        ],
        "spawn_children": {k: list(v) for k, v in topo.spawn_children.items()},
        "roots": list(topo.roots),
        "tasks": [
            {
                "id": t.task_id,
                "subject": t.subject,
                "created_by": t.created_by,
                "owner": t.owner,
                "final_status": t.final_status,
                "transitions": [
                    {"status": s, "actor": a, "offset_s": o} for s, a, o in t.transitions
                ],
            }
            for t in view.tasks
        ],
        "private_todos": [
            {
                "owner": g.owner_label,
                "total": g.total,
                "completed": g.completed,
                "in_progress": g.in_progress,
                "other": g.other,
            }
            for g in view.private_todos
        ],
        "anomalies": list(view.anomalies),
        "messages": [
            {
                "offset_s": m.offset_s,
                "from": m.from_label,
                "to": m.to_label,
                "type": m.message_type,
                "summary": m.summary,
            }
            for m in view.messages
        ],
    }
