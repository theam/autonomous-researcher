"""Small, shared redaction rules for operator-visible text."""

from __future__ import annotations

import re


def redact_secret_shapes(value: str) -> str:
    """Redact common credential shapes without claiming full secret detection."""

    redacted = str(value).replace("\x00", "")
    redacted = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}",
        "Bearer [redacted]",
        redacted,
    )
    redacted = re.sub(
        r"\b(?:sk|ghp|gho|github_pat|xox[aboprs])[-_][A-Za-z0-9_-]{8,}",
        "[redacted]",
        redacted,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)=([^\s&]{4,})",
        r"\1=[redacted]",
        redacted,
    )
