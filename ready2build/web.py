"""Manual IDD upload proof of concept; independent of Jira and Smartsheet."""
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import uuid

import streamlit as st

from ready2build.config import Config
from ready2build.codex_cli import CodexCLIReviewer
from ready2build.documents import available_extensions, extract_text
from ready2build.llm import LLMReviewer
from ready2build.sanitizer import sanitize
from ready2build.scoring import score_review


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).name)[:120]


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Streamlit Community Cloud stores secrets in st.secrets rather than .env.
    # Preserve explicit environment variables when both are present.
    try:
        for key, value in st.secrets.items():
            if key not in os.environ and isinstance(value, (str, int, float, bool)):
                os.environ[key] = str(value)
    except Exception:
        pass

    st.set_page_config(page_title="Ready2Build IDD Review POC", layout="wide")
    st.title("Ready2Build IDD Review — POC")
    st.caption("Upload an IDD file to extract, sanitize, and review it. Jira and Smartsheet are not used in this POC.")
    extensions = available_extensions()
    uploaded = st.file_uploader("Choose an IDD document", type=[s.lstrip(".") for s in sorted(extensions)])
    if not uploaded:
        st.info("Readable file types in this environment: " + ", ".join(sorted(s.lstrip(".").upper() for s in extensions)) + ".")
        return

    config = Config.from_env()
    if st.button("Review IDD", type="primary"):
        sanitized_path = config.sanitized_dir / "manual" / (_safe_name(uploaded.name).rsplit(".", 1)[0] + ".txt")
        sanitized_path.parent.mkdir(parents=True, exist_ok=True)
        raw = uploaded.getvalue()
        correlation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(raw).hexdigest()))
        try:
            # Keep the unsanitized upload only in a temporary folder and remove
            # it after extraction; do not retain original IDDs on a public host.
            with tempfile.TemporaryDirectory(prefix="ready2build-upload-") as temp_dir:
                original_path = Path(temp_dir) / _safe_name(uploaded.name)
                original_path.write_bytes(raw)
                extracted = extract_text(original_path)
            clean = sanitize(extracted, config.sanitizer_patterns)
            if not clean.strip():
                st.error("No readable text was found in the uploaded file. Check that it is not image-only or empty.")
                return
            sanitized_path.write_text(clean, encoding="utf-8")
        except Exception as exc:
            logging.getLogger(__name__).warning("Manual IDD could not be processed: filename=%s error=%s", uploaded.name, type(exc).__name__)
            st.error(f"Could not read this file: {type(exc).__name__}. Check the format and installed document dependencies.")
            return

        if config.llm_enabled:
            if config.llm_provider == "api" and not (config.llm_api_key and config.llm_model):
                st.error("LLM_ENABLED is true, but LLM_API_KEY or LLM_MODEL is missing from .env.")
                return
            try:
                with st.spinner("Reviewing the sanitized IDD…"):
                    if config.llm_provider == "codex_cli":
                        payload = CodexCLIReviewer(config.codex_cli_path, config.codex_model, workspace_dir=config.ledger_path.parent).review(clean)
                    else:
                        payload = LLMReviewer(config.llm_base_url, config.llm_api_key, config.llm_model).review(clean)
            except Exception as exc:
                logging.getLogger(__name__).warning("Manual IDD review request failed: error=%s", type(exc).__name__)
                st.error(f"The review request failed ({type(exc).__name__}). Check the configured LLM endpoint and credentials.")
                return
            review = score_review(payload)
        else:
            st.success("File extracted and sanitized")
            st.warning("No IDD assessment or complexity score was generated because LLM review is not configured.")
            st.code("Set LLM_ENABLED=true and LLM_PROVIDER=codex_cli in .env, ensure Codex CLI is signed in, restart, and upload again.")
            st.text_area("Sanitized text (not sent to an LLM)", clean, height=250, disabled=True)
            st.caption(f"Sanitized file saved locally: {sanitized_path}")
            return
        result = {
            "filename": uploaded.name,
            "correlation_id": correlation_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review": review.to_dict(),
            "sanitized_file": str(sanitized_path),
        }
        result_dir = config.ledger_path.parent / "manual-results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{correlation_id}.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        st.success("Review complete" if config.llm_enabled else "Sanitization complete; LLM assessment is not configured")
        left, right = st.columns(2)
        left.metric("Status", review.status)
        right.metric("Implementation complexity", review.complexity)
        st.metric("Overall Ready-to-Build Score", f"{review.readiness_score}/100")
        st.caption("Readiness reflects the six criterion scores. Implementation complexity uses template-specific Boomi effort estimates from the IDD.")
        st.write("**Complexity rationale:** " + review.complexity_reason)
        for assessment in review.template_assessments:
            st.subheader(f"{assessment['template_type']} — {assessment['complexity']}")
            total = assessment.get("total_hours")
            st.write(f"Estimated total: {total:g} Boomi consultant hours" if total is not None else "Estimated total: Undetermined")
            st.write(assessment.get("classification_reason", ""))
            st.dataframe(assessment.get("tasks", []), use_container_width=True, hide_index=True)
            st.write("Evidence:", assessment.get("evidence", "Not stated"))
            st.write("Assumptions / exclusions:", assessment.get("assumptions", []))
            st.write("Missing information:", assessment.get("missing_information", []))
            st.write("Clarification questions:", assessment.get("clarification_questions", []))
            st.write("Confidence:", assessment.get("confidence", "Not stated"))
        if not config.llm_enabled:
            st.warning("This response does not assess completeness or complexity. Configure the LLM values in .env and rerun to receive the review.")
        st.subheader("Criterion scores")
        st.dataframe([{"Criterion": s.name.replace("_", " ").title(), "Score (1–5)": s.score, "Reason": s.reason} for s in review.scores], use_container_width=True, hide_index=True)
        for title, values in [("Findings", review.findings), ("Missing information", review.missing_information),
                              ("Clarification questions", review.clarification_questions), ("Risks", review.risks), ("Assumptions", review.assumptions)]:
            st.subheader(title)
            if values:
                for value in values:
                    st.markdown(f"- {value}")
            else:
                st.write("None reported.")
        if review.reviewer_notes:
            st.subheader("Reviewer notes")
            st.write(review.reviewer_notes)
        with st.expander("Sanitization preview"):
            st.text_area("Sanitized text (this is the only document text eligible for LLM review)", clean, height=250, disabled=True)
        st.caption(f"Correlation ID: {correlation_id} · Result saved locally to {result_path}")


if __name__ == "__main__":
    main()
