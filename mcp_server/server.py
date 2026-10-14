"""SecureAssist MCP server (PREDEFINED - students do not modify this file).

A small, real Model Context Protocol (MCP) server built with the official
Python SDK (package `mcp`, pinned in requirements.txt).

Transport : MCP "Streamable HTTP" at  http://<host>:8093/mcp
Health    : plain HTTP GET             http://<host>:8093/health

It exposes exactly two SAFE, READ-ONLY tools:

  search_support_faq(query)     -> searches the predefined FAQ list below
  get_service_status(service)   -> returns SIMULATED status from the table below

Neither tool runs commands, reads files, or calls other systems. All data is
predefined in this file, so every answer is deterministic and testable.
"""

import os
import re

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

SERVER_NAME = "secureassist-mcp"
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8093"))

# Only these Host headers are accepted (DNS-rebinding protection).
# Defaults cover the Kubernetes Service name, its FQDN, and local testing.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv(
        "MCP_ALLOWED_HOSTS",
        "secureassist-mcp:*,secureassist-mcp.secureassist:*,"
        "secureassist-mcp.secureassist.svc:*,"
        "secureassist-mcp.secureassist.svc.cluster.local:*,"
        "localhost:*,127.0.0.1:*",
    ).split(",")
    if h.strip()
]

# --------------------------------------------------------------------------
# Predefined project data (the ONLY data the tools can return)
# --------------------------------------------------------------------------
FAQS = [
    {
        "id": "FAQ-001",
        "title": "Reset your corporate password",
        "keywords": ["password", "reset", "forgot", "expired", "login"],
        "answer": "Open the Self-Service Portal (https://sso.example.internal/reset), "
        "choose 'Forgot password', verify with your registered MFA device and set a new "
        "password of at least 14 characters. Never share your password with anyone, "
        "including the helpdesk.",
    },
    {
        "id": "FAQ-002",
        "title": "Connect to the corporate VPN",
        "keywords": ["vpn", "remote", "connect", "tunnel", "home"],
        "answer": "Install the approved VPN client from the Software Center, sign in with "
        "your corporate account, select the gateway nearest to you and approve the MFA "
        "prompt. If it fails, restart the client and check your internet connection.",
    },
    {
        "id": "FAQ-003",
        "title": "Set up multi-factor authentication (MFA)",
        "keywords": ["mfa", "2fa", "authenticator", "multi-factor", "token", "otp"],
        "answer": "Go to the Security page of the Self-Service Portal, choose 'Register "
        "authenticator', scan the QR code with the approved authenticator app and enter "
        "the 6-digit code to confirm.",
    },
    {
        "id": "FAQ-004",
        "title": "Add a network printer",
        "keywords": ["printer", "print", "printing", "scanner"],
        "answer": "Open Settings > Printers, choose 'Add printer', and pick the printer "
        "named after your floor (for example FL3-PRINT-01). Drivers install automatically "
        "from the print server.",
    },
    {
        "id": "FAQ-005",
        "title": "Configure corporate email on a phone",
        "keywords": ["email", "mail", "outlook", "phone", "mobile"],
        "answer": "Install the approved mail app from the company app store, sign in with "
        "your corporate account and accept the device-management policy. Personal mail "
        "apps are not permitted for corporate email.",
    },
    {
        "id": "FAQ-006",
        "title": "Join the office Wi-Fi",
        "keywords": ["wifi", "wi-fi", "wireless", "network", "internet"],
        "answer": "Select the 'CORP-SECURE' network and sign in with your corporate "
        "account. Guests must use 'CORP-GUEST' with a voucher from reception.",
    },
    {
        "id": "FAQ-007",
        "title": "Request new software",
        "keywords": ["software", "install", "application", "license", "request"],
        "answer": "Raise a request in the Helpdesk Portal under 'Software'. Only software "
        "on the approved catalogue can be installed; other titles need a security review.",
    },
    {
        "id": "FAQ-008",
        "title": "Report a lost or stolen laptop",
        "keywords": ["lost", "stolen", "laptop", "device", "theft"],
        "answer": "Call the Service Desk immediately so the device can be locked and "
        "wiped remotely, then file an incident report in the Helpdesk Portal.",
    },
]

# Simulated status table. This is DEMO DATA, not live infrastructure health.
SERVICE_STATUS = {
    "email": {"status": "operational", "note": "No known issues."},
    "vpn": {"status": "degraded", "note": "Scheduled maintenance on gateway EU-2 (simulated)."},
    "sso": {"status": "operational", "note": "No known issues."},
    "wifi": {"status": "operational", "note": "No known issues."},
    "printing": {"status": "outage", "note": "Print server FL3 is offline (simulated)."},
    "helpdesk-portal": {"status": "operational", "note": "No known issues."},
}
APPROVED_SERVICES = sorted(SERVICE_STATUS)

MAX_QUERY_CHARS = 200


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\-]+", text.lower()))


def search_faq_data(query: str, limit: int = 3) -> list[dict]:
    """Plain Python search used by the MCP tool (and easy to unit-test)."""
    words = _tokens(query)
    scored = []
    for faq in FAQS:
        score = len(words & set(faq["keywords"])) * 2 + len(words & _tokens(faq["title"]))
        if score > 0:
            scored.append((score, faq))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [
        {"id": f["id"], "title": f["title"], "answer": f["answer"], "score": s}
        for s, f in scored[:limit]
    ]


# --------------------------------------------------------------------------
# MCP server definition
# --------------------------------------------------------------------------
mcp = FastMCP(
    SERVER_NAME,
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,  # each request is independent: simple and Kubernetes-friendly
    json_response=True,  # plain JSON responses instead of an SSE stream
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=[],
    ),
)


@mcp.tool()
def search_support_faq(query: str) -> dict:
    """Search the approved IT helpdesk FAQ. Read-only. Returns up to 3 matching entries."""
    query = (query or "").strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be 1-{MAX_QUERY_CHARS} characters")
    results = search_faq_data(query)
    return {"query": query, "match_count": len(results), "results": results,
            "source": "predefined SecureAssist FAQ"}


@mcp.tool()
def get_service_status(service: str) -> dict:
    """Return the SIMULATED status of an approved demo service. Read-only."""
    service = (service or "").strip().lower()
    if service not in SERVICE_STATUS:
        raise ValueError(f"unknown service '{service}'. Approved: {', '.join(APPROVED_SERVICES)}")
    return {"service": service, **SERVICE_STATUS[service],
            "source": "simulated demo data - not live infrastructure health"}


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": SERVER_NAME,
                         "tools": ["search_support_faq", "get_service_status"]})


if __name__ == "__main__":
    print(f"[{SERVER_NAME}] MCP streamable-http on http://{HOST}:{PORT}/mcp", flush=True)
    mcp.run(transport="streamable-http")
