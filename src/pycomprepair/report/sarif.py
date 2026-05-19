"""SARIF 2.1.0 reporter for ingestion by GitHub Code Scanning and other tooling.

SARIF (`Static Analysis Results Interchange Format`_) is the format GitHub's
*Code Scanning* feature expects. Producing a SARIF artifact lets PyCompatRepair
issues show up natively in the **Security** tab of any GitHub repository and
be uploaded with the standard ``github/codeql-action/upload-sarif`` action::

    pycomprepair report ./src --format sarif --output pcr.sarif

This module produces a minimal-but-conformant document: one ``run`` whose
tool driver is PyCompatRepair, a ``rules`` array deduplicating the encountered
codes (so each unique rule appears once with its default severity), and one
``result`` per issue with a ``physicalLocation`` pointing at the source file.

.. _Static Analysis Results Interchange Format:
   https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pycomprepair import __version__
from pycomprepair.core.issue import Issue, Severity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json"
)
TOOL_INFORMATION_URI = "https://github.com/alvaroo-fdez/pycomprepair"

_SEVERITY_TO_LEVEL = {
    Severity.INFO: "note",
    Severity.WARNING: "warning",
    Severity.ERROR: "error",
}


def render_issues_sarif(
    issues: Iterable[Issue],
    *,
    base_path: Path | None = None,
) -> str:
    """Return a SARIF 2.1.0 JSON document describing ``issues``.

    Parameters
    ----------
    issues:
        The detected incompatibilities.
    base_path:
        Optional root used to compute ``artifactLocation.uri`` as a
        repository-relative POSIX path. When omitted the file path is
        rendered as-is (still using forward slashes). Supplying the repo
        root is recommended for GitHub Code Scanning so links jump to the
        correct file in PRs.
    """
    issues = list(issues)
    rules_index, rules = _collect_rules(issues)
    results = [_issue_to_result(issue, rules_index, base_path) for issue in issues]

    document: dict[str, Any] = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "pycomprepair",
                        "version": __version__,
                        "informationUri": TOOL_INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2, sort_keys=False)


def _collect_rules(issues: list[Issue]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Return (code -> rule index, rule descriptors) for SARIF ``rules``."""
    rules: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    # Track which severity has been seen first for each rule so we keep
    # ``defaultConfiguration.level`` stable across runs.
    for issue in issues:
        if issue.code in index:
            continue
        index[issue.code] = len(rules)
        rules.append(
            {
                "id": issue.code,
                "name": issue.code,
                "shortDescription": {"text": _rule_short_description(issue)},
                "fullDescription": {"text": _rule_short_description(issue)},
                "defaultConfiguration": {
                    "level": _SEVERITY_TO_LEVEL.get(issue.severity, "warning"),
                },
                "helpUri": TOOL_INFORMATION_URI,
            }
        )
    return index, rules


def _rule_short_description(issue: Issue) -> str:
    """Best-effort one-line summary for a rule from one of its messages."""
    # Trim long messages so the rule descriptor stays compact; the per-result
    # ``message.text`` always carries the full diagnostic.
    text = issue.message.strip().splitlines()[0]
    return text[:200]


def _issue_to_result(
    issue: Issue,
    rules_index: dict[str, int],
    base_path: Path | None,
) -> dict[str, Any]:
    location = {
        "physicalLocation": {
            "artifactLocation": {"uri": _artifact_uri(issue.file, base_path)},
            "region": {
                # SARIF columns are 1-based; our issues use 0-based offsets.
                "startLine": max(1, issue.line),
                "startColumn": max(1, issue.column + 1),
            },
        }
    }
    result: dict[str, Any] = {
        "ruleId": issue.code,
        "ruleIndex": rules_index[issue.code],
        "level": _SEVERITY_TO_LEVEL.get(issue.severity, "warning"),
        "message": {"text": issue.message},
        "locations": [location],
    }
    if issue.fix is not None:
        result["fixes"] = [
            {
                "description": {"text": issue.fix.description},
            }
        ]
    return result


def _artifact_uri(file: Path, base_path: Path | None) -> str:
    """Render ``file`` as a SARIF-friendly URI (forward slashes, URL-quoted)."""
    if base_path is not None:
        try:
            rel = file.resolve().relative_to(base_path.resolve())
            posix = rel.as_posix()
        except ValueError:
            posix = file.as_posix()
    else:
        posix = file.as_posix()
    # SARIF artifactLocation.uri should be a valid URI reference; keep slashes
    # but escape other unsafe characters (spaces, brackets, etc.).
    return quote(posix, safe="/:")
