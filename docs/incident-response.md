# SecureAssist — Incident Response Drill (Task 7, 5 minutes)

Run every command on the VM, in the project folder. The drill only changes Deployments in the `secureassist` namespace and can be fully reversed: no namespace is deleted, no shared service is stopped, and no system configuration is changed.

Each step also writes one line with a UTC timestamp to `reports/incident-timeline.log`. That log is your evidence.

## What the drill does

A faulty release changes the backend's MCP server address to `http://secureassist-mcp-typo:8093/mcp`, a hostname that does not exist.

The backend's readiness check (`/ready`) tests whether the MCP hostname resolves, so the new backend Pod never becomes Ready. Kubernetes keeps the old, healthy Pod running (`maxUnavailable: 0`), so users are not affected, but the release is stuck.

You then:

1. find the cause from the rollout, events, logs, `/ready` and the Pod's environment;
2. roll the release back;
3. verify the system again;
4. write an incident record.

## Step 1 — Inject the faulty configuration

```bash
mkdir -p reports
echo "$(date -u +%FT%TZ) INJECT: MCP_SERVER_URL=http://secureassist-mcp-typo:8093/mcp" >> reports/incident-timeline.log

kubectl -n secureassist set env deployment/secureassist-backend \
  MCP_SERVER_URL=http://secureassist-mcp-typo:8093/mcp
kubectl -n secureassist annotate deployment/secureassist-backend \
  kubernetes.io/change-cause="INCIDENT DRILL: wrong MCP hostname" --overwrite
```

## Step 2 — Observe the failure

```bash
# the rollout does not finish (expected to time out)
kubectl -n secureassist rollout status deployment/secureassist-backend --timeout=60s
echo "$(date -u +%FT%TZ) DETECT: backend rollout did not complete" >> reports/incident-timeline.log

# a new backend Pod is stuck at READY 0/1 next to the old 1/1 Pod
kubectl -n secureassist get pods -l app.kubernetes.io/name=secureassist-backend
```

Copy the name of the Pod that shows `0/1` into a variable. Replace `<new-pod-name>` with the real name:

```bash
NEW_POD=<new-pod-name>
```

## Step 3 — Identify the affected dependency

```bash
# events: "Readiness probe failed: HTTP probe failed with statuscode: 503"
kubectl -n secureassist describe pod "$NEW_POD" | sed -n '/Events/,$p'
kubectl -n secureassist get events --field-selector type=Warning --sort-by=.lastTimestamp | tail -n 10

# the readiness answer of the failing Pod: mcp_dns ok:false, host secureassist-mcp-typo
kubectl -n secureassist exec "$NEW_POD" -- python -c "import urllib.request as u
try: print(u.urlopen('http://127.0.0.1:8092/ready', timeout=5).read().decode())
except Exception as e: print(e.read().decode() if hasattr(e, 'read') else e)"

# the application log line
kubectl -n secureassist logs "$NEW_POD" --tail=50 | grep readiness_failed | tail -n 1

# the faulty value in the Pod environment
kubectl -n secureassist get pod "$NEW_POD" \
  -o jsonpath='{range .spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' | grep MCP_SERVER_URL

# the release history (the drill revision is the newest)
kubectl -n secureassist rollout history deployment/secureassist-backend

echo "$(date -u +%FT%TZ) DIAGNOSE: readiness 503, MCP hostname secureassist-mcp-typo does not resolve" >> reports/incident-timeline.log
```

Optionally, confirm the report in the verification script:

```bash
bash scripts/verify-deployment.sh     # expect FAIL on "Workload secureassist-backend ready"
```

## Step 4 — Roll back

```bash
echo "$(date -u +%FT%TZ) RECOVER: kubectl rollout undo" >> reports/incident-timeline.log
kubectl -n secureassist rollout undo deployment/secureassist-backend
```

## Step 5 — Wait until the workload is healthy

```bash
kubectl -n secureassist rollout status deployment/secureassist-backend --timeout=180s
kubectl -n secureassist get deployment secureassist-backend \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MCP_SERVER_URL")].value}'; echo
echo "$(date -u +%FT%TZ) RECOVERED: backend rollout complete" >> reports/incident-timeline.log
```

Expected: the rollout completes and the address is back to `http://secureassist-mcp:8093/mcp`.

Port-forwards are attached to the Pod that existed when they started, so restart them:

```bash
pkill -f "secureassist port-forward"
nohup kubectl -n secureassist port-forward --address 0.0.0.0   svc/secureassist-frontend 8091:8091 >/dev/null 2>&1 &
nohup kubectl -n secureassist port-forward --address 127.0.0.1 svc/secureassist-backend  8092:8092 >/dev/null 2>&1 &
nohup kubectl -n secureassist port-forward --address 127.0.0.1 svc/secureassist-mcp      8093:8093 >/dev/null 2>&1 &
nohup kubectl -n secureassist port-forward --address 0.0.0.0   svc/secureassist-langfuse 3031:3031 >/dev/null 2>&1 &
```

## Step 6 — Re-run the verification

```bash
bash scripts/verify-deployment.sh
```

Expected: `Workload secureassist-backend ready` is PASS again.

## Step 7 — Write the incident record

```bash
cat > reports/incident-record.md <<'EOF'
# Incident record - SecureAssist

| Field | Value |
|---|---|
| Incident ID | INC-SECUREASSIST-001 |
| Recorded by | TODO: your name |
| Detected at (UTC) | TODO: copy from reports/incident-timeline.log |
| Detection method | TODO: e.g. rollout status timed out, readiness probe 503 |
| Affected component | TODO |
| Affected dependency | TODO |
| Root cause | TODO |
| User impact | TODO: e.g. none - old Pod kept serving (maxUnavailable: 0) |
| Evidence (commands + key output) | TODO |
| Recovery action | TODO |
| Recovered at (UTC) | TODO |
| Final status | TODO: paste the OVERALL line of reports/verification-latest.md |
| Prevention | TODO: one improvement |
EOF

cat reports/incident-timeline.log
nano reports/incident-record.md       # replace every TODO
```

The record is complete when `grep -c TODO reports/incident-record.md` prints `0`.

## Optional — dependency outage visible in the UI (2 minutes)

```bash
kubectl -n secureassist scale deployment/secureassist-mcp --replicas=0
# Browser: "How do I reset my password?"  -> red "failed dependency: mcp-server"
# Browser: "Why should I lock my screen?"  -> still answered by phi3:mini (llm route)
kubectl -n secureassist logs deploy/secureassist-backend --tail=5 | grep mcp_unreachable

kubectl -n secureassist scale deployment/secureassist-mcp --replicas=1
kubectl -n secureassist rollout status deployment/secureassist-mcp --timeout=120s
```

This shows graceful degradation: only the features that need the failed dependency fail, and the error message names the dependency.

## Emergency reset

Use this if anything is left in a bad state. It restores the known-good values:

```bash
kubectl -n secureassist set env deployment/secureassist-backend MCP_SERVER_URL=http://secureassist-mcp:8093/mcp
kubectl -n secureassist scale deployment/secureassist-mcp --replicas=1
kubectl -n secureassist rollout status deployment/secureassist-mcp --timeout=120s
kubectl -n secureassist rollout status deployment/secureassist-backend --timeout=180s
```

## Isolated alternative (if live fault injection is not allowed in your lab)

This reproduces the same failure signal without changing the Deployment:

```bash
kubectl -n secureassist exec deploy/secureassist-backend -- python -c "
import socket
for host in ('secureassist-mcp', 'secureassist-mcp-typo'):
    try:
        socket.getaddrinfo(host, None); print(host, '-> resolves')
    except OSError:
        print(host, '-> DOES NOT RESOLVE (this is what /ready reports as mcp_dns ok:false)')"
```

Expected: the real Service name resolves and the typo does not, which is the same check the readiness probe performs. Use this as the evidence for Steps 3, 6 and 7.
