"""Tests for the SARIF 2.1.0 reporter."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pycomprepair import __version__
from pycomprepair.cli import app
from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.report.sarif import render_issues_sarif


def _issue(
    code: str = "PYD001",
    *,
    file: Path = Path("src/app.py"),
    line: int = 10,
    column: int = 4,
    severity: Severity = Severity.ERROR,
    fix: Fix | None = None,
    message: str = "Example diagnostic",
) -> Issue:
    return Issue(
        plugin="example",
        code=code,
        message=message,
        file=file,
        line=line,
        column=column,
        severity=severity,
        fix=fix,
    )


def test_empty_document_is_valid_sarif() -> None:
    text = render_issues_sarif([])
    doc = json.loads(text)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "pycomprepair"
    assert doc["runs"][0]["tool"]["driver"]["version"] == __version__
    assert doc["runs"][0]["tool"]["driver"]["rules"] == []
    assert doc["runs"][0]["results"] == []


def test_basic_issue_renders_as_sarif_result() -> None:
    issue = _issue(severity=Severity.ERROR, line=42, column=7, message="boom")
    doc = json.loads(render_issues_sarif([issue]))
    results = doc["runs"][0]["results"]
    assert len(results) == 1
    result = results[0]
    assert result["ruleId"] == "PYD001"
    assert result["ruleIndex"] == 0
    assert result["level"] == "error"
    assert result["message"]["text"] == "boom"
    region = result["locations"][0]["physicalLocation"]["region"]
    # SARIF columns are 1-based; our internal columns are 0-based.
    assert region == {"startLine": 42, "startColumn": 8}


def test_severity_mapping() -> None:
    issues = [
        _issue("A", severity=Severity.INFO),
        _issue("B", severity=Severity.WARNING),
        _issue("C", severity=Severity.ERROR),
    ]
    doc = json.loads(render_issues_sarif(issues))
    levels = [r["level"] for r in doc["runs"][0]["results"]]
    assert levels == ["note", "warning", "error"]


def test_rules_are_deduplicated() -> None:
    issues = [
        _issue("PYD001"),
        _issue("PYD001", message="another instance"),
        _issue("DJA002", severity=Severity.WARNING),
    ]
    doc = json.loads(render_issues_sarif(issues))
    rules = doc["runs"][0]["tool"]["driver"]["rules"]
    ids = [r["id"] for r in rules]
    assert ids == ["PYD001", "DJA002"]
    # ruleIndex points to the dedup'd descriptor list.
    indices = [r["ruleIndex"] for r in doc["runs"][0]["results"]]
    assert indices == [0, 0, 1]


def test_fix_metadata_propagates() -> None:
    issue = _issue(fix=Fix(description="Rename .dict() to .model_dump()"))
    doc = json.loads(render_issues_sarif([issue]))
    fixes = doc["runs"][0]["results"][0]["fixes"]
    assert fixes == [{"description": {"text": "Rename .dict() to .model_dump()"}}]


def test_artifact_uri_is_relative_to_base_path(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    file = tmp_path / "app" / "views.py"
    file.write_text("x = 1\n", encoding="utf-8")
    issue = _issue(file=file)
    doc = json.loads(render_issues_sarif([issue], base_path=tmp_path))
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"]
    assert uri == "app/views.py"


def test_artifact_uri_falls_back_to_absolute(tmp_path: Path) -> None:
    file = tmp_path / "outside.py"
    issue = _issue(file=file)
    doc = json.loads(render_issues_sarif([issue], base_path=Path("/some/unrelated/root")))
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"]
    assert uri.endswith("outside.py")


def test_columns_clamp_to_one() -> None:
    """A column of 0 (first character) must serialise as startColumn 1."""
    issue = _issue(line=1, column=0)
    doc = json.loads(render_issues_sarif([issue]))
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startColumn"] == 1


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_report_sarif_writes_valid_json(tmp_path: Path) -> None:
    # The Django plugin is delivered as an entry point; in editable dev
    # installs the metadata may still point at an older wheel that only ships
    # pydantic/fastapi. Register explicitly so the test is hermetic.
    from pycomprepair.core.plugin import get_registry
    from pycomprepair.plugins.django_v5 import plugin as django_plugin

    get_registry().register(django_plugin)

    (tmp_path / "app").mkdir()
    file = tmp_path / "app" / "views.py"
    file.write_text(
        "from django.utils.encoding import smart_text\n"
        "def f(v):\n    return smart_text(v)\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.sarif"
    result = CliRunner().invoke(
        app,
        [
            "report",
            str(tmp_path / "app"),
            "--target",
            "django>=5.0",
            "--format",
            "sarif",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert doc["version"] == "2.1.0"
    rule_ids = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    assert "DJA002" in rule_ids
    # The artifact URI must be relative to the scanned directory.
    uris = {
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        for r in doc["runs"][0]["results"]
    }
    assert "views.py" in uris


def test_cli_report_rejects_unknown_format(tmp_path: Path) -> None:
    file = tmp_path / "ok.py"
    file.write_text("x = 1\n", encoding="utf-8")
    result = CliRunner().invoke(
        app, ["report", str(file), "--target", "django>=5.0", "--format", "xml"]
    )
    assert result.exit_code == 2
