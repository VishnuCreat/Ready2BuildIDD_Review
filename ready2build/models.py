from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Attachment:
    id: str
    filename: str
    url: str
    mime_type: str = ""
    size: int = 0


@dataclass
class Issue:
    key: str
    url: str
    dim_solution_id: str
    summary: str
    status: str
    attachments: list[Attachment] = field(default_factory=list)
    content_fingerprint: str = ""


@dataclass
class CriterionScore:
    name: str
    score: int
    reason: str


@dataclass
class Review:
    status: str
    complexity: str
    provisional: bool
    scores: list[CriterionScore]
    readiness_score: int = 0
    complexity_reason: str = ""
    template_assessments: list[dict[str, Any]] = field(default_factory=list)
    implementation_factors: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    reviewer_notes: str = ""
    sanitized_link: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
