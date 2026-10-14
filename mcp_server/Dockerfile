# SecureAssist MCP server image -> secureassist-mcp:1.0   (PREDEFINED reference)
# Build (from the project root):  docker build -t secureassist-mcp:1.0 mcp_server
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8093

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin secureassist
USER 10001

EXPOSE 8093

CMD ["python", "server.py"]
