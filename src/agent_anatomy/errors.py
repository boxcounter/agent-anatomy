"""Typed exception hierarchy for the analysis tool."""


class AnalysisToolError(Exception):
    """Base exception for all tool errors."""


# --- Session errors ---


class SessionNotFoundError(AnalysisToolError):
    """Session directory does not exist under ~/.claude/projects/."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


# --- Data errors ---


class RawDataNotFoundError(AnalysisToolError):
    """The analysis/raw/ directory is missing or empty."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"No raw data found at {path}")


class ParseError(AnalysisToolError):
    """A JSONL line or file could not be parsed."""

    def __init__(self, path: str, detail: str = "") -> None:
        self.path = path
        self.detail = detail
        msg = f"Failed to parse {path}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


# --- Watch errors ---


class WatchTargetNotFoundError(AnalysisToolError):
    """The team directory being watched does not exist."""

    def __init__(self, team_name: str) -> None:
        self.team_name = team_name
        super().__init__(f"Team not found: {team_name}")


# --- Template errors ---


class TemplateNotFoundError(AnalysisToolError):
    """A Jinja2 template file is missing."""

    def __init__(self, template_name: str) -> None:
        self.template_name = template_name
        super().__init__(f"Template not found: {template_name}")
