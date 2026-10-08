import json
from pathlib import Path

from ready2build.ledger import Ledger
from ready2build.models import Attachment, Issue
from ready2build.processor import Processor, attachment_is_idd
from ready2build.sanitizer import sanitize
from ready2build.scoring import classify_effort, score_review


def test_available_document_formats_reflect_installed_readers(monkeypatch):
    from ready2build import documents
    available = {"pypdf", "docx", "openpyxl"}
    monkeypatch.setattr(documents.importlib.util, "find_spec", lambda name: object() if name in available else None)
    assert documents.available_extensions() == {".pdf", ".docx", ".xlsx", ".csv", ".txt"}
    available.clear()
    assert documents.available_extensions() == {".docx", ".csv", ".txt"}
    assert documents.missing_document_readers() == {".pdf": "pypdf", ".xlsx": "openpyxl"}


def test_docx_text_extraction_has_standard_library_fallback(monkeypatch):
    import sys
    from ready2build import documents
    xml = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>People Import IDD</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Employee ID</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
    class Archive:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _name): return xml
    monkeypatch.setattr(documents.zipfile, "ZipFile", Archive)
    monkeypatch.setitem(sys.modules, "docx", None)
    assert documents.extract_text(Path("synthetic.docx")) == "People Import IDD\nEmployee ID"


def test_effort_tiers_boundary_hours():
    assert classify_effort(15.99) == "Low"
    assert classify_effort(16) == "Medium"
    assert classify_effort(31.99) == "Medium"
    assert classify_effort(32) == "High"


def test_mapping_only_is_low_even_with_many_fields_and_high_hours():
    review = score_review({"template_assessments": [{
        "template_type": "Payroll Export", "total_hours": 40, "direct_mapping_only": True,
        "tasks": [{"task": "Direct mapping", "hours": 40, "evidence": "Source fields mapped to target fields"}],
        "evidence": "Direct mapping table", "confidence": "High"}]})
    assert review.template_assessments[0]["complexity"] == "Low"
    assert review.template_assessments[0]["total_hours"] == 40
    assert "regardless of mapped field count" in review.template_assessments[0]["classification_reason"]


def test_sanitizer_redacts_sensitive_values():
    result = sanitize("Contact jane@example.com; API_KEY=abcd1234; customer name: Jane Doe")
    assert "jane@example.com" not in result
    assert "abcd1234" not in result
    assert "Jane Doe" not in result


def test_sanitizer_redacts_jira_and_dim_identifiers():
    result = sanitize("See ABC-123 and Jira issue R2B-42. DIM task: TASK-987; DIM Solution ID=445566")
    assert "ABC-123" not in result
    assert "R2B-42" not in result
    assert "TASK-987" not in result
    assert "445566" not in result
    assert result.count("[REDACTED_JIRA_KEY]") == 2
    assert "[REDACTED_DIM_ID]" in result


def test_sanitizer_accepts_configured_rules():
    assert sanitize("Account: ACCT-123", [[r"ACCT-\d+", "[REDACTED_ACCOUNT]"]]) == "Account: [REDACTED_ACCOUNT]"


def test_scoring_is_explainable_and_provisional():
    review = score_review({"criteria": {"requirements_clarity": {"score": 5, "reason": "Specific acceptance rules"}}, "missing_information": ["Volume absent"],
                           "template_assessments": [{"template_type": "People Import", "total_hours": 10, "direct_mapping_only": True, "tasks": [], "evidence": "Direct map", "confidence": "High"}]})
    assert review.provisional
    assert review.scores[0].score == 5
    assert review.scores[0].reason == "Specific acceptance rules"
    assert review.complexity == "Low"
    assert review.readiness_score == 67


def test_implementation_complexity_uses_effort_not_readiness_scores():
    high_scores = {name: {"score": 5, "reason": "Complete"} for name in ("requirements_clarity", "systems_interfaces", "data_mapping_rules", "volume_performance", "error_handling", "security_operations")}
    review = score_review({"criteria": high_scores, "template_assessments": [{"template_type": "Payroll Export", "total_hours": 32, "direct_mapping_only": False, "tasks": [{"task": "Payroll rules", "hours": 32, "evidence": "Complex payroll rules"}], "evidence": "Complex payroll rules", "confidence": "Medium"}]})
    assert review.readiness_score == 100
    assert review.complexity == "High"


def test_simple_mapping_is_low_and_unknown_factors_are_provisional():
    low = score_review({"template_assessments": [{"template_type": "People Import", "total_hours": 12, "direct_mapping_only": True, "tasks": [], "evidence": "Direct map", "confidence": "High"}]})
    unknown = score_review({})
    assert low.complexity == "Low"
    assert unknown.complexity == "Undetermined"
    assert unknown.provisional


def test_template_estimates_are_assessed_separately():
    review = score_review({"template_assessments": [
        {"template_type": "Payroll Export", "total_hours": 8, "direct_mapping_only": True, "tasks": [{"task": "Map", "hours": 8, "evidence": "Map only"}], "evidence": "Map only", "confidence": "High"},
        {"template_type": "People Import", "total_hours": 16, "direct_mapping_only": False, "tasks": [{"task": "Validation rules", "hours": 16, "evidence": "Validations"}], "evidence": "Validations", "confidence": "Medium"},
    ]})
    assert [a["complexity"] for a in review.template_assessments] == ["Low", "Medium"]
    assert review.complexity == "Medium"


def test_ledger_idempotency(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert not ledger.is_processed("R2B-1", "fp")
    ledger.record("R2B-1", "fp", "correlation")
    assert ledger.is_processed("R2B-1", "fp")
    assert not ledger.is_processed("R2B-1", "new")


def test_idd_attachment_selection():
    assert attachment_is_idd(Attachment("1", "System IDD v2.docx", "url"))
    assert not attachment_is_idd(Attachment("2", "diagram.png", "url"))


def test_jira_api_error_is_safe_and_raises():
    from ready2build.jira import JiraClient
    class Response:
        status_code = 403
        headers = {}
        def raise_for_status(self):
            raise RuntimeError("forbidden")
    class Session:
        auth = None
        headers = {}
        def request(self, *args, **kwargs):
            return Response()
    client = JiraClient("https://jira.invalid", "u", "secret", Session())
    import pytest
    with pytest.raises(RuntimeError):
        client._request("GET", "https://jira.invalid/rest/api/3/search")


def test_sharepoint_dry_run_does_not_call_api(tmp_path):
    from ready2build.sharepoint import SharePointUploader
    class Session:
        def post(self, *args, **kwargs):
            raise AssertionError("dry-run must not request a token")
        def put(self, *args, **kwargs):
            raise AssertionError("dry-run must not upload")
    path = tmp_path / "safe.txt"
    path.write_text("sanitized")
    uploader = SharePointUploader("", "", "", "", "", session=Session())
    assert "safe.txt" in uploader.upload(path, "corr", dry_run=True)


def test_codex_cli_reviewer_uses_structured_agent_output():
    from ready2build.codex_cli import CodexCLIReviewer
    expected = {"criteria": {}, "findings": [], "missing_information": [], "clarification_questions": [], "risks": [], "assumptions": [], "reviewer_notes": "ok",
                "implementation_factors": {"templates": 1, "apis": 0, "custom_shapes": 0, "scripts_functions": 0, "conditions": 0,
                                           "simple_mapping_only": False, "template_names_mentioned": ["Boomi UKG WFM to LMS v3"],
                                           "integration_name": "UKG WFM to LMS", "evidence": "Template listed"}}
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(expected)}}
    def runner(command, **kwargs):
        assert kwargs["input"].find("safe sanitized text") >= 0
        assert Path(kwargs["cwd"]) == Path(".ready2build").resolve()
        assert "--sandbox" in command and "read-only" in command
        schema = Path(command[command.index("--output-schema") + 1])
        assert schema.is_file()
        assert schema.parent == Path(kwargs["cwd"])
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(event), "stderr": ""})()
    reviewer = CodexCLIReviewer(runner=runner)
    assert reviewer.review("safe sanitized text") == expected
    assert not list(reviewer.workspace_dir.glob(".codex-review-schema-*.json"))


def test_result_page_shows_exact_template_names_from_idd():
    from ready2build.config import Config
    from ready2build.manual_server import _result_page
    review = score_review({"implementation_factors": {"templates": 1, "apis": None, "custom_shapes": None,
        "scripts_functions": None, "conditions": 1, "simple_mapping_only": False,
        "template_names_mentioned": ["Boomi UKG WFM to LMS v3"], "integration_name": "WFM Outbound", "evidence": "Named in the Integration Template section."}})
    page = _result_page("example.docx", review, "safe.txt", "result.json", "correlation", "sanitized", Config())
    assert "Template / integration name" in page
    assert "Boomi UKG WFM to LMS v3" in page
    assert "Not stated in IDD" not in page
    assert "WFM Outbound" in page


def test_result_page_uses_integration_name_when_template_name_is_not_labeled():
    from ready2build.config import Config
    from ready2build.manual_server import _result_page
    review = score_review({"implementation_factors": {"templates": None, "apis": None, "custom_shapes": None,
        "scripts_functions": None, "conditions": 1, "simple_mapping_only": False,
        "template_names_mentioned": [], "integration_name": "Activities Definition Export"}})
    page = _result_page("example.xlsx", review, "safe.txt", "result.json", "correlation", "sanitized", Config())
    assert "Activities Definition Export" in page
    assert "Template count: Not stated" in page
    assert "<span>TEMPLATES</span>" not in page


def test_extracts_integration_name_from_spreadsheet_label_value_row():
    from ready2build.implementation import extract_implementation_names
    names = extract_implementation_names("Integration Name | Customer facing display name of the interface | Activities Definition Export |  |")
    assert names["integration_name"] == "Activities Definition Export"
    assert names["template_names_mentioned"] == []


def test_codex_cli_reports_restricted_state_database_safely():
    from ready2build.codex_cli import CodexCLIReviewer
    def runner(command, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "attempt to write a readonly database"})()
    try:
        CodexCLIReviewer(runner=runner).review("synthetic text")
    except RuntimeError as exc:
        assert "regular Windows PowerShell" in str(exc)
    else:
        raise AssertionError("expected a writable local Codex state error")


def test_processor_skips_unchanged_issue(tmp_path):
    class Jira:
        def download_attachment(self, *args):
            raise AssertionError("must not redownload")
    class Config:
        download_dir = tmp_path / "downloads"
        sanitized_dir = tmp_path / "sanitized"
    ledger = Ledger(tmp_path / "ledger.json")
    issue = Issue("R2B-2", "url", "dim", "summary", "Ready", [], "fingerprint")
    p = Processor(Config(), Jira(), ledger)
    p.process(issue)
    assert p.process(issue) == "skipped"
