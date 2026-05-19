"""Data model for detected incompatibilities and proposed fixes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    """Severity level of a detected incompatibility."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Fix:
    """An automated fix suggestion produced by a plugin.

    A ``Fix`` is metadata only: the actual transformation is applied by the
    plugin's :meth:`Plugin.repair` method using libcst. This dataclass exists
    so that scans can be inspected, reported and audited without mutating
    source files.
    """

    description: str
    """Short, human-readable summary of what the fix does."""

    confidence: float = 1.0
    """Confidence score in ``[0.0, 1.0]``. Plugins emit conservative scores
    when ambiguity exists (e.g. dynamic call sites)."""

    safe: bool = True
    """Whether the fix is considered safe to apply automatically.
    Unsafe fixes are skipped unless ``--unsafe-fixes`` is passed."""


@dataclass(frozen=True)
class Issue:
    """A detected incompatibility at a specific call site."""

    plugin: str
    """Identifier of the plugin that detected the issue (e.g. ``pydantic``)."""

    code: str
    """Stable rule code (e.g. ``PYD001`` for ``Config`` class)."""

    message: str
    """Human-readable description."""

    file: Path
    """Path to the source file."""

    line: int
    """1-based line number."""

    column: int = 0
    """0-based column offset."""

    severity: Severity = Severity.WARNING

    fix: Fix | None = None
    """Optional automated fix. ``None`` means the issue must be resolved manually."""

    context: dict[str, str] = field(default_factory=dict)
    """Free-form metadata (e.g. old/new symbol names) used by reporters."""

    @property
    def location(self) -> str:
        """Render as ``path:line:column`` for CLI output."""
        return f"{self.file}:{self.line}:{self.column}"


def is_actionable(
    issue: Issue, *, min_confidence: float = 0.0, unsafe_fixes: bool = False
) -> bool:
    """Return ``True`` when ``issue`` should be auto-fixed under the given gates.

    Detection-only issues (``fix is None``) are never actionable: they exist
    purely to inform the user. For issues that *do* carry a :class:`Fix`,
    the gate is:

    * the fix must be ``safe`` (or ``unsafe_fixes=True`` must override that), and
    * ``fix.confidence`` must be ``>= min_confidence``.
    """
    fix = issue.fix
    if fix is None:
        return False
    if not fix.safe and not unsafe_fixes:
        return False
    return fix.confidence >= min_confidence
