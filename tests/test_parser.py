from pathlib import Path

from analysis_tool.models import EventSource, EventType
from analysis_tool.parser import parse_jsonl


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
