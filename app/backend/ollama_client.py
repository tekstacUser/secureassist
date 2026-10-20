"""Ollama client for SecureAssist (PREDEFINED - students do not modify).

Calls the EXISTING Ollama server and the already-downloaded model. It never
pulls/downloads models and never needs a GPU.

Environment variables:
  OLLAMA_URL              default http://host.minikube.internal:11434 (from a Pod)
                          use http://localhost:11434 when running on the VM
  OLLAMA_MODEL            default phi3:mini
  OLLAMA_CONNECT_TIMEOUT  seconds to open the TCP connection (default 5)
  OLLAMA_READ_TIMEOUT     seconds to wait for the answer   (default 300, CPU is slow)
  OLLAMA_NUM_PREDICT      max tokens to generate            (default 256)
"""

import os

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.minikube.internal:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")
CONNECT_TIMEOUT = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("OLLAMA_READ_TIMEOUT", "300"))
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))

SYSTEM_PROMPT = (
    "You are SecureAssist, an internal IT helpdesk assistant. Answer briefly and "
    "practically in plain text. Only use the approved support information you are "
    "given when it is provided. Never ask for or reveal passwords, keys or tokens. "
    "Never claim to have performed actions on systems; you can only give guidance. "
    "If you are not sure, tell the employee to raise a ticket in the Helpdesk Portal."
)


class OllamaError(Exception):
    """Raised for any Ollama failure. `category` is safe to log and show."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def chat(user_message: str, context: str | None = None) -> str:
    """Send one question to the model and return validated answer text."""
    system = SYSTEM_PROMPT
    if context:
        system += "\n\nApproved support information:\n" + context
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "options": {"num_predict": NUM_PREDICT, "temperature": 0.2},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat", json=payload, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
    except requests.exceptions.ConnectTimeout as exc:
        raise OllamaError("ollama_connect_timeout", f"Could not connect to Ollama at {OLLAMA_URL}") from exc
    except requests.exceptions.ReadTimeout as exc:
        raise OllamaError("ollama_timeout", f"Ollama did not answer within {READ_TIMEOUT:.0f}s") from exc
    except requests.exceptions.ConnectionError as exc:
        raise OllamaError("ollama_unreachable", f"Ollama is unreachable at {OLLAMA_URL}") from exc

    if resp.status_code == 404:
        raise OllamaError("ollama_model_missing", f"Model '{OLLAMA_MODEL}' not found on the Ollama server")
    if resp.status_code != 200:
        raise OllamaError("ollama_http_error", f"Ollama returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise OllamaError("ollama_invalid_response", "Ollama returned non-JSON data") from exc

    content = (data.get("message") or {}).get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise OllamaError("ollama_invalid_response", "Ollama response had no answer text")
    return content.strip()


def check_model_available() -> dict:
    """Quick check used by /ready?deep=true. Never raises."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=(CONNECT_TIMEOUT, 5))
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        ok = any(n == OLLAMA_MODEL or n.startswith(OLLAMA_MODEL + ":") for n in names)
        return {"ok": ok, "url": OLLAMA_URL, "model": OLLAMA_MODEL,
                "detail": "model available" if ok else f"model not in {names}"}
    except Exception as exc:  # noqa: BLE001 - report, never crash a health check
        return {"ok": False, "url": OLLAMA_URL, "model": OLLAMA_MODEL, "detail": type(exc).__name__}
