"""SecureAssist backend / AI orchestrator (PREDEFINED).

Endpoints (port 8092):
  GET  /health            liveness: process is up (no dependency calls)
  GET  /ready             readiness: configuration valid and MCP hostname resolves
  GET  /ready?deep=true   also probes MCP (tools/list), Ollama and Langfuse (report only)
  POST /chat              {"message": "..."} -> guardrails -> MCP / Ollama -> guardrails

Request flow for POST /chat:
  1. Validate JSON body.
  2. Input guardrail. If blocked -> HTTP 400, NOTHING else is called.
  3. Choose a route with simple, documented keyword rules:
       "status" route : message asks about the status of an approved service
                        -> MCP tool get_service_status (answer is the tool result)
       "faq" route    : message mentions a helpdesk topic
                        -> MCP tool search_support_faq, results given to phi3:mini as context
       "llm" route    : everything else -> phi3:mini only
  4. Output guardrail on every answer (redaction / validation).
  5. Langfuse trace (metadata only) and one structured JSON log line.
"""

import json
import logging
import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Flask, jsonify, request

import guardrails
import mcp_client
import ollama_client
from monitoring import Monitor

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
log = logging.getLogger("secureassist.backend")
for noisy in ("httpx", "mcp", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = Flask(__name__)
monitor = Monitor()

SERVICE_ALIASES = {
    "email": ["email", "e-mail", "mail", "outlook"],
    "vpn": ["vpn"],
    "sso": ["sso", "single sign-on", "single sign on"],
    "wifi": ["wifi", "wi-fi", "wireless"],
    "printing": ["printing", "printer", "printers", "print server"],
    "helpdesk-portal": ["helpdesk portal", "helpdesk-portal", "service portal"],
}
STATUS_WORDS = re.compile(r"\b(status|outage|down|degraded|is\s+\w+\s+working|any\s+issues?)\b", re.I)
FAQ_WORDS = re.compile(
    r"\b(how\s+do\s+i|how\s+to|faq|reset|password|vpn|mfa|2fa|authenticator|printer|print|"
    r"email|outlook|wi-?fi|wireless|software|install|lost|stolen|laptop)\b", re.I)


def log_event(event: str, **fields):
    """One JSON object per line -> easy to grep with kubectl logs."""
    fields.update({"ts": datetime.now(timezone.utc).isoformat(), "event": event})
    log.info(json.dumps(fields))


def choose_route(message: str) -> tuple[str, str | None]:
    """Return (route, service). Transparent keyword rules - see module docstring."""
    lower = message.lower()
    if STATUS_WORDS.search(lower):
        for service, aliases in SERVICE_ALIASES.items():
            if any(re.search(rf"\b{re.escape(a)}\b", lower) for a in aliases):
                return "status", service
    if FAQ_WORDS.search(lower):
        return "faq", None
    return "llm", None


def _now():
    return datetime.now(timezone.utc)


def _span(spans, name, start, level="DEFAULT", **metadata):
    spans.append({"name": name, "start": start, "end": _now(), "level": level, "metadata": metadata})


def format_faq_context(results: list[dict]) -> str:
    return "\n".join(f"- [{r['id']}] {r['title']}: {r['answer']}" for r in results)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "secureassist-backend",
                    "monitoring": monitor.status()["state"]})


@app.get("/ready")
def ready():
    host = urlparse(mcp_client.MCP_SERVER_URL).hostname or ""
    checks = {}
    try:
        socket.getaddrinfo(host, None)
        checks["mcp_dns"] = {"ok": True, "host": host}
    except OSError:
        checks["mcp_dns"] = {"ok": False, "host": host, "detail": "hostname does not resolve"}
    checks["config"] = {"ok": bool(ollama_client.OLLAMA_URL and ollama_client.OLLAMA_MODEL),
                        "ollama_url": ollama_client.OLLAMA_URL, "model": ollama_client.OLLAMA_MODEL}
    is_ready = all(c["ok"] for c in checks.values())

    if request.args.get("deep") == "true":  # informational only; does not change the status code
        checks["mcp"] = mcp_client.check_server()
        checks["ollama"] = ollama_client.check_model_available()
        checks["langfuse"] = {**monitor.status(), **monitor.auth_check()}

    if not is_ready:
        log_event("readiness_failed", checks=checks)
    return jsonify({"ready": is_ready, "checks": checks}), (200 if is_ready else 503)


@app.post("/chat")
def chat():
    trace_id = uuid.uuid4().hex
    started = time.monotonic()
    spans: list[dict] = []
    meta = {"trace_id": trace_id, "model": ollama_client.OLLAMA_MODEL, "route": None,
            "guardrail_input": None, "guardrail_output": None, "mcp_tool": None,
            "mcp_outcome": None, "success": False, "outcome": None, "error_category": None,
            "message_chars": 0, "degraded": False}
    tools_used: list[dict] = []

    def finish(status_code: int, body: dict):
        meta["duration_ms"] = int((time.monotonic() - started) * 1000)
        meta["monitoring"] = monitor.record_chat(trace_id, dict(meta), spans)
        log_event("chat", **meta)
        body.update({"trace_id": trace_id, "route": meta["route"], "tools_used": tools_used,
                     "model": meta["model"], "duration_ms": meta["duration_ms"],
                     "monitoring": meta["monitoring"], "degraded": meta["degraded"]})
        return jsonify(body), status_code

    # 1. JSON validation
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "message" not in data:
        meta.update(outcome="bad_request", error_category="invalid_json")
        return finish(400, {"blocked": False, "error": {"category": "invalid_json",
                            "message": 'Send JSON like {"message": "your question"}'}})
    message = data["message"]
    meta["message_chars"] = len(message) if isinstance(message, str) else 0

    # 2. Input guardrail - blocked input never reaches MCP or Ollama
    t0 = _now()
    decision = guardrails.check_input(message)
    meta["guardrail_input"] = decision.category
    _span(spans, "guardrail-input", t0, "DEFAULT" if decision.allowed else "WARNING",
          allowed=decision.allowed, category=decision.category)
    if not decision.allowed:
        meta.update(outcome="blocked", error_category=f"guardrail_{decision.category}", success=True)
        return finish(400, {"blocked": True, "answer": None,
                            "guardrail": {"allowed": False, "category": decision.category,
                                          "reason": decision.reason}})
    message = message.strip()

    # 3. Route and dependencies
    route, service = choose_route(message)
    meta["route"] = route
    context = None
    faq_results: list[dict] = []
    try:
        if route == "status":
            meta["mcp_tool"] = "get_service_status"
            t0 = _now()
            result = mcp_client.call_tool("get_service_status", {"service": service})
            _span(spans, "mcp:get_service_status", t0, service=service, outcome="success")
            meta["mcp_outcome"] = "success"
            tools_used.append({"type": "mcp", "name": "get_service_status", "outcome": "success"})
            raw_answer = (f"Service '{result['service']}' status: {result['status'].upper()}. "
                          f"{result.get('note', '')} (Source: {result.get('source', 'MCP tool')}.)")
        else:
            if route == "faq":
                meta["mcp_tool"] = "search_support_faq"
                t0 = _now()
                result = mcp_client.call_tool("search_support_faq", {"query": message[:200]})
                faq_results = result.get("results", [])
                _span(spans, "mcp:search_support_faq", t0, matches=len(faq_results), outcome="success")
                meta["mcp_outcome"] = "success"
                tools_used.append({"type": "mcp", "name": "search_support_faq", "outcome": "success",
                                   "matches": [r["id"] for r in faq_results]})
                context = format_faq_context(faq_results) or None
            t0 = _now()
            try:
                raw_answer = ollama_client.chat(message, context)
                _span(spans, "ollama", t0, outcome="success")
            except ollama_client.OllamaError as exc:
                _span(spans, "ollama", t0, "ERROR", outcome=exc.category)
                if not faq_results:
                    raise
                # Graceful degradation: show the approved FAQ text without the model.
                meta.update(degraded=True, error_category=exc.category)
                raw_answer = ("The AI model is currently unavailable, so here is the approved "
                              "FAQ answer:\n" + "\n".join(f"{r['title']} - {r['answer']}" for r in faq_results))
    except mcp_client.MCPError as exc:
        _span(spans, f"mcp:{meta['mcp_tool']}", t0, "ERROR", outcome=exc.category)
        meta.update(mcp_outcome=exc.category, outcome="dependency_error", error_category=exc.category)
        tools_used.append({"type": "mcp", "name": meta["mcp_tool"], "outcome": "error"})
        return finish(503, {"blocked": False, "answer": None, "error": {
            "category": exc.category, "dependency": "mcp-server",
            "message": "The support tools service (MCP server) is unavailable. Please try again later."}})
    except ollama_client.OllamaError as exc:
        meta.update(outcome="dependency_error", error_category=exc.category)
        return finish(503, {"blocked": False, "answer": None, "error": {
            "category": exc.category, "dependency": "ollama",
            "message": "The AI model (Ollama phi3:mini) is unavailable or too slow. Please try again later."}})

    # 4. Output guardrail
    t0 = _now()
    out_decision, safe_answer = guardrails.check_output(raw_answer)
    meta["guardrail_output"] = out_decision.category
    _span(spans, "guardrail-output", t0, "DEFAULT" if out_decision.allowed else "WARNING",
          allowed=out_decision.allowed, category=out_decision.category)
    if not out_decision.allowed:
        meta.update(outcome="invalid_response", error_category="guardrail_invalid_response")
        return finish(502, {"blocked": False, "answer": None, "error": {
            "category": "invalid_response", "dependency": "ollama",
            "message": "The model returned an invalid response, so it was not shown."}})

    meta.update(success=True, outcome="answered" if not meta["degraded"] else "answered_degraded")
    return finish(200, {"blocked": False, "answer": safe_answer,
                        "guardrail": {"allowed": True, "category": decision.category,
                                      "output_category": out_decision.category,
                                      "reason": out_decision.reason}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("BACKEND_PORT", "8092")))
