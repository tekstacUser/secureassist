# SecureAssist — Student Tasks

Total hands-on time: **70 minutes** (+5 min buffer). Read time before starting: 10–15 minutes.

## What is predefined (do not modify)
| Area | Files |
|---|---|
| Frontend | `app/frontend/app.py`, `templates/index.html`, `static/style.css`, `static/chat.js`, `requirements.txt` |
| Backend (except guardrails) | `app/backend/app.py`, `ollama_client.py`, `mcp_client.py`, `monitoring.py`, `requirements.txt` |
| MCP server | `mcp_server/server.py`, `requirements.txt`, `Dockerfile` |
| Langfuse | `langfuse/Dockerfile`, `langfuse/.env.example` |
| Kubernetes | `k8s/namespace.yaml`, `k8s/mcp-*.yaml`, `k8s/langfuse-*.yaml`, `k8s/secrets-template.yaml` |
| CI/CD | `cicd/Jenkinsfile`, `sonar-project.properties` |
| Scripts | everything in `scripts/` |

## Task 1 — Environment checks and Langfuse secrets file (5 min)
Run `bash scripts/check-environment.sh`. Create `langfuse/.env` from `langfuse/.env.example` with random values (exact command in README section F, Task 1).
**Expected:** `RESULT: 0 failure(s)` (especially *Ollama from inside Minikube* and *default StorageClass*); `langfuse/.env complete`; `git check-ignore -v langfuse/.env` prints a rule.

## Task 2 — Guardrails (10 min) — `app/backend/guardrails.py`
Implement the two functions between the `STUDENT TASK START/END` markers. The rule lists (`SECRET_REQUEST_PATTERNS`, `PROMPT_INJECTION_PATTERNS`, `SECRET_OUTPUT_PATTERNS`) and compiled regexes are provided.

`check_input(message) -> GuardrailDecision`, in this order:
1. not a `str` → `(False, reason, "invalid_type")`
2. empty after `strip()` → `"empty"`
3. longer than `MAX_PROMPT_CHARS` (default 1000) → `"too_long"`, reason must mention the limit
4. any `_SECRET_REQUEST_RE` matches → `"secret_request"`
5. any `_INJECTION_RE` matches → `"prompt_injection"`
6. otherwise `(True, "Input passed all guardrail checks.", "ok")`

`check_output(response) -> (GuardrailDecision, safe_text)`:
1. not a `str` → `(False, ..., "invalid_response"), ""`
2. remove control characters, strip; empty → `"invalid_response"`, `""`
3. longer than `MAX_RESPONSE_CHARS` → cut and append `" ...[truncated]"`
4. `redact_secrets(text)`; if count > 0 → `(True, "<n> secret-like value(s) redacted.", "redacted")`
5. otherwise `(True, "Response passed output checks.", "ok"), text`

**Check:** run the five `python3 -c "import guardrails as g; ..."` commands in README section F, Task 2.
**Expected:** `ok`, `secret_request`, `prompt_injection`, `empty`, `redacted`. After deployment, `scripts/verify-deployment.sh` re-checks these rules inside the running backend Pod.

> Why order matters: type before `.strip()` (avoid crashes), length before regex (avoid slow regex on huge input).
> Limitation: keyword/regex rules are a first layer only. Rephrasing, other languages or encodings can bypass them; that is why tools are also allow-listed and read-only and output is never executed.

## Task 3 — Dockerfiles (10 min) — `app/frontend/Dockerfile`, `app/backend/Dockerfile`
Use `mcp_server/Dockerfile` as a model. Each must:
* start `FROM python:3.12-slim`;
* set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`;
* copy `requirements.txt` first and `pip install --no-cache-dir -r requirements.txt` (layer caching);
* copy only application files (frontend: `app.py templates/ static/`; backend: `app.py guardrails.py ollama_client.py mcp_client.py monitoring.py`);
* create user UID `10001` and `USER 10001`;
* `EXPOSE 8091` (frontend) / `EXPOSE 8092` (backend);
* `CMD ["gunicorn","--bind","0.0.0.0:<port>","--workers","2","--threads","4","--timeout","<160|150>","--access-logfile","-","app:app"]`.

Then build all four project images (including the predefined `langfuse/Dockerfile`), pull `postgres:16.4-alpine`, and load all five into Minikube.
**Expected:** `docker image inspect` shows `User=10001` (or `1001` for Langfuse) and the right port; no `.env` inside any image.

## Task 4 — Kubernetes (15 min)
Files: `k8s/backend-deployment.yaml`, `k8s/backend-service.yaml`, `k8s/frontend-deployment.yaml`, `k8s/frontend-service.yaml`. Use `k8s/mcp-deployment.yaml` as a model.

| Item | Backend | Frontend |
|---|---|---|
| image / pullPolicy | `secureassist-backend:1.0` / `Never` | `secureassist-frontend:1.0` / `Never` |
| containerPort | 8092 | 8091 |
| env | `MCP_SERVER_URL=http://secureassist-mcp:8093/mcp`, `OLLAMA_URL=http://host.minikube.internal:11434` (or the URL check-environment proved), `OLLAMA_MODEL=phi3:mini`, `LANGFUSE_HOST=http://secureassist-langfuse:3031`, `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` from Secret `secureassist-langfuse` (`optional: true`) | `BACKEND_URL=http://secureassist-backend:8092` |
| readinessProbe | `GET /ready` | `GET /health` |
| livenessProbe | `GET /health` | `GET /health` |
| securityContext | `runAsNonRoot: true`, `runAsUser: 10001`, no privilege escalation, drop ALL, read-only root FS + `/tmp` emptyDir | same |
| Service | ClusterIP `secureassist-backend`, port 8092 → targetPort `http` | ClusterIP `secureassist-frontend`, port 8091 → `http` |

Create the Secret from `langfuse/.env`, then deploy in order: database → Langfuse → MCP → backend → frontend.
**Expected:** five Deployments `1/1`, PVC `Bound`; `curl localhost:8092/ready?deep=true` → `ready: true` with MCP, Ollama and Langfuse ok.

## Task 5 — Verify MCP and Langfuse (10 min)
Run discovery, two tool calls and two rejected calls, read the MCP server and backend logs, send browser tests 3 and 4, then find the trace in Langfuse (README F Task 5, G and H).
**Expected:** 2 tools discovered; FAQ-001 returned; `run_shell` → `mcp_tool_not_allowed`; `payroll-db` → `mcp_invalid_arguments`; green MCP badges; trace visible in project SecureAssist-Helpdesk.

## Task 6 — Jenkins + SonarQube (10 min)
Create the `secureassist` pipeline job (Script Path `cicd/Jenkinsfile`), build with parameters, read the console, the SonarQube quality gate and the archived `reports/`. Write `reports/jenkins-result.md`.
**Expected:** build SUCCESS with stage 5 quality gate `OK`. If a stage fails because of missing permissions, record the clear failure message and ask the administrator; do not work around it with `sudo`.

## Task 7 — Incident drill (5 min)
Plain `kubectl` commands (README section I, full runbook in `docs/incident-response.md`): set a wrong MCP hostname with `kubectl set env` → watch the rollout get stuck → find the cause in events, logs, `/ready` and the Pod environment → `kubectl rollout undo` → wait for `rollout status` → restart the port-forwards → `bash scripts/verify-deployment.sh` (PASS) → write `reports/incident-record.md`. Each step appends a timestamped line to `reports/incident-timeline.log`.
**Expected:** rollout stuck while the fault is active; healthy again after the rollback; record with no TODO.

## Task 8 — Governance and final verification (5 min)
Run `bash scripts/verify-deployment.sh` until **OVERALL: PASS**, then tick `docs/governance-checklist.md`.
