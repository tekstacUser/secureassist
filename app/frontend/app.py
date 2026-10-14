"""SecureAssist frontend (PREDEFINED).

Serves the chat page on port 8091 and PROXIES chat requests to the backend
on the server side. The browser only ever talks to this frontend; it never
connects to the backend (8092) or MCP server (8093) directly.

  GET  /           chat page
  POST /api/chat   -> BACKEND_URL/chat  (server-side proxy)
  GET  /health     liveness of the frontend itself
  GET  /ready      frontend can reach the backend /health

Environment:
  BACKEND_URL      default http://secureassist-backend:8092 (Kubernetes Service DNS)
  PROXY_TIMEOUT    seconds to wait for the backend (default 150, phi3 on CPU is slow)
"""

import os

import requests
from flask import Flask, jsonify, render_template, request

BACKEND_URL = os.getenv("BACKEND_URL", "http://secureassist-backend:8092").rstrip("/")
PROXY_TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "150"))
MAX_BODY_BYTES = 16 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/chat")
def proxy_chat():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        return jsonify({"error": {"category": "invalid_json",
                                  "message": "Send JSON like {\"message\": \"...\"}"}}), 400
    try:
        resp = requests.post(f"{BACKEND_URL}/chat", json={"message": data["message"]},
                             timeout=(5, PROXY_TIMEOUT))
    except requests.exceptions.Timeout:
        return jsonify({"error": {"category": "backend_timeout", "dependency": "backend",
                                  "message": "The backend took too long to answer."}}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": {"category": "backend_unreachable", "dependency": "backend",
                                  "message": "The SecureAssist backend is unreachable."}}), 502
    try:
        body = resp.json()
    except ValueError:
        return jsonify({"error": {"category": "backend_invalid_response", "dependency": "backend",
                                  "message": f"Backend returned HTTP {resp.status_code} without JSON."}}), 502
    return jsonify(body), resp.status_code


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "secureassist-frontend"})


@app.get("/ready")
def ready():
    try:
        ok = requests.get(f"{BACKEND_URL}/health", timeout=3).status_code == 200
    except requests.RequestException:
        ok = False
    return jsonify({"ready": ok, "backend_url": BACKEND_URL}), (200 if ok else 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("FRONTEND_PORT", "8091")))
