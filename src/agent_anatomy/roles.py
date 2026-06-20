# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Agent identity & topology model.

This is the keystone the human-facing artifacts (report, graph, timeline) all
consume. It turns a flat event stream into an answer to four questions:

  - Who is the lead / a teammate / a one-shot subagent?
  - What is the spawn (delegation) tree?
  - Which collaboration mode is this — Subagent, Agent Team, or Hybrid?
  - ...with the evidence used to decide, so a reader can audit the call.

Normalization note: a spawned agent appears twice in the data with two ids —
the parent records `child_agent_id = "agent-<hash>"`, while the child's own
events carry `agentId = "<hash>"` (no prefix). We canonicalize by stripping a
leading "agent-" so both resolve to the same profile.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from agent_anatomy.models import EventType, UnifiedEvent

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class AgentRole(Enum):
    LEAD = "lead"
    TEAMMATE = "teammate"
    SUBAGENT = "subagent"
    ROOT = "root"
    PHASE = "phase"  # synthetic grouping node in a Workflow run (Scope/Search/…)
    UNKNOWN = "unknown"


class SessionMode(Enum):
    SUBAGENT = "subagent"
    AGENT_TEAM = "agent_team"
    WORKFLOW = "workflow"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str  # canonical id (no "agent-" prefix)
    role: AgentRole
    display_name: str
    agent_type: str
    spawned_by: str | None
    description: str
    first_seen: datetime | None
    last_seen: datetime | None
    event_count: int
    tokens_in: int
    tokens_out: int


@dataclass
class Topology:
    profiles: dict[str, AgentProfile] = field(default_factory=dict)
    spawn_children: dict[str, list[str]] = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    mode: SessionMode = SessionMode.UNKNOWN
    mode_signals: list[str] = field(default_factory=list)

    def profile(self, agent_id: str) -> AgentProfile | None:
        return self.profiles.get(canonical_id(agent_id))

    def label(self, agent_id: str) -> str:
        p = self.profile(agent_id)
        if p:
            return p.display_name
        cid = canonical_id(agent_id)
        # An unprofiled name (e.g. a task owner with no events) is still
        # readable — only shorten ids that look like hashes/UUIDs.
        return _short(cid) if _looks_like_hash(cid) else cid


def canonical_id(agent_id: str) -> str:
    """Strip the "agent-" prefix so parent/child references resolve equally."""
    return agent_id[len("agent-"):] if agent_id.startswith("agent-") else agent_id


def _short(agent_id: str) -> str:
    return agent_id[:8]


def _looks_like_hash(agent_id: str) -> bool:
    """Hex-ish blob (subagent) or UUID — i.e. not a human-chosen name."""
    stripped = agent_id.replace("-", "")
    return len(stripped) >= 16 and all(c in "0123456789abcdefABCDEF" for c in stripped)


def _is_session_root_id(agent_id: str) -> bool:
    """A genuine root is the literal "main" or a UUID session id — never a
    bare `agent-<hex>` blob (those are sub-agents whose spawn link was lost)."""
    return agent_id == "main" or bool(_UUID_RE.match(agent_id))


@dataclass
class _Acc:
    """Mutable per-agent accumulator, frozen into an AgentProfile at the end."""
    agent_id: str
    agent_type: str = ""
    spawned_by: str | None = None
    description: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    event_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def _config_roles(team_config: Mapping[str, object] | None) -> dict[str, AgentRole]:
    """Authoritative role map from a team's config.json (canonical-id keyed).

    The config names the lead (`leadAgentId`/`leadSessionId`) and every member
    (`agentType` of "team-lead" vs anything else). We key by every identity an
    event might use — the agentId, the member name, the lead session id — so a
    transcript that refers to a teammate by name still resolves authoritatively.
    """
    roles: dict[str, AgentRole] = {}
    if not team_config:
        return roles
    for key in ("leadAgentId", "leadSessionId"):
        val = team_config.get(key)
        if isinstance(val, str) and val:
            roles[canonical_id(val)] = AgentRole.LEAD
    members = team_config.get("members", [])
    if isinstance(members, list):
        for m in members:  # type: ignore[reportUnknownVariableType]
            if not isinstance(m, dict):
                continue
            role = AgentRole.LEAD if m.get("agentType") == "team-lead" else AgentRole.TEAMMATE
            for field_name in ("agentId", "name"):
                ident = m.get(field_name)
                if isinstance(ident, str) and ident:
                    roles[canonical_id(ident)] = role
    return roles


def _workflow_agents(
    journals: list[Mapping[str, object]] | None,
) -> list[tuple[int, str, str, str]]:
    """Flatten Workflow journals into (phase_index, phase_title, agent_cid, label).

    Reads each journal's `workflowProgress` array, keeping only `workflow_agent`
    entries. Ordered by phase index then queue order so phases render in run order.
    """
    out: list[tuple[int, str, str, str]] = []
    for journal in journals or []:
        progress = journal.get("workflowProgress", [])
        if not isinstance(progress, list):
            continue
        for entry in progress:  # type: ignore[reportUnknownVariableType]
            if not isinstance(entry, dict) or entry.get("type") != "workflow_agent":
                continue
            agent_id = entry.get("agentId")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            phase_idx = entry.get("phaseIndex", 0)
            phase_title = entry.get("phaseTitle", "") or "(phase)"
            label = entry.get("label", "") or ""
            out.append((
                int(phase_idx) if isinstance(phase_idx, int) else 0,
                str(phase_title),
                canonical_id(agent_id),
                str(label),
            ))
    out.sort(key=lambda t: (t[0], t[2]))
    return out


def build_topology(
    events: list[UnifiedEvent],
    team_config: Mapping[str, object] | None = None,
    workflow_journals: list[Mapping[str, object]] | None = None,
) -> Topology:
    """Infer per-agent roles, the spawn tree, and the session mode from events.

    When a team `config.json` is supplied its roles are authoritative and
    override the heuristics — it is ground truth for who the lead and teammates
    are. Likewise, when Workflow run journals are supplied they are authoritative
    for a Workflow-mode run: the orchestrator (root) fans out one-shot agents
    grouped into phases, reconstructed as a `root → phase → agent` tree. Without
    either, roles are inferred from spawn/message/task evidence.
    """
    config_roles = _config_roles(team_config)
    accs: dict[str, _Acc] = {}

    def acc(agent_id: str) -> _Acc:
        cid = canonical_id(agent_id)
        if cid not in accs:
            accs[cid] = _Acc(agent_id=cid)
        return accs[cid]

    spawn_children: dict[str, list[str]] = {}
    # readable label hints seen in message `to`/`from` and task `owner`
    name_hints: set[str] = set()
    teammate_ids: set[str] = set()
    lead_ids: set[str] = set()

    has_task_assignment = False
    has_owner = False
    has_named_member = False
    spawn_count = 0

    for e in events:
        a = acc(e.agent_id)
        a.event_count += 1
        if a.first_seen is None:
            a.first_seen = e.timestamp
        a.last_seen = e.timestamp

        if "@" in e.agent_id or "team-lead" in e.agent_id:
            has_named_member = True
            lead_ids.add(canonical_id(e.agent_id))

        if e.type == EventType.AGENT_MESSAGE:
            usage = e.data.get("token_usage", {})
            if isinstance(usage, dict):
                a.tokens_in += int(usage.get("input_tokens", 0) or 0)
                a.tokens_out += int(usage.get("output_tokens", 0) or 0)

        elif e.type == EventType.AGENT_SPAWN:
            child = e.data.get("child_agent_id", "")
            if child:
                spawn_count += 1
                ccid = canonical_id(child)
                parent = canonical_id(e.agent_id)
                spawn_children.setdefault(parent, [])
                if ccid not in spawn_children[parent]:
                    spawn_children[parent].append(ccid)
                ca = acc(child)
                ca.spawned_by = parent
                ca.agent_type = str(e.data.get("agent_type", "") or ca.agent_type)
                ca.description = str(e.data.get("description", "") or ca.description)

        elif e.type == EventType.MESSAGE_SEND:
            sender = str(e.data.get("from", "") or e.agent_id)
            recipient = str(e.data.get("to", ""))
            mtype = str(e.data.get("message_type", "message"))
            for who in (sender, recipient):
                if who and not _looks_like_hash(who):
                    name_hints.add(who)
            if mtype == "task_assignment":
                has_task_assignment = True
                if recipient:
                    teammate_ids.add(canonical_id(recipient))
                if sender:
                    lead_ids.add(canonical_id(sender))

        elif e.type == EventType.TASK_UPDATE:
            owner = str(e.data.get("owner", ""))
            if owner:
                has_owner = True
                teammate_ids.add(canonical_id(owner))
                name_hints.add(owner)

    # ---- Workflow journal: rebuild the orchestrator → phase → agent tree ----
    # The journal is authoritative (like team config.json). Workflow agents are
    # one-shot and carry no spawn events, so the tree is synthesized here: the
    # orchestrator (the session root) fans out to one synthetic node per phase,
    # and each phase fans out to its agents.
    wf_agents = _workflow_agents(workflow_journals)
    phase_ids: set[str] = set()
    if wf_agents:
        # Orchestrator = the genuine session root among the accumulated agents
        # (the main UUID/"main" session that invoked the Workflow tool).
        root_candidates = sorted(
            (cid for cid in accs if _is_session_root_id(cid)),
            key=lambda c: accs[c].first_seen or datetime.max,
        )
        orchestrator = root_candidates[0] if root_candidates else "orchestrator"
        acc(orchestrator)  # ensure a profile exists even if it had no events

        # Group agents by phase, preserving first-seen phase order.
        phase_order: list[str] = []
        phase_members: dict[str, list[str]] = {}
        for _idx, title, agent_cid, label in wf_agents:
            if title not in phase_members:
                phase_members[title] = []
                phase_order.append(title)
            phase_members[title].append(agent_cid)
            ag = acc(agent_cid)
            ag.agent_type = title
            ag.description = label or ag.description

        for title in phase_order:
            phase_id = f"phase:{title}"
            phase_ids.add(phase_id)
            members = phase_members[title]
            pa = acc(phase_id)
            pa.agent_type = "phase"
            pa.description = f"{title} ({len(members)} agent{'s' if len(members) != 1 else ''})"
            spawn_children.setdefault(orchestrator, [])
            if phase_id not in spawn_children[orchestrator]:
                spawn_children[orchestrator].append(phase_id)
            kids = spawn_children.setdefault(phase_id, [])
            for agent_cid in members:
                if agent_cid not in kids:
                    kids.append(agent_cid)
                acc(agent_cid).spawned_by = phase_id

    # roots: agents that were never spawned by anyone
    spawned: set[str] = {c for kids in spawn_children.values() for c in kids}
    all_ids = set(accs)
    roots = sorted(all_ids - spawned)

    # ---- mode detection -------------------------------------------------
    team_signals: list[str] = []
    if has_named_member:
        team_signals.append("named team members (id contains '@' / 'team-lead')")
    if has_task_assignment:
        team_signals.append("task_assignment messages between agents")
    if has_owner:
        team_signals.append("tasks claimed via owner field")
    if config_roles:
        team_signals.insert(0, "team config.json (authoritative member list)")
    sub_signals: list[str] = []
    if spawn_count:
        sub_signals.append(f"{spawn_count} Agent-tool spawns (agent-<hash> children + sidechains)")
    workflow_signals: list[str] = []
    if wf_agents:
        names = sorted({
            str(j.get("workflowName", "")) for j in (workflow_journals or [])
            if j.get("workflowName")
        })
        wf_name = f" '{', '.join(names)}'" if names else ""
        workflow_signals.append(
            f"Workflow run journal{wf_name} ({len(wf_agents)} agents across "
            f"{len(phase_ids)} phases)"
        )

    has_team = bool(team_signals)
    has_sub = bool(sub_signals)
    has_workflow = bool(workflow_signals)
    if has_workflow:
        # A workflow may itself contain team coordination, but in practice the
        # journal is the dominant structure; flag hybrid only if team signals exist.
        mode = SessionMode.HYBRID if has_team else SessionMode.WORKFLOW
    elif has_team and has_sub:
        mode = SessionMode.HYBRID
    elif has_team:
        mode = SessionMode.AGENT_TEAM
    elif has_sub:
        mode = SessionMode.SUBAGENT
    else:
        mode = SessionMode.UNKNOWN
    mode_signals = workflow_signals + team_signals + sub_signals

    # ---- role assignment ------------------------------------------------
    # Synthetic phase nodes get the PHASE role; everything else is classified.
    forced_roles = dict(config_roles)
    for pid in phase_ids:
        forced_roles[pid] = AgentRole.PHASE

    profiles: dict[str, AgentProfile] = {}
    for cid, a in accs.items():
        role = _classify(cid, a, lead_ids, teammate_ids, roots, forced_roles)
        profiles[cid] = AgentProfile(
            agent_id=cid,
            role=role,
            display_name=_display_name(cid, role, a),
            agent_type=a.agent_type,
            spawned_by=a.spawned_by,
            description=a.description,
            first_seen=a.first_seen,
            last_seen=a.last_seen,
            event_count=a.event_count,
            tokens_in=a.tokens_in,
            tokens_out=a.tokens_out,
        )

    return Topology(
        profiles=profiles,
        spawn_children=spawn_children,
        roots=roots,
        mode=mode,
        mode_signals=mode_signals,
    )


def _classify(
    cid: str,
    a: _Acc,
    lead_ids: set[str],
    teammate_ids: set[str],
    roots: list[str],
    config_roles: dict[str, AgentRole],
) -> AgentRole:
    # config.json is ground truth and wins over every heuristic.
    if cid in config_roles:
        return config_roles[cid]
    # A lead can also spawn helpers, so check lead first.
    if cid in lead_ids:
        return AgentRole.LEAD
    # A named agent that receives task_assignment or owns tasks is a teammate
    # even if it was spawned via the Agent tool (teammates are "spawned" too) —
    # so teammate evidence wins over the bare spawned_by signal.
    if cid in teammate_ids:
        return AgentRole.TEAMMATE
    if a.spawned_by is not None:
        return AgentRole.SUBAGENT
    if cid in roots:
        if _is_session_root_id(cid):
            return AgentRole.ROOT
        # Unspawned hex blob = a sub-agent whose spawn link was lost in the data.
        if _looks_like_hash(cid):
            return AgentRole.SUBAGENT
        return AgentRole.UNKNOWN
    return AgentRole.UNKNOWN


def _display_name(cid: str, role: AgentRole, a: _Acc) -> str:
    if role == AgentRole.LEAD:
        return cid.split("@")[0] if "@" in cid else cid
    if role == AgentRole.TEAMMATE:
        return cid
    if role == AgentRole.SUBAGENT:
        atype = a.agent_type or "subagent"
        desc = a.description.strip()
        if desc:
            if len(desc) > 48:
                desc = desc[:47] + "…"
            return f"[{atype}] {desc}"
        return f"[{atype}] {_short(cid)}"
    if role == AgentRole.PHASE:
        # description was set to "<Title> (<n> agents)" when the node was built.
        return a.description or cid.split(":", 1)[-1]
    if role == AgentRole.ROOT:
        return f"main session ({_short(cid)})"
    return _short(cid)
