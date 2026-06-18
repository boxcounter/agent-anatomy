from pathlib import Path

from analysis_tool.models import EventSource, EventType
from analysis_tool.parser import parse_jsonl, parse_raw_dir


def test_parse_session_jsonl_yields_agent_spawn(fixtures_dir: Path):
    events = parse_jsonl(fixtures_dir / "session.jsonl")
    spawns = [e for e in events if e.type == EventType.AGENT_SPAWN]
    assert len(spawns) == 1
    spawn = spawns[0]
    assert spawn.source == EventSource.TRANSCRIPT
    assert spawn.agent_id == "main"
    assert spawn.data["child_agent_id"] == ""
    assert spawn.data["tool_use_id"] == "call_00_abc123"
    assert spawn.data["agent_type"] == "general-purpose"


def test_parse_subagent_jsonl_yields_agent_message(fixtures_dir: Path):
    events = parse_jsonl(fixtures_dir / "subagents" / "agent-a0.jsonl")
    msgs = [e for e in events if e.type == EventType.AGENT_MESSAGE]
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.agent_id == "agent-a0"
    assert msg.source == EventSource.TRANSCRIPT
    assert msg.data["role"] == "assistant"
    assert msg.data["content_summary"] == "I am a sub-agent response"
    assert msg.parent_id is not None


def test_parse_jsonl_extracts_task_id_from_tool_result(fixtures_dir: Path):
    events = parse_jsonl(fixtures_dir / "session-tasks.jsonl")
    creates = [e for e in events if e.type == EventType.TASK_CREATE]
    assert len(creates) == 1
    assert creates[0].data["task_id"] == "1"
    assert creates[0].data["subject"] == "test task"
    assert creates[0].data["tool_use_id"] == "call_create_1"


def test_parse_raw_dir_links_spawn_to_sidechain(fixtures_dir: Path):
    events = parse_raw_dir(fixtures_dir)

    spawns = [e for e in events if e.type == EventType.AGENT_SPAWN]
    assert len(spawns) == 1
    spawn = spawns[0]
    # After association, child_agent_id should be populated
    assert spawn.data["child_agent_id"] != ""
    assert "agent-a0" in spawn.data["child_agent_id"]

    # Verify sidechain messages exist and reference the spawn
    sidechain_msgs = [
        e for e in events
        if e.type == EventType.AGENT_MESSAGE and e.agent_id == "agent-a0"
    ]
    assert len(sidechain_msgs) >= 1
