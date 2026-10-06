"""Extract explicitly labeled implementation names from sanitized IDD text."""
import re


_TEMPLATE_LABELS = {"template name", "integration template name", "boomi template name"}
_INTEGRATION_LABELS = {"integration name", "interface name"}


def _label_value(line, labels):
    cells = [cell.strip() for cell in line.split("|")]
    if cells and re.sub(r"\s+", " ", cells[0].strip().lower()) in labels:
        # Workbook extraction emits label | description | value | ...
        candidate = cells[2] if len(cells) > 2 else cells[1] if len(cells) > 1 else ""
        return candidate.strip()
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    match = re.search(rf"(?i)\b(?:{label_pattern})\s*[:=]\s*([^|\r\n;]+)", line)
    return match.group(1).strip() if match else ""


def extract_implementation_names(text):
    """Return exact template/integration names found after explicit IDD labels."""
    templates, integrations = [], []
    for line in text.splitlines():
        template = _label_value(line, _TEMPLATE_LABELS)
        integration = _label_value(line, _INTEGRATION_LABELS)
        for candidate, target in ((template, templates), (integration, integrations)):
            candidate = candidate.strip().strip("\"'")
            if candidate and candidate.lower() not in {"unknown", "n/a", "na", "not specified", "none"} and not candidate.startswith("[REDACTED") and candidate not in target:
                target.append(candidate)
    return {"template_names_mentioned": templates, "integration_name": integrations[0] if integrations else None}


def merge_implementation_names(payload, sanitized_text):
    """Prefer explicit names found deterministically in the sanitized document."""
    factors = payload.setdefault("implementation_factors", {})
    extracted = extract_implementation_names(sanitized_text)
    if extracted["template_names_mentioned"]:
        factors["template_names_mentioned"] = extracted["template_names_mentioned"]
    else:
        factors.setdefault("template_names_mentioned", [])
    if extracted["integration_name"]:
        factors["integration_name"] = extracted["integration_name"]
    else:
        factors.setdefault("integration_name", None)
    return payload
