from datetime import UTC, datetime

from agent_anatomy.models import EventSource, EventType, UnifiedEvent
from agent_anatomy.roles import AgentRole, SessionMode, build_topology, canonical_id


def _ev(agent_id: str, etype: EventType, data: dict[str, object], sec: int = 0) -> UnifiedEvent:
    return UnifiedEvent.create(
        timestamp=datetime(2026, 6, 18, 12, 0, sec, tzinfo=UTC),
        agent_id=agent_id,
        source=EventSource.TRANSCRIPT,
        type=etype,
        data=data,
    )


def test_canonical_id_strips_agent_prefix():
    assert canonical_id("agent-a0c3") == "a0c3"
    assert canonical_id("main") == "main"
    assert canonical_id("team-lead@s") == "team-lead@s"


def test_subagent_mode_builds_spawn_tree():
    events = [
        _ev("main", EventType.AGENT_SPAWN,
            {"child_agent_id": "agent-a0", "agent_type": "Explore", "description": "scan the repo"}, 0),
        _ev("a0", EventType.AGENT_MESSAGE,
            {"role": "assistant", "content_summary": "done",
             "token_usage": {"input_tokens": 10, "output_tokens": 5}}, 1),
    ]
    topo = build_topology(events)

    assert topo.mode == SessionMode.SUBAGENT
    # parent/child resolve across the "agent-" prefix mismatch
    assert topo.spawn_children == {"main": ["a0"]}
    assert topo.profiles["main"].role == AgentRole.ROOT
    assert topo.profiles["a0"].role == AgentRole.SUBAGENT
    # subagent is labelled by its task, not a hash
    assert "scan the repo" in topo.profiles["a0"].display_name
    assert topo.profiles["a0"].spawned_by == "main"
    assert topo.profiles["a0"].tokens_in == 10


def test_agent_team_mode_detects_lead_and_teammate():
    events = [
        _ev("team-lead@team1", EventType.TASK_CREATE, {"task_id": "1", "subject": "investigate"}, 0),
        _ev("team-lead@team1", EventType.MESSAGE_SEND,
            {"from": "team-lead", "to": "Bet-2-Investigator", "summary": "go", "message_type": "task_assignment"}, 1),
        _ev("Bet-2-Investigator", EventType.TASK_UPDATE,
            {"task_id": "1", "new_status": "in_progress", "owner": "Bet-2-Investigator"}, 2),
    ]
    topo = build_topology(events)

    assert topo.mode == SessionMode.AGENT_TEAM
    assert topo.profiles["team-lead@team1"].role == AgentRole.LEAD
    assert topo.profiles["Bet-2-Investigator"].role == AgentRole.TEAMMATE
    # teammate name is preserved, not truncated to a hash
    assert topo.profiles["Bet-2-Investigator"].display_name == "Bet-2-Investigator"
    assert any("task_assignment" in s for s in topo.mode_signals)


def test_spawned_teammate_classified_as_teammate_not_subagent():
    # An agent that was spawned AND receives a task_assignment is a teammate —
    # teammate evidence must win over the bare spawned_by signal.
    events = [
        _ev("team-lead@t", EventType.AGENT_SPAWN,
            {"child_agent_id": "agent-mate", "agent_type": "general-purpose", "description": "help"}, 0),
        _ev("team-lead@t", EventType.MESSAGE_SEND,
            {"from": "team-lead", "to": "mate", "summary": "go", "message_type": "task_assignment"}, 1),
    ]
    topo = build_topology(events)
    assert topo.profiles["mate"].role == AgentRole.TEAMMATE


def test_config_roles_override_heuristics():
    # config.json is ground truth: a hex-blob spawned agent named as a member
    # is still a teammate.
    events = [
        _ev("main", EventType.AGENT_SPAWN,
            {"child_agent_id": "agent-worker", "agent_type": "general-purpose", "description": "x"}, 0),
    ]
    config = {"members": [{"agentId": "worker", "name": "worker", "agentType": "general-purpose"}]}
    topo = build_topology(events, config)
    assert topo.profiles["worker"].role == AgentRole.TEAMMATE


def test_hybrid_mode_when_team_also_spawns():
    events = [
        _ev("team-lead@t", EventType.MESSAGE_SEND,
            {"from": "team-lead", "to": "mate", "summary": "x", "message_type": "task_assignment"}, 0),
        _ev("team-lead@t", EventType.AGENT_SPAWN,
            {"child_agent_id": "agent-z", "agent_type": "general-purpose", "description": "helper"}, 1),
    ]
    topo = build_topology(events)
    assert topo.mode == SessionMode.HYBRID
