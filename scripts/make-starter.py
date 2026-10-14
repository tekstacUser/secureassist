#!/usr/bin/env python3
"""Create the STUDENT starter copy from this reference solution (INSTRUCTOR tool).

    python3 scripts/make-starter.py

Writes dist/secureassist-starter/ INSIDE this project (git-ignored). In that
copy, only the student-task parts are removed and replaced by TODO hints:

  Task 2  app/backend/guardrails.py        check_input / check_output bodies
  Task 3  app/frontend/Dockerfile, app/backend/Dockerfile
  Task 4  k8s/backend-deployment.yaml, k8s/backend-service.yaml,
          k8s/frontend-deployment.yaml, k8s/frontend-service.yaml (key values)

Everything else (frontend, Ollama client, MCP server + client, monitoring,
Langfuse Dockerfile and manifests, scripts, docs) is copied unchanged as
predefined starter code.
"""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "secureassist-starter"
SKIP = {"dist", "reports", ".git", "__pycache__", ".scannerwork"}

GUARDRAIL_HINTS = {
    "check_input": '''    # TODO (Task 2a): implement the input guardrail. Return GuardrailDecision(allowed, reason, category).
    #  1. not a str                          -> (False, ..., "invalid_type")
    #  2. empty after .strip()               -> (False, ..., "empty")
    #  3. longer than MAX_PROMPT_CHARS       -> (False, ..., "too_long")   mention the limit in the reason
    #  4. any _SECRET_REQUEST_RE matches     -> (False, ..., "secret_request")
    #  5. any _INJECTION_RE matches          -> (False, ..., "prompt_injection")
    #  6. otherwise                          -> (True, "Input passed all guardrail checks.", "ok")
    raise NotImplementedError("Task 2a: implement check_input")''',
    "check_output": '''    # TODO (Task 2b): implement the output guardrail. Return (GuardrailDecision, safe_text).
    #  1. not a str                          -> (False, ..., "invalid_response"), ""
    #  2. remove control chars (_CONTROL_CHARS_RE), strip; empty -> "invalid_response", ""
    #  3. longer than MAX_RESPONSE_CHARS     -> cut and append " ...[truncated]"
    #  4. redact_secrets(text); if anything was redacted -> (True, "<n> secret-like value(s) redacted.", "redacted")
    #  5. otherwise                          -> (True, "Response passed output checks.", "ok"), text
    raise NotImplementedError("Task 2b: implement check_output")''',
}

DOCKERFILE_STARTER = '''# {image} - STUDENT TASK (Task 3)
# Build from the project root:  docker build -t {image} {context}
#
# TODO 1: start from a lightweight Python 3.12 image (slim variant)
# TODO 2: set PYTHONDONTWRITEBYTECODE=1 and PYTHONUNBUFFERED=1
# TODO 3: set WORKDIR /app, copy requirements.txt FIRST and pip install it with --no-cache-dir
# TODO 4: copy only the application files: {files}
# TODO 5: create a non-root user with UID 10001 and switch to it (USER 10001)
# TODO 6: EXPOSE {port}
# TODO 7: CMD gunicorn bound to 0.0.0.0:{port}, 2 workers, 4 threads,
#         --timeout {timeout}, --access-logfile -, app:app
'''


def copy_tree():
    if OUT.exists():
        shutil.rmtree(OUT)

    def ignore(_dir, names):
        return [n for n in names if n in SKIP or n.endswith(".pyc")]

    shutil.copytree(ROOT, OUT, ignore=ignore)


def strip_guardrails():
    path = OUT / "app/backend/guardrails.py"
    text = path.read_text()
    for name, hint in GUARDRAIL_HINTS.items():
        pattern = rf"    # >>> STUDENT TASK START: {name}\n.*?    # <<< STUDENT TASK END: {name}"
        text, n = re.subn(pattern, f"    # >>> STUDENT TASK START: {name}\n{hint}\n    # <<< STUDENT TASK END: {name}",
                          text, flags=re.S)
        assert n == 1, f"marker for {name} not found"
    path.write_text(text)


def stub_dockerfiles():
    (OUT / "app/frontend/Dockerfile").write_text(DOCKERFILE_STARTER.format(
        image="secureassist-frontend:1.0", context="app/frontend", port=8091, timeout=160,
        files="app.py, templates/, static/"))
    (OUT / "app/backend/Dockerfile").write_text(DOCKERFILE_STARTER.format(
        image="secureassist-backend:1.0", context="app/backend", port=8092, timeout=150,
        files="app.py guardrails.py ollama_client.py mcp_client.py monitoring.py"))


def stub_manifests():
    probe_block = re.compile(r"          (readinessProbe|livenessProbe):.*?(?=\n          [a-zA-Z]|\Z)", re.S)
    edits = {
        "k8s/backend-deployment.yaml": [
            (r'value: "http://secureassist-mcp:8093/mcp"', 'value: "TODO-mcp-service-url"   # TODO: http://<mcp Service>:<port>/mcp'),
            (r'value: "http://host.minikube.internal:11434"', 'value: "TODO-ollama-url"   # TODO: Ollama URL reachable FROM a Pod'),
            (r"runAsNonRoot: true", "runAsNonRoot: false   # TODO: run as non-root (UID 10001)"),
        ],
        "k8s/frontend-deployment.yaml": [
            (r'value: "http://secureassist-backend:8092"', 'value: "TODO-backend-service-url"   # TODO: http://<backend Service>:<port>'),
            (r"runAsNonRoot: true", "runAsNonRoot: false   # TODO: run as non-root (UID 10001)"),
        ],
        "k8s/backend-service.yaml": [(r"port: 8092", "port: 1   # TODO: Service port for the backend")],
        "k8s/frontend-service.yaml": [(r"port: 8091", "port: 1   # TODO: Service port for the frontend")],
    }
    for rel, subs in edits.items():
        path = OUT / rel
        text = path.read_text()
        for old, new in subs:
            assert old in text or re.search(old, text), f"{old} not in {rel}"
            text = re.sub(old, new, text, count=1)
        if "deployment" in rel:
            text = probe_block.sub("          # TODO: add a \\1 (see docs/student-task.md)", text)
        path.write_text(text)


if __name__ == "__main__":
    copy_tree()
    strip_guardrails()
    stub_dockerfiles()
    stub_manifests()
    print(f"Student starter written to {OUT.relative_to(ROOT)}")
    print("Student files now contain TODO hints: guardrails.py, 2 Dockerfiles, 4 k8s manifests")
