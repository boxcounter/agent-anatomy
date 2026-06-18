from pathlib import Path

import pytest

from analysis_tool.collect import collect_session


def _mock_find_session_dir(path: Path):
    """Create a replacement for find_session_dir that always returns `path`."""
    def _finder(_session_id: str) -> Path:
        return path
    return _finder


def test_collect_session_copies_session_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """collect_session copies the main session JSONL into raw/."""
    # Mock ~/.claude/projects path
    fake_projects = tmp_path / "projects"
    fake_projects.mkdir()
    session_dir = fake_projects / "test-project" / "sid-1234"
    session_dir.mkdir(parents=True)
    (session_dir / "sid-1234.jsonl").write_text('{"test": true}\n')

    subagents_dir = session_dir / "sid-1234" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-x.jsonl").write_text('{"sidechain": true}\n')
    (subagents_dir / "agent-x.meta.json").write_text('{"toolUseId": "call_123"}')

    output_dir = tmp_path / "analysis"

    # Replace find_session_dir to return our mock
    monkeypatch.setattr(
        "analysis_tool.collect.find_session_dir",
        _mock_find_session_dir(session_dir),
    )

    result = collect_session("sid-1234", output_dir)

    assert (result / "raw" / "session.jsonl").exists()
    assert (result / "raw" / "subagents" / "agent-x.jsonl").exists()
    assert (result / "raw" / "subagents" / "agent-x.meta.json").exists()
    content = (result / "raw" / "session.jsonl").read_text()
    assert "test" in content
