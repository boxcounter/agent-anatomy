"""Tests for error handling."""

from agent_anatomy.errors import (
    AnalysisToolError,
    ParseError,
    RawDataNotFoundError,
    SessionNotFoundError,
    TemplateNotFoundError,
    WatchTargetNotFoundError,
)


def test_session_not_found_error():
    err = SessionNotFoundError("abc-123")
    assert err.session_id == "abc-123"
    assert "abc-123" in str(err)
    assert isinstance(err, AnalysisToolError)


def test_raw_data_not_found_error():
    err = RawDataNotFoundError("/some/path")
    assert err.path == "/some/path"
    assert "/some/path" in str(err)


def test_parse_error_with_detail():
    err = ParseError("test.jsonl", "invalid JSON on line 5")
    assert err.path == "test.jsonl"
    assert "invalid JSON on line 5" in str(err)


def test_parse_error_without_detail():
    err = ParseError("test.jsonl")
    assert err.detail == ""
    assert "test.jsonl" in str(err)


def test_watch_target_not_found_error():
    err = WatchTargetNotFoundError("my-team")
    assert err.team_name == "my-team"
    assert "my-team" in str(err)


def test_template_not_found_error():
    err = TemplateNotFoundError("timeline.html.j2")
    assert err.template_name == "timeline.html.j2"
    assert "timeline.html.j2" in str(err)


def test_all_errors_are_user_friendly():
    """All error messages should be single-line and not contain traceback artifacts."""
    errors: list[AnalysisToolError] = [
        SessionNotFoundError("sid-1"),
        RawDataNotFoundError("/tmp/raw"),
        ParseError("data.jsonl", "bad JSON"),
        WatchTargetNotFoundError("team-x"),
        TemplateNotFoundError("missing.j2"),
    ]
    for err in errors:
        msg = str(err)
        assert "\n" not in msg, f"Multi-line error message: {msg}"
        assert "Traceback" not in msg
        assert len(msg) > 0
