import re

# Patterns are deliberately conservative; extend through environment-configured rules if required.
PATTERNS = [
    (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]"),
    (r"\b(?:\+?\d[\d .()/-]{7,}\d)\b", "[REDACTED_PHONE]"),
    (r"(?i)\b(?:api[_ -]?key|client[_ -]?secret|password|passwd|token|authorization)\b\s*[:=]\s*[^\s,;]+", "[REDACTED_CREDENTIAL]"),
    (r"\b(?:\d[ -]*?){13,19}\b", "[REDACTED_PAYMENT_NUMBER]"),
    (r"(?i)\b(?:ssn|social security number)\s*[:#]?\s*\d{3}-?\d{2}-?\d{4}\b", "[REDACTED_PERSONAL_ID]"),
    (r"(?i)\b(?:customer|employee|person|patient)\s+(?:name|id)\s*[:=]\s*[^\n,;]+", "[REDACTED_SENSITIVE_VALUE]"),
    # Jira issue keys (for example, ABC-123) and labeled DIM identifiers.
    (r"\b[A-Z][A-Z0-9]{1,9}-\d+\b", "[REDACTED_JIRA_KEY]"),
    (r"(?i)\bDIM\s*(?:task|solution)(?:\s*ID)?\s*[:=#]\s*[^\s,;]+", "[REDACTED_DIM_ID]"),
]


def sanitize(text: str, extra_patterns=None) -> str:
    for item in extra_patterns or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not all(isinstance(v, str) for v in item):
            raise ValueError("Each sanitizer rule must contain a regex and replacement string")
        re.compile(item[0])
    # Apply configured rules first so a project-specific rule can override
    # the generic Jira-key matcher (for example, ACCT-123 account IDs).
    for pattern, replacement in [*(extra_patterns or []), *PATTERNS]:
        text = re.sub(pattern, replacement, text)
    return text
