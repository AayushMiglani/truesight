"""PII redaction, applied to every Evidence snapshot before it is stored, shown,
or sent to a model. On by default; there is no switch to turn it off."""

import re

# ponytail: pattern list tuned for Indian PII (phone, PAN, Aadhaar, email, IPv4).
# Add patterns here as leaks are found; move to config when a second team adopts.
_PATTERNS = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"(?<![\dA-Fa-f])\d{4}\s?\d{4}\s?\d{4}(?![\dA-Fa-f])")),
    ("phone", re.compile(r"(?<![\dA-Fa-f])(?:\+?91[\s-]?)?[6-9]\d{9}(?![\dA-Fa-f])")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
)


def redact(text: str) -> tuple[str, int]:
    """Return the text with PII replaced by [redacted:<kind>], and the count replaced."""
    total = 0
    for kind, pattern in _PATTERNS:
        text, n = pattern.subn(f"[redacted:{kind}]", text)
        total += n
    return text, total


def redact_lines(lines: list[str]) -> tuple[tuple[str, ...], int]:
    out, total = [], 0
    for line in lines:
        clean, n = redact(line)
        out.append(clean)
        total += n
    return tuple(out), total
