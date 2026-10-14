# SecureAssist MCP Server (predefined)

A small, real **Model Context Protocol** server built with the official Python SDK (`mcp==1.30.0`, `FastMCP`).

| Item | Value |
|---|---|
| Transport | MCP **Streamable HTTP**, endpoint `POST /mcp` (stateless, JSON responses) |
| Port | 8093 (container, Service `secureassist-mcp:8093`, VM port-forward `127.0.0.1:8093`) |
| Health | `GET /health` (plain HTTP, for probes) |
| Image | `secureassist-mcp:1.0` (`docker build -t secureassist-mcp:1.0 mcp_server`) |
| Host protection | only Host headers in `MCP_ALLOWED_HOSTS` (Service name/FQDN, localhost) are accepted |

## Tools (read-only, predefined data)
| Tool | Arguments | Returns |
|---|---|---|
| `search_support_faq` | `query` (1–200 chars) | up to 3 matching entries from the 8 FAQ items in `server.py` (`FAQ-001` … `FAQ-008`), keyword scoring |
| `get_service_status` | `service` ∈ `email, vpn, sso, wifi, printing, helpdesk-portal` | **simulated** status from the table in `server.py`, labelled `"source": "simulated demo data - not live infrastructure health"` |

No tool runs commands, reads files, or contacts other systems. Results are deterministic, so checks can compare exact answers.

## How MCP is used (not a REST call labelled MCP)
Each backend call (`app/backend/mcp_client.py`) is a full MCP exchange over JSON-RPC 2.0:
1. `initialize` (client and server negotiate the protocol version and capabilities),
2. `notifications/initialized`,
3. `tools/list` — **discovery**; the client confirms the server offers the tool,
4. `tools/call` — **invocation** with validated arguments.

Before any network traffic the client enforces its **allowlist** (`ALLOWED_TOOLS`) and validates arguments, so `run_shell` or `{"service": "payroll-db"}` are rejected locally.

## Verify in the cluster
```bash
# discovery and invocation through the Kubernetes Service, from inside the backend Pod
kubectl -n secureassist exec deploy/secureassist-backend -- python mcp_client.py list
kubectl -n secureassist exec deploy/secureassist-backend -- python mcp_client.py call get_service_status '{"service": "printing"}'
# rejected by the allowlist / validation
kubectl -n secureassist exec deploy/secureassist-backend -- python mcp_client.py call run_shell '{}'
kubectl -n secureassist exec deploy/secureassist-backend -- python mcp_client.py call search_support_faq '{"query": "vpn", "path": "/etc/passwd"}'
# server-side protocol log
kubectl -n secureassist logs deploy/secureassist-mcp --tail=20
```
Expected server log lines: `Processing request of type ListToolsRequest` and `Processing request of type CallToolRequest`.

## Verify from the UI and backend logs
1. Browser `http://<VM-IP>:8091`: ask `How do I reset my password?` → green badge **🔧 MCP tool: search_support_faq (success)**.
2. Ask `Is the VPN service down?` → badge **get_service_status**, answer marked *simulated*.
3. Backend log:
   ```bash
   kubectl -n secureassist logs deploy/secureassist-backend --tail=20 | grep '"event": "chat"'
   ```
   shows `"route": "faq"`, `"mcp_tool": "search_support_faq"`, `"mcp_outcome": "success"`.

## Raw protocol (optional, through the port-forward on 8093)
```bash
curl -s http://localhost:8093/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
curl -s http://localhost:8093/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```
