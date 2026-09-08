"""Credential and PII detection.

Anything deposited can be inspected by the public, so a hardcoded key in
the source is not just a security bug - it is a disclosure. Findings are
reported with a masked excerpt, and each carries a stable id so the
operator's decision to ignore or redact it survives into the next run.
"""

from __future__ import annotations

import hashlib
import math
import re

from . import SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM, Finding

# (rule name, pattern, severity, human explanation)
_RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (
        "aws-access-key",
        re.compile(r"\b((?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16})\b"),
        SEVERITY_HIGH,
        "AWS access key id",
    ),
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        SEVERITY_HIGH,
        "embedded private key block",
    ),
    (
        "github-token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,})\b"),
        SEVERITY_HIGH,
        "GitHub token",
    ),
    (
        "slack-token",
        re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"),
        SEVERITY_HIGH,
        "Slack token",
    ),
    (
        "google-api-key",
        re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"),
        SEVERITY_HIGH,
        "Google API key",
    ),
    (
        "stripe-key",
        re.compile(r"\b((?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,})\b"),
        SEVERITY_HIGH,
        "Stripe secret key",
    ),
    (
        "openai-key",
        re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,})\b"),
        SEVERITY_HIGH,
        "OpenAI-style API key",
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        SEVERITY_MEDIUM,
        "JSON web token",
    ),
    (
        "connection-string",
        re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s/]+", re.IGNORECASE),
        SEVERITY_HIGH,
        "URL containing credentials",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        SEVERITY_LOW,
        "email address",
    ),
)

# name = "value" style assignments worth entropy-checking
# The prefix is optional so that a name which *is* the keyword - `api_key`,
# `token` - matches as readily as `service_api_key`.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?P<name>[A-Za-z0-9_]*
        (?:pass(?:wd|word)?|secret|token|api[_-]?key|apikey|auth|credential|private[_-]?key)
        [A-Za-z0-9_]*)
    \s*[:=]\s*
    (?P<quote>["'])(?P<value>[^"']{8,})(?P=quote)
    """
)

# Values that are obviously not real credentials. The tails accept hyphens
# and dots so that "your-api-key-here" is recognised as a placeholder.
_PLACEHOLDER = re.compile(
    r"(?i)^(?:\s*|x{3,}|\.{3,}|none|null|true|false|changeme|placeholder|redacted|"
    r"(?:your|my|the|some|example|dummy|test|sample|fake|todo|insert|enter|put)"
    r"[\w\-. ]*|"
    r"\$\{.*\}|\{\{.*\}\}|<.*>|%\w+%|\*+)$"
)

_NON_SECRET_EXT = (".md", ".rst", ".txt")


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _mask(value: str) -> str:
    if len(value) <= 8:
        return value[0] + "*" * (len(value) - 1) if value else ""
    return f"{value[:4]}{'*' * 8}{value[-2:]}"


def _finding_id(rel_path: str, line_number: int, rule: str, value: str) -> str:
    digest = hashlib.sha256(f"{rel_path}|{rule}|{value}".encode("utf-8")).hexdigest()
    return f"{rule}-{digest[:12]}"


def scan_text(rel_path: str, text: str) -> list[Finding]:
    """Find credentials and PII in one file's original text."""
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    allow_low = not rel_path.lower().endswith(_NON_SECRET_EXT)

    for number, line in enumerate(text.split("\n"), start=1):
        if len(line) > 4000:
            line = line[:4000]

        for rule, pattern, severity, detail in _RULES:
            if severity == SEVERITY_LOW and not allow_low:
                continue
            for match in pattern.finditer(line):
                value = match.group(1) if match.groups() else match.group(0)
                if _PLACEHOLDER.match(value):
                    continue
                key = (number, rule)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        id=_finding_id(rel_path, number, rule, value),
                        rel_path=rel_path,
                        line_number=number,
                        rule=rule,
                        detail=detail,
                        severity=severity,
                        excerpt=_mask(value),
                        category="secret",
                    )
                )

        match = _ASSIGNMENT.search(line)
        if match:
            value = match.group("value")
            name = match.group("name")
            if not _PLACEHOLDER.match(value) and _shannon_entropy(value) >= 3.0:
                key = (number, "hardcoded-credential")
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            id=_finding_id(rel_path, number, "hardcoded-credential", value),
                            rel_path=rel_path,
                            line_number=number,
                            rule="hardcoded-credential",
                            detail=f"high-entropy value assigned to '{name}'",
                            severity=SEVERITY_HIGH,
                            excerpt=_mask(value),
                            category="secret",
                        )
                    )
    return findings
