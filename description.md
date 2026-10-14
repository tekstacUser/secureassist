# SecureAssist — Scenario Description

## The organisation
A mid-sized enterprise runs an internal IT Service Desk for about 3,000 employees. Most tickets are repeat questions: password resets, VPN problems, printers, MFA set-up, Wi-Fi and "is service X down?". Agents spend hours answering the same things, and employees wait.

The platform team already operates, on a single lab VM:

* **Ollama** with the `phi3:mini` model (local inference, no data leaves the company),
* **Jenkins** (CI/CD) with **SonarQube** for code-quality gates,
* **Kubernetes** (Minikube) for workloads,
* GitLab for source control.

LLM observability (**Langfuse**, with its PostgreSQL database) is delivered with this project and runs as Pods next to the application, in the same Kubernetes namespace and network.

## The request
Leadership asked for **SecureAssist**, an internal AI helpdesk that:

1. Answers employees in a browser chat window.
2. Uses only **approved** support content, obtained through a standard tool protocol (**MCP**) so tools can be governed, allow-listed and audited.
3. Blocks attempts to extract passwords, keys or tokens and obvious prompt-injection attempts, and redacts secrets from answers.
4. Never executes anything the model says — answers are text only.
5. Runs as containers on Kubernetes, delivered by a Jenkins pipeline that **must pass a SonarQube quality gate** before anything is built or deployed.
6. Is observable in Langfuse without leaking prompt content or credentials.
7. Has a rehearsed incident-response procedure and auditable governance evidence.

## Your role
You are the platform engineer delivering the first production-like release. Most of the code is provided. You will:

* implement the guardrails (security logic) and check them in the running system,
* containerise the frontend and backend,
* write the Kubernetes deployment configuration,
* deploy and verify genuine MCP tool use,
* run the Jenkins pipeline with SonarQube analysis and quality gate,
* break the release on purpose, diagnose it and recover,
* produce the evidence an auditor would ask for.

## Expected outcomes
| Outcome | Evidence |
|---|---|
| Chatbot reachable at `http://<VM-IP>:8091` | browser test + verification report |
| Guardrails block secret requests and injection; redact secrets | guardrail check in the running backend Pod, blocked message in the UI |
| Real MCP tool discovery/invocation through an allowlist | `mcp_client.py list/call` output, MCP server logs, UI badge |
| Real `phi3:mini` answers from the existing Ollama | verification report "Real Ollama phi3:mini response" |
| Four project images (+ PostgreSQL), five Ready Kubernetes workloads in one namespace | `minikube image ls`, `kubectl get deploy` |
| Jenkins pipeline with genuine pass/fail and SonarQube gate | Jenkins build, `reports/jenkins-result.md` |
| Langfuse traces | trace fetched from the Langfuse API by ID |
| Incident drill recorded | `reports/incident-record.md` |
| Governance checklist completed | `docs/governance-checklist.md`, `reports/verification-latest.md` = PASS |

## Constraints
* Reuse existing Ollama (`phi3:mini`) and SonarQube — do not install or duplicate them, do not download models. Run exactly one Langfuse instance (the project's Pods).
* Ports: frontend 8091, backend 8092, MCP server 8093, Langfuse 3031 (Jenkins 3030, Ollama 11434).
* All project components run as Pods in namespace `secureassist` (same network); only the existing Ollama stays on the VM.
* No automated test files are delivered; behaviour is verified on the running system.
* No `sudo`, no files outside the `secureassist/` directory, no real secrets in Git.
* Total time: 80–90 minutes (10–15 understanding + 70–75 hands-on).
