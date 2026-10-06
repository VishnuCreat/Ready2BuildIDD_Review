import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .documents import extract_text
from .implementation import merge_implementation_names
from .scoring import score_review
from .sanitizer import sanitize

log = logging.getLogger(__name__)


def attachment_is_idd(attachment):
    name = attachment.filename.lower()
    return any(word in name for word in ("idd", "integration design", "interface design"))


def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120]


def comment_text(issue, review, correlation_id, sheet_link=""):
    parts = [f"Ready2Build IDD Review — {review.status}", f"IDD readiness: {review.readiness_score}/100", f"Implementation complexity: {review.complexity}{' (provisional)' if review.provisional else ''}", f"Complexity rationale: {review.complexity_reason}"]
    parts.extend([f"Key findings: {'; '.join(review.findings[:4]) or 'None recorded.'}", f"Missing information: {'; '.join(review.missing_information[:5]) or 'None recorded.'}", f"Clarification questions: {'; '.join(review.clarification_questions[:5]) or 'None.'}"])
    if sheet_link:
        parts.append(f"Review record: {sheet_link}")
    if review.sanitized_link:
        parts.append(f"Sanitized IDD: {review.sanitized_link}")
    parts.append(f"Correlation ID: {correlation_id}")
    return "\n".join(parts)


class Processor:
    def __init__(self, config, jira, ledger, smartsheet=None, llm=None, uploader=None):
        self.config, self.jira, self.ledger = config, jira, ledger
        self.smartsheet, self.llm, self.uploader = smartsheet, llm, uploader

    def process(self, issue, reprocess=False):
        attachments = [a for a in issue.attachments if attachment_is_idd(a)]
        fingerprint = hashlib.sha256((issue.content_fingerprint + "|" + "|".join(f"{a.id}:{a.filename}:{a.size}" for a in attachments)).encode()).hexdigest()
        if not reprocess and self.ledger.is_processed(issue.key, fingerprint):
            log.info("Skipping unchanged issue %s", issue.key)
            return "skipped"
        correlation = str(uuid.uuid5(uuid.NAMESPACE_URL, issue.key + ":" + fingerprint))
        if not attachments:
            log.warning("No likely IDD attachment found: issue=%s attachments=%d", issue.key, len(issue.attachments))
            self.ledger.record(issue.key, fingerprint, correlation, status="missing_attachment", reviewed_at=datetime.now(timezone.utc).isoformat())
            return "missing_attachment"
        review_payload = {"missing_information": ["IDD attachment could not be read; provide a supported, readable IDD file."], "clarification_questions": ["Can you attach a readable IDD document?"]}
        chosen = attachments[0]
        local = self.config.download_dir / issue.key / _safe_filename(chosen.filename)
        try:
            if not local.exists() or reprocess:
                self.jira.download_attachment(chosen, local)
            text = extract_text(local)
            clean = sanitize(text, self.config.sanitizer_patterns)
            sanitized_path = self.config.sanitized_dir / issue.key / (_safe_filename(chosen.filename).rsplit(".", 1)[0] + ".txt")
            sanitized_path.parent.mkdir(parents=True, exist_ok=True)
            sanitized_path.write_text(clean, encoding="utf-8")
            if self.config.llm_enabled and self.llm:
                # The only document text passed to the reviewer is the sanitized copy.
                review_payload = self.llm.review(clean)
                review_payload = merge_implementation_names(review_payload, clean)
        except Exception as exc:
            log.warning("IDD attachment unavailable for review: issue=%s filename=%s error=%s", issue.key, chosen.filename, type(exc).__name__)
            review_payload = {"missing_information": [f"Attachment {chosen.filename} is unsupported or unreadable."], "clarification_questions": ["Can you provide the IDD in a supported, readable format?"]}
            sanitized_path = None
        review = score_review(review_payload)
        review.sanitized_link = str(sanitized_path) if sanitized_path else ""
        if self.config.sharepoint_enabled and sanitized_path:
            try:
                if self.uploader:
                    review.sanitized_link = self.uploader.upload(sanitized_path, correlation, self.config.dry_run)
                else:
                    log.info("DRY RUN SharePoint upload not configured: issue=%s file=%s correlation=%s", issue.key, sanitized_path.name, correlation)
            except Exception as exc:
                log.warning("SharePoint upload unavailable: issue=%s error=%s", issue.key, type(exc).__name__)
        values = {"review_status": review.status, "last_reviewed": date.today().isoformat(), "overall_complexity": review.complexity,
                  "idd_readiness_score": review.readiness_score, "overall_ready_to_build_score": review.readiness_score,
                  "complexity_reason": review.complexity_reason,
                  "critical_gaps": "; ".join(review.missing_information), "clarification_questions": "; ".join(review.clarification_questions),
                  "risks": "; ".join(review.risks), "assumptions": "; ".join(review.assumptions), "sanitized_idd_link": review.sanitized_link,
                  "reviewer_notes": review.reviewer_notes, "correlation_id": correlation}
        values.update({f"score_{s.name}": s.score for s in review.scores})
        values.update({f"reason_{s.name}": s.reason for s in review.scores})
        log.info("Review prepared: issue=%s status=%s complexity=%s provisional=%s correlation=%s", issue.key, review.status, review.complexity, review.provisional, correlation)
        if self.smartsheet:
            self.smartsheet.upsert(issue.key, issue.dim_solution_id, values, correlation, self.config.dry_run)
        comment = comment_text(issue, review, correlation)
        marker = f"Correlation ID: {correlation}"
        if not self.config.dry_run and self.jira.comment_exists(issue.key, marker):
            log.info("Jira comment already exists: issue=%s correlation=%s", issue.key, correlation)
        else:
            self.jira.add_comment(issue.key, comment, self.config.dry_run)
        if review.clarification_questions and self.config.jira_transition_on_clarification and self.config.jira_pending_status:
            self.jira.transition(issue.key, self.config.jira_pending_status, self.config.dry_run)
        self.ledger.record(issue.key, fingerprint, correlation, status=review.status, reviewed_at=datetime.now(timezone.utc).isoformat(), review=review.to_dict())
        return "processed"

    def follow_up_items(self):
        """Return provisional items waiting at least three business days; never sends messages."""
        import json
        data = self.ledger._read()
        today = date.today()
        flagged = []
        for key, item in data.items():
            if item.get("status") != "Provisional":
                continue
            stamp = item.get("reviewed_at", "")[:10]
            try:
                start = date.fromisoformat(stamp)
            except ValueError:
                continue
            days = sum(1 for n in range(1, (today - start).days + 1) if (start + timedelta(days=n)).weekday() < 5)
            if days >= 3:
                flagged.append(key)
        return flagged
