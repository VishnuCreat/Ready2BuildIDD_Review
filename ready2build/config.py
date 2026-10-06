from dataclasses import dataclass
import json
import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    dry_run: bool = True
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project: str = ""
    jira_jql: str = 'labels = ready2build AND status = "Ready for IDD Review"'
    jira_queue_status: str = "Ready for IDD Review"
    jira_label: str = "ready2build"
    jira_dim_field: str = ""
    jira_pending_status: str = ""
    jira_transition_on_clarification: bool = False
    poll_interval_seconds: int = 300
    smartsheet_access_token: str = ""
    smartsheet_sheet_id: str = ""
    smartsheet_columns: dict | None = None
    llm_enabled: bool = False
    llm_provider: str = "api"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    codex_cli_path: str = "codex"
    codex_model: str = ""
    sharepoint_enabled: bool = False
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""
    sharepoint_folder: str = "Ready2Build/IDD"
    sanitizer_patterns: list | None = None
    ledger_path: Path = Path(".ready2build/ledger.json")
    download_dir: Path = Path(".ready2build/downloads")
    sanitized_dir: Path = Path(".ready2build/sanitized")

    @classmethod
    def from_env(cls):
        try:
            columns = json.loads(os.getenv("SMARTSHEET_COLUMNS", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("SMARTSHEET_COLUMNS must be valid JSON") from exc
        try:
            sanitizer_patterns = json.loads(os.getenv("SANITIZER_PATTERNS", "[]"))
            if not isinstance(sanitizer_patterns, list):
                raise ValueError
        except ValueError as exc:
            raise ValueError("SANITIZER_PATTERNS must be a JSON array of [regex, replacement] pairs") from exc
        return cls(
            dry_run=_bool("DRY_RUN", True), jira_base_url=os.getenv("JIRA_BASE_URL", "").rstrip("/"),
            jira_email=os.getenv("JIRA_EMAIL", ""), jira_api_token=os.getenv("JIRA_API_TOKEN", ""),
            jira_project=os.getenv("JIRA_PROJECT", ""), jira_jql=os.getenv("JIRA_JQL", cls.jira_jql),
            jira_queue_status=os.getenv("JIRA_QUEUE_STATUS", cls.jira_queue_status), jira_label=os.getenv("JIRA_LABEL", cls.jira_label),
            jira_dim_field=os.getenv("JIRA_DIM_FIELD", ""),
            jira_pending_status=os.getenv("JIRA_PENDING_STATUS", ""), jira_transition_on_clarification=_bool("JIRA_TRANSITION_ON_CLARIFICATION", False),
            poll_interval_seconds=max(10, int(os.getenv("POLL_INTERVAL_SECONDS", "300"))),
            smartsheet_access_token=os.getenv("SMARTSHEET_ACCESS_TOKEN", ""), smartsheet_sheet_id=os.getenv("SMARTSHEET_SHEET_ID", ""), smartsheet_columns=columns,
            llm_enabled=_bool("LLM_ENABLED", False), llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"), llm_api_key=os.getenv("LLM_API_KEY", ""), llm_model=os.getenv("LLM_MODEL", ""),
            llm_provider=os.getenv("LLM_PROVIDER", "api").strip().lower(), codex_cli_path=os.getenv("CODEX_CLI_PATH", "codex"), codex_model=os.getenv("CODEX_MODEL", ""),
            sharepoint_enabled=_bool("SHAREPOINT_ENABLED", False), ledger_path=Path(os.getenv("LEDGER_PATH", ".ready2build/ledger.json")),
            sharepoint_tenant_id=os.getenv("SHAREPOINT_TENANT_ID", ""), sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID", ""), sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET", ""),
            sharepoint_site_id=os.getenv("SHAREPOINT_SITE_ID", ""), sharepoint_drive_id=os.getenv("SHAREPOINT_DRIVE_ID", ""), sharepoint_folder=os.getenv("SHAREPOINT_FOLDER", "Ready2Build/IDD"),
            sanitizer_patterns=sanitizer_patterns,
            download_dir=Path(os.getenv("DOWNLOAD_DIR", ".ready2build/downloads")), sanitized_dir=Path(os.getenv("SANITIZED_DIR", ".ready2build/sanitized")),
        )

    def validate_jira_read(self):
        missing = [name for name, value in [("JIRA_BASE_URL", self.jira_base_url), ("JIRA_EMAIL", self.jira_email), ("JIRA_API_TOKEN", self.jira_api_token)] if not value]
        if missing:
            raise ValueError("Missing Jira read configuration: " + ", ".join(missing))
