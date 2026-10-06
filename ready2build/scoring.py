from .models import CriterionScore, Review
import math

CRITERIA = {
    "requirements_clarity": "Requirements are explicit, complete, and testable.",
    "systems_interfaces": "Source/target systems, interfaces, and dependencies are identified.",
    "data_mapping_rules": "Mappings, transformations, calculations, and business rules are specified.",
    "volume_performance": "Volumes, performance expectations, and schedules are stated.",
    "error_handling": "Error handling, retries, reconciliation, and monitoring are addressed.",
    "security_operations": "Security, privacy, support, and operational controls are addressed.",
}

TEMPLATE_TYPES = ("Payroll Export", "Activity Definition Export", "People Import")


def classify_effort(hours, mapping_only=False):
    """Return the hour-tier classification, with direct mapping taking precedence."""
    if mapping_only:
        return "Low"
    if hours is None:
        return "Undetermined"
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return "Undetermined"
    if hours < 0:
        return "Undetermined"
    if hours < 16:
        return "Low"
    if hours < 32:
        return "Medium"
    return "High"


def score_review(payload: dict) -> Review:
    scores = []
    for name, description in CRITERIA.items():
        item = payload.get("criteria", {}).get(name, {})
        try:
            score = max(1, min(5, int(item.get("score", 3))))
        except (TypeError, ValueError):
            score = 3
        reason = str(item.get("reason") or "Not enough evidence supplied; provisional midpoint assigned.")[:1000]
        scores.append(CriterionScore(name, score, reason))
    avg = sum(s.score for s in scores) / len(scores)
    readiness_score = round(avg * 20)
    gaps = list(map(str, payload.get("missing_information", []) or []))
    questions = list(map(str, payload.get("clarification_questions", []) or []))
    factors = payload.get("implementation_factors") or {}
    assessments = []
    raw_assessments = payload.get("template_assessments")
    if not isinstance(raw_assessments, list):
        raw_assessments = []
    for raw in raw_assessments:
        if not isinstance(raw, dict) or raw.get("template_type") not in TEMPLATE_TYPES:
            continue
        tasks = raw.get("tasks") if isinstance(raw.get("tasks"), list) else []
        valid_tasks = [t for t in tasks if isinstance(t, dict) and isinstance(t.get("hours"), (int, float)) and math.isfinite(t["hours"]) and t["hours"] >= 0]
        task_total = sum(float(t["hours"]) for t in valid_tasks) if tasks and len(valid_tasks) == len(tasks) else None
        # Recompute the total from line items so totals cannot silently double-count or disagree.
        hours = task_total
        mapping_only = raw.get("direct_mapping_only") is True
        level = classify_effort(hours, mapping_only)
        reason = ("Direct source-to-target mapping only; classified Low regardless of mapped field count." if mapping_only else
                  f"Estimated {hours:g} Boomi consultant hours; {level} tier." if hours is not None else
                  "Effort is not sufficiently specified to classify.")
        assessments.append({**raw, "total_hours": hours, "direct_mapping_only": mapping_only,
                            "complexity": level, "task_hours_total": task_total, "classification_reason": reason})
        for item in raw.get("missing_information", []) if isinstance(raw.get("missing_information"), list) else []:
            if str(item) not in gaps:
                gaps.append(str(item))
        for item in raw.get("clarification_questions", []) if isinstance(raw.get("clarification_questions"), list) else []:
            question = str(item)
            if question not in questions:
                questions.append(question)
    if assessments:
        levels = [a["complexity"] for a in assessments]
        rank = {"Low": 0, "Medium": 1, "High": 2, "Undetermined": -1}
        complexity = max(levels, key=lambda x: rank[x])
        complexity_reason = "; ".join(f"{a['template_type']}: {a['classification_reason']}" for a in assessments)
    else:
        complexity, complexity_reason = "Undetermined", "No supported template-specific Boomi effort estimate was returned."
    provisional = bool(gaps) or complexity == "Undetermined" or any(a["total_hours"] is None for a in assessments)
    if complexity == "Undetermined":
        gaps.append("Template-specific Boomi build effort is not sufficiently clear to classify.")
    return Review(status="Provisional" if provisional else "Reviewed", complexity=complexity, provisional=provisional, scores=scores,
                  readiness_score=readiness_score, complexity_reason=complexity_reason, template_assessments=assessments,
                  implementation_factors=factors,
                  findings=list(map(str, payload.get("findings", []))), missing_information=gaps,
                  clarification_questions=questions, risks=list(map(str, payload.get("risks", []) or [])),
                  assumptions=list(map(str, payload.get("assumptions", []))), reviewer_notes=str(payload.get("reviewer_notes", "")))
