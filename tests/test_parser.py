import json
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


def test_parse_jsonl_captures_string_content_message(tmp_path: Path):
    # A turn whose content is a bare string (e.g. a sub-agent's prompt) must be
    # captured, not dropped — it's the instruction the agent was given.
    entry = {
        "type": "user", "timestamp": "2026-06-18T12:00:00.000Z", "agentId": "agent-x",
        "uuid": "x1", "message": {"role": "user", "content": "You are implementing Task 7."},
    }
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps(entry) + "\n")
    events = parse_jsonl(f)
    msgs = [e for e in events if e.type == EventType.AGENT_MESSAGE]
    assert len(msgs) == 1
    assert msgs[0].data["role"] == "user"
    assert msgs[0].data["text"] == "You are implementing Task 7."


def test_parse_raw_dir_links_nested_spawn(tmp_path: Path):
    # A spawns B in session; B spawns C in B's sidechain. The two-phase linker
    # must connect C to B regardless of meta-file ordering.
    raw = tmp_path
    (raw / "session.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": "2026-06-18T12:00:00.000Z", "agentId": "main", "uuid": "m1",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "callB", "name": "Agent",
             "input": {"subagent_type": "general-purpose", "description": "B"}}]},
    }) + "\n")
    sub = raw / "subagents"
    sub.mkdir()
    # B's sidechain contains the spawn of C
    (sub / "agent-B.meta.json").write_text(json.dumps({"toolUseId": "callB", "agentType": "general-purpose"}))
    (sub / "agent-B.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": "2026-06-18T12:00:01.000Z", "agentId": "B", "uuid": "b1",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "callC", "name": "Agent",
             "input": {"subagent_type": "Explore", "description": "C"}}]},
    }) + "\n")
    (sub / "agent-C.meta.json").write_text(json.dumps({"toolUseId": "callC", "agentType": "Explore"}))
    (sub / "agent-C.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": "2026-06-18T12:00:02.000Z", "agentId": "C", "uuid": "c1",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    }) + "\n")

    events = parse_raw_dir(raw)
    spawns = {e.data.get("tool_use_id"): e.data.get("child_agent_id") for e in events
              if e.type == EventType.AGENT_SPAWN}
    assert spawns["callB"] == "agent-B"
    assert spawns["callC"] == "agent-C"  # nested spawn linked despite ordering
