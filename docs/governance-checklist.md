# SecureAssist — Governance and Evidence Checklist

Fill this in at the end of the lab. Every item must point to evidence produced by a **real command**. Evidence lives only in `reports/` inside the project. Do not type results by hand into report files that scripts generate.

Generate / refresh evidence (VM, project root):
```bash
bash scripts/check-environment.sh              # reports/environment-check.txt
bash scripts/verify-deployment.sh              # reports/verification-<ts>.md + verification-latest.md
```

| # | Control | How it is verified | Evidence | Done |
|---|---|---|---|---|
| 1 | **Source and dependency checks** | all Python dependencies pinned (`==`) in each `requirements.txt`; syntax check, no execution primitives, no committed secrets | Jenkins stage 3 console output and artifact `reports/code-checks.txt` | [ ] |
| 2 | **Static analysis / quality gate** | Jenkins stages 4–5 (SonarQube) | Jenkins build; `reports/sonar-quality-gate.txt` (archived artifact); `reports/jenkins-result.md` | [ ] |
| 3 | **Guardrail verification results** | rules checked inside the running backend Pod: allow normal, block empty / too long / secret request / injection, redact secrets, reject empty output | verification row "Guardrail rules (allow, block, redact, invalid)" | [ ] |
| 4 | **Guardrails in the running system** | blocked prompt through the UI path | verification row "Guardrail blocks prohibited input" | [ ] |
| 5 | **Secret-handling verification** | no keys in tracked files; `langfuse/.env` git-ignored; keys only in Secret `secureassist-langfuse`; no prompt text in Langfuse | verification row "No secrets committed"; `git check-ignore -v langfuse/.env` | [ ] |
| 6 | **Docker image build results** | 4 project images (non-root, correct ports) + official PostgreSQL image, all inside Minikube | `docker image inspect` output; Jenkins artifact `reports/images.txt`; verification rows "Image …" | [ ] |
| 7 | **Kubernetes deployment status** | 5 Deployments Ready in namespace `secureassist` (frontend, backend, MCP, Langfuse, PostgreSQL), non-root, not privileged, no duplicate Ollama | verification "Workload …" and "Pods non-root" rows; Jenkins artifact `reports/k8s-status.txt` | [ ] |
| 8 | **MCP tool allowlisting** | discovery returns exactly 2 approved tools; unknown tool rejected; invalid arguments rejected | verification rows "MCP tool discovery / invocation / allowlist" | [ ] |
| 9 | **Langfuse trace verification** | Langfuse healthy on 3031; trace fetched by ID from the Langfuse public API (not just "queued") | verification rows "Langfuse UI/API on 3031" and "Langfuse trace delivered" | [ ] |
| 10 | **Jenkins pipeline results** | real build with all stages green, or a clearly failing stage with a recorded reason | Jenkins build URL in `reports/jenkins-result.md`; archived `reports/` | [ ] |
| 11 | **Incident-response record** | drill executed with timestamps; record completed | `reports/incident-timeline.log`, `reports/incident-record.md` (no TODO) | [ ] |
| 12 | **Final application health** | full verification run | `reports/verification-latest.md` ends with `OVERALL: PASS` | [ ] |

## `reports/jenkins-result.md` template
```markdown
# Jenkins result
- Job: secureassist   Build number: <number>
- Result: <SUCCESS or FAILURE>
- SonarQube quality gate: <OK or ERROR>
- Build URL: http://<VM-IP>:3030/job/secureassist/<number>/
- Failed stage and reason (if any): <text>
```

## Rules for honest evidence
* A report must show the real status, its timestamp and failure details. `FAIL` and `NOT CONFIGURED` are acceptable answers when true; a fabricated `PASS` is not.
* Re-run the generating command instead of editing generated files.
* `NOT CONFIGURED` is only used for records that cannot exist in a Jenkins run (pipeline mode); explain it in the record.

## Sign-off
| Role | Name | Date | Notes |
|---|---|---|---|
| Student / platform engineer | | | |
| Reviewer | | | |
