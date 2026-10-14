# Langfuse for SecureAssist — Pods in the `secureassist` namespace

Langfuse runs inside Kubernetes, in the same namespace and cluster network as the frontend, backend and MCP server. Nothing runs outside the cluster except the existing Ollama.

| Workload | Image | Service (in-cluster DNS) | Access from the VM |
|---|---|---|---|
| `secureassist-langfuse` (UI + API) | `secureassist-langfuse:1.0`, built from `langfuse/Dockerfile` | `secureassist-langfuse:3031` → container 3000 | `kubectl port-forward` on **3031** (all interfaces) |
| `secureassist-langfuse-db` (PostgreSQL) | `postgres:16.4-alpine` (official) | `secureassist-langfuse-db:5432` | none (internal only) |

The database is stored on the PersistentVolumeClaim `secureassist-langfuse-db-data` (1 GiB, Minikube default StorageClass).

The backend sends traces to `http://secureassist-langfuse:3031` with the Python SDK `langfuse==2.60.10` (`app/backend/monitoring.py`).

**Version choice.** Langfuse v2 needs only these two workloads, which fits a lab VM that already runs Minikube, Jenkins and Ollama. Langfuse v3 would add a worker, ClickHouse, Redis and MinIO. Langfuse v2 no longer receives security updates, so use it only on the lab's internal network.

## Files

| File | In Git? | Purpose |
|---|---|---|
| `langfuse/Dockerfile` | yes | `FROM langfuse/langfuse:2` plus non-secret settings (port, telemetry off, sign-up off, organisation/project names, numeric non-root user) |
| `langfuse/.env.example` | yes | template for all secrets, `REPLACE_ME` placeholders only |
| `langfuse/.env` | **no** (git-ignored) | real secrets, created in Task 1 |
| `k8s/langfuse-db-deployment.yaml` | yes | PVC + PostgreSQL Deployment |
| `k8s/langfuse-db-service.yaml` | yes | Service on 5432 |
| `k8s/langfuse-deployment.yaml` | yes | Langfuse Deployment with startup, readiness and liveness probes |
| `k8s/langfuse-service.yaml` | yes | Service on 3031 |

Secrets are **not** baked into the image. They are stored in the Kubernetes Secret `secureassist-langfuse`, created from `langfuse/.env`:

| Workload | What it reads from the Secret |
|---|---|
| PostgreSQL | `POSTGRES_*` |
| Langfuse | all keys |
| Backend | only `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` |

## 1. Create the secrets file (Task 1)

```bash
cp langfuse/.env.example langfuse/.env
# fill every REPLACE_ME with random values - exact sed + openssl command in README section F, Task 1
grep -E '^[^#]*REPLACE_ME' langfuse/.env || echo "langfuse/.env complete"
```

## 2. Build and load the images (Task 3)

```bash
docker build -t secureassist-langfuse:1.0 langfuse
docker pull postgres:16.4-alpine
minikube image load secureassist-langfuse:1.0 --overwrite=true
minikube image load postgres:16.4-alpine
```

## 3. Create the Secret and deploy (Task 4)

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n secureassist create secret generic secureassist-langfuse \
  --from-env-file=langfuse/.env --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/langfuse-db-deployment.yaml -f k8s/langfuse-db-service.yaml
kubectl apply -f k8s/langfuse-deployment.yaml -f k8s/langfuse-service.yaml
kubectl -n secureassist rollout status deployment/secureassist-langfuse-db --timeout=180s
kubectl -n secureassist rollout status deployment/secureassist-langfuse --timeout=420s
```

On first start, Langfuse runs its database migrations (1–3 minutes). It then creates the following automatically (headless initialisation):

| Resource | Value |
|---|---|
| Organisation | `secureassist-org` |
| Project | `SecureAssist-Helpdesk` (id `secureassist`) |
| API keys | the two keys from `langfuse/.env` |
| Admin user | `admin@secureassist.local`, password from `langfuse/.env` |

Sign-up is disabled, so only that admin user can log in.

## 4. Open the UI

```bash
nohup kubectl -n secureassist port-forward --address 0.0.0.0 svc/secureassist-langfuse 3031:3031 >/dev/null 2>&1 &
curl -s http://localhost:3031/api/public/health; echo
grep LANGFUSE_INIT_USER_PASSWORD langfuse/.env     # admin password
```

Open `http://localhost:3031` on the VM, or `http://<VM-IP>:3031` from another machine.

`NEXTAUTH_URL` is set to `http://localhost:3031` in `k8s/langfuse-deployment.yaml`. If login redirects go to the wrong address when you browse from another machine, change it to `http://<VM-IP>:3031` and re-apply the manifest.

## 5. Check the backend connection

```bash
curl -s http://localhost:8092/health; echo         # "monitoring": "configured"
curl -s "http://localhost:8092/ready?deep=true" | python3 -c "import sys,json; print(json.load(sys.stdin)['checks']['langfuse'])"
```

The second command should show `'ok': True, 'detail': 'keys accepted'`. That result comes from a real call from the backend Pod to the Langfuse Service.

## 6. What is recorded (and what is not)

Each chat request creates one trace named `secureassist-chat`. Its ID is the `trace_id` shown in the chat response.

- **Metadata:** `trace_id`, `model`, `route`, `duration_ms`, `success`, `outcome`, `guardrail_input`, `guardrail_output`, `mcp_tool`, `mcp_outcome`, `error_category`, `degraded`, `message_chars`.
- **Tags:** `secureassist`, `route:<route>`, and `success` or `failure`.
- **Steps (observations):** `guardrail-input`, `mcp:<tool>`, `ollama-chat` (a generation with model name and latency), and `guardrail-output`. Failures are marked with level `ERROR` or `WARNING`.

**Not recorded:** prompt text, answer text, API keys, passwords, authorization headers.

## 7. Prove a trace was delivered

`monitoring: queued` in a chat response only means the SDK accepted the trace for sending. To prove it reached Langfuse, fetch it back:

```bash
set -a; . ./langfuse/.env; set +a
curl -s -o /dev/null -w '%{http_code}\n' -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3031/api/public/traces/<TRACE_ID>"
```

- `200` means the trace exists.
- `404` straight away is normal, because traces are processed in the background. Retry after 10–30 seconds.

`scripts/verify-deployment.sh` does this automatically, reading the keys from the Kubernetes Secret.

## 8. Find a failure or latency issue

- **Latency:** sort traces by *Latency* and open the slowest. The `ollama-chat` bar shows model time compared with MCP time.
- **Failures:** filter by tag `failure` or by metadata `error_category` (for example `mcp_unreachable` during the incident drill).
- **Guardrail activity:** filter by `guardrail_input` = `secret_request` or `prompt_injection`.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `CreateContainerConfigError` | Secret missing or a key missing | re-create the Secret from a complete `langfuse/.env` |
| Langfuse Pod not Ready for several minutes | migrations still running, or database not Ready | `kubectl -n secureassist logs deploy/secureassist-langfuse`; check `secureassist-langfuse-db` |
| Database Pod `Pending` | PVC not bound (no default StorageClass) | `kubectl -n secureassist get pvc`; administrator enables the Minikube storage provisioner |
| Langfuse `OOMKilled` | memory limit 1 GiB reached, or the node is full | `kubectl describe pod`; free node memory (do not raise limits without checking capacity) |
| API keys rejected | Secret changed after the first start (keys are created only once) | instructor-approved reset: `kubectl -n secureassist delete deployment secureassist-langfuse secureassist-langfuse-db`, `kubectl -n secureassist delete pvc secureassist-langfuse-db-data`, then re-apply |
| Backend says `not_configured` | Secret created after the backend started | `kubectl -n secureassist rollout restart deployment/secureassist-backend` |
| Port 3031 busy on the VM | old port-forward or another process | `pgrep -af "secureassist port-forward"`, `ss -ltnp \| grep :3031` |
