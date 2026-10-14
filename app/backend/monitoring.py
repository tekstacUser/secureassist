"""Langfuse monitoring for SecureAssist (PREDEFINED).

Uses the Langfuse server that runs as a Pod in the same namespace
(Service secureassist-langfuse:3031, image built from langfuse/Dockerfile) through the pinned
Langfuse Python SDK v2 (langfuse==2.60.10).

Environment variables (from the Kubernetes Secret `secureassist-langfuse`):
  LANGFUSE_HOST        http://secureassist-langfuse:3031 (Kubernetes Service DNS)
  LANGFUSE_PUBLIC_KEY  pk-lf-...
  LANGFUSE_SECRET_KEY  sk-lf-...

Privacy rules applied here:
  * NO prompt or answer text is sent - only lengths, route, decisions,
    tool names, durations and error categories.
  * NO keys, passwords or headers are ever placed in metadata.

Honesty rule: this module only says a trace was QUEUED for sending. Delivery
is proven separately by fetching the trace from the Langfuse API
(see langfuse/README.md and scripts/verify-deployment.sh).

If credentials are missing, `status()` reports "not_configured" and every
record call is a no-op, so the chatbot keeps working.
"""

import logging
import os

log = logging.getLogger("secureassist.monitoring")

def _is_placeholder(value: str) -> bool:
    return not value or "REPLACE" in value.upper()


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


class Monitor:
    def __init__(self):
        self.host = _env("LANGFUSE_HOST") or "http://secureassist-langfuse:3031"
        public_key, secret_key = _env("LANGFUSE_PUBLIC_KEY"), _env("LANGFUSE_SECRET_KEY")
        self.client = None
        self.error = None
        if _is_placeholder(public_key) or _is_placeholder(secret_key):
            self.state = "not_configured"
            log.warning("Langfuse monitoring NOT configured (missing or placeholder keys)")
            return
        try:
            from langfuse import Langfuse  # imported lazily so missing config costs nothing

            self.client = Langfuse(public_key=public_key, secret_key=secret_key, host=self.host,
                                   timeout=5, max_retries=1, release="secureassist-1.0")
            self.state = "configured"
            log.info("Langfuse monitoring configured for host %s", self.host)
        except Exception as exc:  # noqa: BLE001
            self.state = "error"
            self.error = type(exc).__name__
            log.error("Langfuse client could not start: %s", self.error)

    def status(self) -> dict:
        return {"state": self.state, "host": self.host, "error": self.error}

    def auth_check(self) -> dict:
        """Ask the Langfuse server to validate the keys (network call)."""
        if not self.client:
            return {"ok": False, "detail": self.state}
        try:
            return {"ok": bool(self.client.auth_check()), "detail": "keys accepted"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": type(exc).__name__}

    def record_chat(self, trace_id: str, metadata: dict, spans: list[dict]) -> str:
        """Queue one trace. Returns 'queued', 'not_configured' or 'error'.

        metadata: safe fields only (see app.py).
        spans:    [{"name", "start", "end", "level", "metadata"}] for guardrail,
                  MCP and Ollama steps.
        """
        if not self.client:
            return self.state
        try:
            trace = self.client.trace(
                id=trace_id,
                name="secureassist-chat",
                metadata=metadata,
                tags=["secureassist", f"route:{metadata.get('route')}",
                      "success" if metadata.get("success") else "failure"],
                input={"message_chars": metadata.get("message_chars")},
                output={"outcome": metadata.get("outcome"), "error_category": metadata.get("error_category")},
            )
            for span in spans:
                if span["name"] == "ollama":
                    trace.generation(name="ollama-chat", model=metadata.get("model"),
                                     start_time=span["start"], end_time=span["end"],
                                     level=span["level"], metadata=span["metadata"])
                else:
                    trace.span(name=span["name"], start_time=span["start"], end_time=span["end"],
                               level=span["level"], metadata=span["metadata"])
            self.client.flush()
            return "queued"
        except Exception as exc:  # noqa: BLE001 - monitoring must never break chat
            log.error("Langfuse record failed: %s", type(exc).__name__)
            return "error"
