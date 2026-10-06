# Ready2Build IDD Review

Python REST application for polling a configurable Jira IDD review queue. Dry-run is enabled by default. It maintains a local processing ledger, discovers likely IDD attachments, downloads originals separately, sanitizes supported documents before optional LLM review, computes explainable complexity, and prepares Smartsheet/Jira actions through adapters.

## Install and run

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[documents,test]"
Copy-Item .env.example .env
pytest
ready2build --once
ready2build --poll
```

## Run the local IDD review app (no Jira required)

```powershell
python -m pip install -e ".[documents]"
Copy-Item .env.example .env
# Optional: set LLM_ENABLED=true and LLM_PROVIDER=codex_cli in .env to use your signed-in Codex CLI.
python -m ready2build.manual_server --port 8501
```

Open `http://localhost:8501/` for the upload form. If that port is in use, choose another port, such as `--port 8502`, and open the matching URL. Keep the terminal running while using the app; press Ctrl+C to stop it. Supported upload formats depend on the optional reader libraries installed above.

For an assessment using your signed-in Codex CLI, set `LLM_ENABLED=true` and `LLM_PROVIDER=codex_cli` in `.env`. No API key is needed for that option. The app sends sanitized text to the reviewer and runs Codex with shell, apps, and web search disabled. Alternatively, set `LLM_PROVIDER=api` and configure `LLM_API_KEY` and `LLM_MODEL`. With LLM disabled, the page performs sanitization only and does not create placeholder assessment scores. Results are saved under `.ready2build/manual-results/`.

Set Jira configuration in `.env` for queue retrieval. A dry-run needs no write credentials and makes no external changes. LLM review, Smartsheet updates, status transitions, and SharePoint upload are independently gated by configuration; all external writes require `DRY_RUN=false`.

Required for a Jira run: Jira URL, email, API token and project/queue settings. For row updates, configure the Smartsheet token, sheet ID and numeric column IDs. The manual POC can use a signed-in Codex CLI (`LLM_PROVIDER=codex_cli`) or an API provider (`LLM_PROVIDER=api`). SharePoint needs Microsoft Graph configuration. Never commit `.env` or paste credentials into source.

The default ledger and downloaded documents are under `.ready2build/`. Originals and sanitized files use separate directories. The ledger detects changes using Jira content and attachment metadata fingerprints; `--reprocess KEY` explicitly bypasses the unchanged-item skip. Set `JIRA_DIM_FIELD` to the Jira custom field id containing DIM Solution ID when one is used. The Overall Ready-to-Build Score is the average of six IDD completeness scores, scaled to 0–100. Complexity is assessed separately for Payroll Export, Activity Definition Export, and People Import from task-by-task Boomi consultant hours grounded in IDD requirements. Direct source-to-target mapping only is Low regardless of field count; other work is Low below 16 hours, Medium from 16 to under 32 hours, and High at 32 hours or more. Unsupported estimates remain provisional. Thresholds are defined in `ready2build/scoring.py`; the project has no existing threshold configuration mechanism. Additional sanitization expressions can be supplied through `SANITIZER_PATTERNS` as JSON `[regex, replacement]` pairs. SharePoint upload uses Microsoft Graph client credentials and requires tenant, app client, site, and drive configuration.

Readiness criteria and deterministic implementation-complexity rules are in `ready2build/scoring.py`; the reviewer prompt and extracted implementation factors are defined in `ready2build/llm.py` and `ready2build/codex_cli.py`. Sanitization patterns are in `ready2build/sanitizer.py`. Evidence and all document-derived text are kept out of application logs.
