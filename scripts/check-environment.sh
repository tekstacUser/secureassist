#!/usr/bin/env bash
# SecureAssist environment check (PREDEFINED). Run on the VM, from the project root:
#
#   bash scripts/check-environment.sh
#
# It CONNECTS to each service instead of trusting configuration, and writes
# the real results to reports/environment-check.txt. It changes nothing:
# no sudo, no installs, no files outside the project directory.

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
mkdir -p reports
OUT="reports/environment-check.txt"
OLLAMA_VM_URL="${OLLAMA_VM_URL:-http://localhost:11434}"
OLLAMA_POD_URL="${OLLAMA_POD_URL:-http://host.minikube.internal:11434}"
JENKINS_URL="${JENKINS_URL:-http://localhost:3030}"
MODEL="phi3:mini"

FAILS=0
WARNS=0
{ echo "SecureAssist environment check - $(date -u +%Y-%m-%dT%H:%M:%SZ) - user $(id -un)"; echo; } > "$OUT"

pass() { printf '  [PASS] %s\n' "$*" | tee -a "$OUT"; }
warn() { printf '  [WARN] %s\n' "$*" | tee -a "$OUT"; WARNS=$((WARNS + 1)); }
bad()  { printf '  [FAIL] %s\n' "$*" | tee -a "$OUT"; FAILS=$((FAILS + 1)); }
hdr()  { printf '\n== %s\n' "$*" | tee -a "$OUT"; }
have() { command -v "$1" >/dev/null 2>&1; }

hdr "1. Local tools"
for t in python3 docker kubectl minikube curl git; do
  if have "$t"; then pass "$t found: $("$t" --version 2>/dev/null | head -n 1 || true)"; else bad "$t not found on PATH"; fi
done
if python3 -m pip --version >/dev/null 2>&1; then pass "pip: $(python3 -m pip --version | cut -d' ' -f1-2)"; else bad "pip not available (python3 -m pip)"; fi
if python3 -m venv --help >/dev/null 2>&1; then pass "python3 venv module available"; else bad "python3 venv module missing (ask the administrator)"; fi
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null \
  && pass "Python $PYV (>= 3.10 required for the MCP SDK)" || bad "Python $PYV is too old; 3.10+ needed"

hdr "2. Docker daemon"
if docker info >/dev/null 2>&1; then pass "Docker daemon reachable as $(id -un)"; else bad "Cannot talk to Docker daemon (is your user in the 'docker' group?)"; fi

hdr "3. Kubernetes / Minikube"
if minikube status >/dev/null 2>&1; then pass "Minikube is running (driver: $(minikube profile list -o json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["valid"][0]["Config"]["Driver"])' 2>/dev/null || echo unknown))"
else bad "Minikube is not running for this user (try: minikube start - existing profile only)"; fi
if kubectl cluster-info >/dev/null 2>&1; then pass "kubectl reaches the cluster (context: $(kubectl config current-context))"; else bad "kubectl cannot reach the cluster"; fi
SVCS="$(kubectl get svc -A 2>/dev/null || true)"
if grep -qi 'ollama' <<<"$SVCS"; then
  warn "Found an Ollama Service inside Kubernetes - if Ollama runs in-cluster, set OLLAMA_URL to that Service instead:"
  grep -i 'ollama' <<<"$SVCS" | tee -a "$OUT"
fi
SC="$(kubectl get storageclass 2>/dev/null || true)"
if grep -q '(default)' <<<"$SC"; then pass "default StorageClass present (needed for the Langfuse database volume)"
else bad "no default StorageClass - the Langfuse database volume cannot be created (minikube addons enable default-storageclass storage-provisioner)"; fi
ALLOC="$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.memory}' 2>/dev/null)"
[[ -n "$ALLOC" ]] && echo "     node allocatable memory: $ALLOC (all SecureAssist Pods request about 1.2 GiB)" | tee -a "$OUT"

hdr "4. Ollama from the VM ($OLLAMA_VM_URL)"
TAGS="$(curl -fsS -m 5 "$OLLAMA_VM_URL/api/tags" 2>/dev/null)"
if [[ -n "$TAGS" ]]; then
  pass "Ollama API answers on the VM"
  if grep -q "\"$MODEL\"" <<<"$TAGS" || grep -q "\"name\":\"$MODEL\"" <<<"$TAGS"; then pass "Model $MODEL is already downloaded"
  else bad "Model $MODEL not listed by Ollama (ask the administrator; this lab must not download models)"; fi
  echo "     Testing a real generation (can take up to 60s on CPU)..." | tee -a "$OUT"
  GEN="$(curl -fsS -m 90 "$OLLAMA_VM_URL/api/generate" -d "{\"model\":\"$MODEL\",\"prompt\":\"Reply with the single word OK.\",\"stream\":false,\"options\":{\"num_predict\":5}}" 2>/dev/null)"
  if grep -q '"response"' <<<"$GEN"; then pass "Real model response received: $(python3 -c 'import sys,json;print(json.loads(sys.stdin.read())["response"].strip()[:40])' <<<"$GEN")"
  else bad "Model did not answer within 90s"; fi
else
  bad "Ollama not reachable at $OLLAMA_VM_URL"
fi
if have ss; then
  BIND="$(ss -ltn 2>/dev/null | awk '$4 ~ /:11434$/ {print $4}' | head -n 1)"
  [[ -n "$BIND" ]] && echo "     Ollama listens on: $BIND" | tee -a "$OUT"
  if [[ "$BIND" == 127.0.0.1:* ]]; then
    warn "Ollama is bound to 127.0.0.1 only - Pods cannot reach it. Administrator fix: set OLLAMA_HOST=0.0.0.0 for the Ollama service and restart it."
  fi
fi

hdr "5. Ollama from inside Minikube ($OLLAMA_POD_URL) - this is the URL the backend Pod uses"
if minikube status >/dev/null 2>&1; then
  MKTAGS="$(minikube ssh -- "curl -fsS -m 5 $OLLAMA_POD_URL/api/tags" 2>/dev/null || true)"
  if grep -q "$MODEL" <<<"$MKTAGS"; then
    pass "Minikube node reaches Ollama at $OLLAMA_POD_URL and sees $MODEL"
  else
    bad "Minikube cannot reach $OLLAMA_POD_URL. See docs/troubleshooting.md 'Ollama connectivity'."
    echo "     host.minikube.internal resolves to: $(minikube ssh -- 'grep host.minikube.internal /etc/hosts' 2>/dev/null | awk '{print $1}')" | tee -a "$OUT"
  fi
else
  bad "Skipped: Minikube not running"
fi

hdr "6. Jenkins ($JENKINS_URL)"
CODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$JENKINS_URL/login")"
if [[ "$CODE" == "200" ]]; then pass "Jenkins UI answers (HTTP 200)"; else bad "Jenkins UI not reachable (HTTP $CODE)"; fi
if id jenkins >/dev/null 2>&1; then
  id -nG jenkins | grep -qw docker && pass "user 'jenkins' is in the docker group" \
    || warn "user 'jenkins' is NOT in the docker group - the pipeline's checks stage will fail until an administrator adds it"
fi

hdr "7. Langfuse secrets file (Langfuse itself is deployed as Pods in Task 4)"
if [[ -f langfuse/.env ]] && ! grep -qE '^[^#]*=.*REPLACE' langfuse/.env; then pass "langfuse/.env exists and has no placeholders (values not shown)"
else warn "langfuse/.env not created yet - you create it in Task 1 (README section F)"; fi
git check-ignore -q langfuse/.env 2>/dev/null && pass "langfuse/.env is git-ignored" || warn "not a git checkout yet, or langfuse/.env not ignored"

hdr "8. SonarQube (used by the Jenkins pipeline)"
if [[ -n "${SONAR_HOST_URL:-}" ]]; then
  SQ="$(curl -fsS -m 5 "$SONAR_HOST_URL/api/system/status" 2>/dev/null)"
  if grep -q '"status":"UP"' <<<"$SQ"; then pass "SonarQube UP at $SONAR_HOST_URL"; else bad "SonarQube not UP at $SONAR_HOST_URL ($SQ)"; fi
else
  warn "SONAR_HOST_URL not exported - Jenkins uses its own SonarQube configuration. To test from the VM: export SONAR_HOST_URL=http://<host>:<port>"
fi

hdr "9. SecureAssist ports on the VM (8091-8093 and 3031 should be free or used by our port-forwards)"
for p in 8091 8092 8093 3031; do
  if python3 - "$p" <<'EOF'
import socket, sys
s = socket.socket(); s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
EOF
  then
    if pgrep -f "port-forward.*:$p" >/dev/null 2>&1 || pgrep -f "port-forward.*$p:" >/dev/null 2>&1; then pass "port $p in use by a kubectl port-forward (expected after deployment)"
    else warn "port $p is used by another process - find it with: ss -ltnp | grep :$p"; fi
  else
    pass "port $p is free"
  fi
done

echo | tee -a "$OUT"
echo "RESULT: $FAILS failure(s), $WARNS warning(s). Report: $OUT" | tee -a "$OUT"
[[ "$FAILS" -eq 0 ]]
