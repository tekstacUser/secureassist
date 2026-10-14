# SecureAssist — Architecture

## 1. Logical architecture
All project components run as Pods in one Kubernetes namespace, so they share the same cluster network and find each other by Service name. Only the existing, shared Ollama stays on the VM.
```text
 VM (lab host)                                   Minikube cluster — namespace "secureassist"
 ┌─────────────────────────────────┐             ┌───────────────────────────────────────────────────────────────────┐
 │ Browser ─► :8091 port-forward ───┼────────────►│ svc secureassist-frontend:8091 ─► Pod frontend (Flask)             │
 │ Browser ─► :3031 port-forward ───┼──────┐      │                                     │ server-side proxy           │
 │                                 │      │      │                                     ▼                             │
 │ Ollama :11434 (phi3:mini) ◄──────┼──┐   │      │ svc secureassist-backend:8092  ─► Pod backend (Flask)               │
 │ Jenkins :3030 ─► SonarQube       │  │   │      │   guardrails · ollama_client · mcp_client · monitoring              │
 └─────────────────────────────────┘  │   │      │        │ MCP Streamable HTTP          │ Langfuse SDK                 │
   host.minikube.internal = the VM     │   │      │        ▼                              ▼                              │
                                       │   │      │ svc secureassist-mcp:8093      svc secureassist-langfuse:3031 ◄──────┼── :3031
                                       │   │      │  Pod MCP server (FastMCP)       Pod Langfuse (UI + API)              │
                                       │   └──────┼─►                                      │                             │
                                       │          │                                svc secureassist-langfuse-db:5432     │
                                       └──────────┤ backend ─► host.minikube.internal   Pod PostgreSQL + PVC 1 GiB       │
                                                  └───────────────────────────────────────────────────────────────────┘
```

## 2. Component responsibilities
| Component | Responsibility | Does NOT do |
|---|---|---|
| **Frontend** (`app/frontend`) | Chat page, page-session history, loading/error states, badges for MCP tools and guardrails; proxies `POST /api/chat` to the backend | call Ollama/MCP, hold secrets, render HTML from answers (uses `textContent`) |
| **Backend** (`app/backend`) | Validate JSON, input guardrail, route (status/faq/llm), MCP calls, Ollama call, output guardrail, Langfuse trace, JSON logs, `/health` `/ready` | execute model output, call tools outside the allowlist |
| **guardrails.py** | Explicit allow/block decisions with reasons; secret redaction; response validation | claim complete prompt-injection protection |
| **mcp_client.py** | MCP session, tool discovery, allowlist + argument validation, timeouts, error categories | call arbitrary tools or REST endpoints |
| **MCP server** (`mcp_server`) | Two read-only tools over predefined data; DNS-rebinding protection | run commands, read files, report real infrastructure health |
| **monitoring.py** | Metadata-only Langfuse traces; reports `not_configured` honestly | send prompts, answers, keys or headers |
| **Langfuse** (`langfuse/Dockerfile`, `k8s/langfuse-*.yaml`) | Trace storage and UI; organisation, project, API keys and admin created on first start | receive prompt text |
| **PostgreSQL** (`postgres:16.4-alpine`) | Langfuse database on a PersistentVolumeClaim | accept connections from outside the cluster |
| **Ollama** (existing, VM) | `phi3:mini` inference | — (not deployed by us) |
| **Jenkins + SonarQube** (existing) | Code checks, static analysis + quality gate, build, deploy, verify | — |

## 3. Ports
| Component | Container port | Service (ClusterIP) | VM port (port-forward) | Bound on VM |
|---|---:|---|---:|---|
| Frontend | 8091 | `secureassist-frontend:8091` | 8091 | `0.0.0.0` (browser) |
| Backend | 8092 | `secureassist-backend:8092` | 8092 | `127.0.0.1` (checks only) |
| MCP server | 8093 | `secureassist-mcp:8093` | 8093 | `127.0.0.1` (checks only) |
| Langfuse | 3000 | `secureassist-langfuse:3031` | 3031 | `0.0.0.0` (Langfuse UI) |
| PostgreSQL | 5432 | `secureassist-langfuse-db:5432` | — | not exposed |
| Ollama | — | — | 11434 | existing; Pods use `http://host.minikube.internal:11434` |
| Jenkins | — | — | 3030 | existing |

* **Container port** — where the process listens inside the container.
* **Service port** — stable cluster-internal address `name:port` (DNS by CoreDNS); routes only to Ready Pods. Langfuse shows that the two can differ: Service 3031 → container 3000.
* **Host port** — what you type in the browser; created by `kubectl port-forward` (four commands in README Task 4). ClusterIP + port-forward keeps the VM port equal to the assigned port (a NodePort would be 30000–32767).

## 4. Request flow (`POST /chat`)
1. Browser → `POST /api/chat` on the frontend (8091).
2. Frontend forwards only `{"message": ...}` to `http://secureassist-backend:8092/chat`.
3. Backend validates JSON → **input guardrail**. Blocked → HTTP 400, **no** MCP or Ollama call.
4. Route selection (transparent keyword rules in `app.py`):
   * **status** — mentions status/down/outage + an approved service → MCP `get_service_status`; the tool result is the answer.
   * **faq** — mentions a helpdesk topic → MCP `search_support_faq`; results become context for `phi3:mini`. If Ollama fails, the approved FAQ text is shown (`degraded: true`).
   * **llm** — everything else → `phi3:mini`.
5. **Output guardrail** — strip control characters, length cap, redact secrets, reject empty/invalid.
6. Langfuse trace to `http://secureassist-langfuse:3031` (metadata only) + one JSON log line `"event": "chat"`.
7. Response contains `answer`, `route`, `tools_used`, `trace_id`, `duration_ms`, `monitoring`, `degraded` or `error.dependency`.

## 5. MCP flow
```text
backend mcp_client.call_tool("search_support_faq", {"query": "..."})
  1. name in ALLOWED_TOOLS?                          no  -> MCPError mcp_tool_not_allowed (no network)
  2. validate arguments                              bad -> MCPError mcp_invalid_arguments (no network)
  3. POST http://secureassist-mcp:8093/mcp  initialize           (JSON-RPC 2.0, protocol negotiated by the SDK)
  4. POST .../mcp  tools/list   -> tool offered by server?        no  -> mcp_tool_not_offered
  5. POST .../mcp  tools/call   {"name": ..., "arguments": ...}
  6. result.isError? -> mcp_tool_error ; parse JSON result ; timeout 10 s -> mcp_timeout
```
* SDK `mcp==1.30.0` on both sides. Transport Streamable HTTP, `stateless_http=True`, `json_response=True`: every call is self-contained, so no sticky sessions are needed behind the Service.
* Server-side protection: only Host headers for the Service name, its FQDNs, `localhost` and `127.0.0.1` are accepted (DNS-rebinding protection); tools validate their own input again.

## 6. Langfuse flow
```text
backend monitoring.record_chat() ── HTTP (SDK, background) ──► secureassist-langfuse:3031 /api/public/ingestion
Langfuse Pod ── DATABASE_HOST=secureassist-langfuse-db:5432 ──► PostgreSQL Pod ──► PVC secureassist-langfuse-db-data
Secret secureassist-langfuse ─► PostgreSQL (POSTGRES_*), Langfuse (all keys), backend (2 API keys only)
```
Startup order: Secret → database → Langfuse (migrations, then headless initialisation) → backend. The backend does not wait for Langfuse: if Langfuse is down, chat still works and traces are dropped with an error log.

## 7. Health and readiness
| Endpoint / probe | Meaning | Used by |
|---|---|---|
| backend `/health` | process alive | livenessProbe |
| backend `/ready` | config valid **and** MCP Service hostname resolves | readinessProbe (bad MCP hostname → Pod never Ready → rollout stops; old Pod keeps serving because `maxUnavailable: 0`) |
| backend `/ready?deep=true` | also live MCP `tools/list`, Ollama model check, Langfuse key check (informational) | humans, verify script |
| frontend `/health`, `/ready` | alive / backend reachable | probes, humans |
| MCP `/health` | server alive | probes |
| Langfuse `/api/public/health` | server alive | startupProbe (5 min for migrations), readiness, liveness |
| PostgreSQL `pg_isready` | database accepts connections | readiness, liveness |

## 8. Security controls (defence in depth)
Guardrails (input + output) · MCP allowlist + argument validation + read-only tools · model output never executed (checked by the pipeline's code stage) · `textContent` rendering in the browser · every Pod non-root, no privilege escalation, all capabilities dropped, no service-account token · project app Pods with read-only root filesystem · credentials only from the Kubernetes Secret or Jenkins credentials, never in images or YAML · database not exposed outside the cluster · no prompt content in monitoring · SonarQube quality gate before build.

## 9. CI/CD flow
`Checkout → checks (docker/kubectl/minikube permissions) → code checks (syntax, no-exec, secret scan) → SonarQube analysis → quality gate → build 4 images + pull postgres → minikube image load → manifest validation → deploy (Secret must exist, rollouts) → verify-deployment.sh → archive reports/`. Any failure stops the pipeline; nothing is marked green without a real check.
