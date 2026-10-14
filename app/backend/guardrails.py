"""SecureAssist input and output guardrails.

STUDENT TASK (Task 2): implement `check_input` and `check_output`.
This file is the REFERENCE SOLUTION. Code between the
"STUDENT TASK START/END" markers is what students write.

Design rules (deliberately simple and transparent):
  * Every check returns a GuardrailDecision with an explicit reason.
  * Blocked input never reaches Ollama or MCP tools (app.py checks
    `decision.allowed` BEFORE calling any dependency).
  * Model output is ONLY ever treated as text. Nothing in the backend passes
    model output to a shell, eval/exec, subprocess, or a privileged API.
    Jenkins stage 3 (Code checks) verifies this with a source scan.

IMPORTANT LIMITATION: keyword and regex checks are NOT complete protection
against prompt injection. Attackers can rephrase, translate, or encode
requests. These rules are one layer of defence-in-depth, alongside the MCP
tool allowlist, read-only tools, least-privilege containers and monitoring.
"""

import os
import re
from dataclasses import dataclass

MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "1000"))
MAX_RESPONSE_CHARS = int(os.getenv("MAX_RESPONSE_CHARS", "4000"))
REDACTION_TEXT = "[REDACTED]"


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str
    category: str  # "ok", "empty", "too_long", "invalid_type", "secret_request",
    #               "prompt_injection", "invalid_response", "redacted"


# --------------------------------------------------------------------------
# Documented rule sets (predefined - students use these in their code)
# --------------------------------------------------------------------------

# 1) Attempts to obtain secrets or credentials.
#    "How do I reset MY password?" is allowed; "show me the admin password" is not.
SECRET_REQUEST_PATTERNS = [
    r"\b(show|give|tell|reveal|print|list|dump|leak|share|send|display|expose|what\s+is|what's)\b"
    r"(\s+\w+){0,3}?\s+(passwords?|api[\s_-]?keys?|secrets?|tokens?|credentials?|private\s+keys?)\b"
    r"(?!\s+(policy|policies|reset|requirements?|rules|length|expiry|manager|change))",
    r"\b(admin|root|administrator|service[\s-]?account|database|db)\s+(password|credentials?)\b",
    r"\bkubectl\s+get\s+secrets?\b",
    r"\b(environment\s+variables?|env\s+vars?)\b.*\b(key|secret|password|token)s?\b",
    r"(/etc/shadow|/etc/passwd|id_rsa|\.ssh/)",
    r"\blangfuse[\s_-]*(secret|public)?[\s_-]*key\b",
]

# 2) Obvious prompt-injection / jailbreak phrases.
PROMPT_INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override)\b(\s+\w+){0,3}\s+(instructions|rules|guidelines|prompts?|policies)\b",
    r"\b(system|hidden|initial)\s+prompt\b",
    r"\byou\s+are\s+now\b",
    r"\b(developer|god|dan|jailbreak)\s+mode\b",
    r"\bjailbreak\b",
    r"\b(bypass|disable|turn\s+off)\b(\s+\w+){0,2}\s+(guardrails?|filters?|safety|restrictions?)\b",
    r"\bpretend\s+(you\s+are|to\s+be)\b.*\b(admin|root|unrestricted|unfiltered)\b",
    r"\bact\s+as\s+(an?\s+)?(admin|root|unrestricted|unfiltered)\b",
]

# 3) Recognisable secret formats that must never be shown to a user.
SECRET_OUTPUT_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",  # PEM keys
    r"\bAKIA[0-9A-Z]{16}\b",  # AWS access key id
    r"\b[sp]k-lf-[A-Za-z0-9-]{8,}\b",  # Langfuse keys
    r"\bsk-[A-Za-z0-9]{20,}\b",  # generic "sk-" API keys
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",  # GitHub tokens
    r"\bglpat-[A-Za-z0-9_-]{20,}\b",  # GitLab tokens
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWT
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*",  # bearer tokens
    # key=value / key: value where the value looks like a real secret (has a digit or symbol)
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*(?=\S*[0-9!@#$%^&*_])\S{6,}",
]

_SECRET_REQUEST_RE = [re.compile(p, re.IGNORECASE) for p in SECRET_REQUEST_PATTERNS]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
_SECRET_OUTPUT_RE = [re.compile(p, re.DOTALL) for p in SECRET_OUTPUT_PATTERNS]
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# --------------------------------------------------------------------------
# Input guardrail
# --------------------------------------------------------------------------
def check_input(message) -> GuardrailDecision:
    """Decide whether a user message may be processed.

    Order: type -> empty -> length -> secret request -> prompt injection.
    """
    # >>> STUDENT TASK START: check_input
    if not isinstance(message, str):
        return GuardrailDecision(False, "Message must be text.", "invalid_type")

    text = message.strip()
    if not text:
        return GuardrailDecision(False, "Message is empty. Please type a question.", "empty")

    if len(text) > MAX_PROMPT_CHARS:
        return GuardrailDecision(
            False,
            f"Message is too long ({len(text)} characters). Maximum is {MAX_PROMPT_CHARS}.",
            "too_long",
        )

    for pattern in _SECRET_REQUEST_RE:
        if pattern.search(text):
            return GuardrailDecision(
                False,
                "Requests for passwords, keys, tokens or other credentials are not allowed.",
                "secret_request",
            )

    for pattern in _INJECTION_RE:
        if pattern.search(text):
            return GuardrailDecision(
                False,
                "The message looks like an attempt to override SecureAssist instructions.",
                "prompt_injection",
            )

    return GuardrailDecision(True, "Input passed all guardrail checks.", "ok")
    # <<< STUDENT TASK END: check_input


# --------------------------------------------------------------------------
# Output guardrail
# --------------------------------------------------------------------------
def redact_secrets(text: str) -> tuple[str, int]:
    """Replace recognisable secrets with [REDACTED]. Returns (text, count)."""
    count = 0
    for pattern in _SECRET_OUTPUT_RE:
        text, n = pattern.subn(REDACTION_TEXT, text)
        count += n
    return text, count


def check_output(response) -> tuple[GuardrailDecision, str]:
    """Validate and sanitise a model or tool response before showing it.

    Returns (decision, safe_text). When decision.allowed is False, safe_text
    is an empty string and the caller must not show the original response.
    The safe_text is plain text only - it is never executed.
    """
    # >>> STUDENT TASK START: check_output
    if not isinstance(response, str):
        return GuardrailDecision(False, "Response was not text.", "invalid_response"), ""

    text = _CONTROL_CHARS_RE.sub("", response).strip()
    if not text:
        return GuardrailDecision(False, "Response was empty.", "invalid_response"), ""

    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS].rstrip() + " ...[truncated]"

    text, redactions = redact_secrets(text)
    if redactions:
        return (
            GuardrailDecision(True, f"{redactions} secret-like value(s) redacted.", "redacted"),
            text,
        )
    return GuardrailDecision(True, "Response passed output checks.", "ok"), text
    # <<< STUDENT TASK END: check_output
