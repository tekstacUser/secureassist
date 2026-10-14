# SecureAssist Langfuse image -> secureassist-langfuse:1.0   (PREDEFINED)
#
# Build (VM, project root):   docker build -t secureassist-langfuse:1.0 langfuse
# Load into Minikube:         minikube image load secureassist-langfuse:1.0 --overwrite=true
# Runs as a Pod in namespace secureassist (k8s/langfuse-deployment.yaml), on the same
# cluster network as the frontend, backend and MCP server.
#
# Based on the official prebuilt Langfuse v2 server image (web UI + API, Next.js).
# Only NON-SECRET settings are baked in here. Database password, NextAuth secret,
# salt, encryption key, API keys and admin password come from the Kubernetes Secret
# `secureassist-langfuse` at runtime - never from this image.
FROM langfuse/langfuse:2

ENV HOSTNAME=0.0.0.0 \
    PORT=3000 \
    NODE_ENV=production \
    TELEMETRY_ENABLED=false \
    LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES=false \
    AUTH_DISABLE_SIGNUP=true \
    LANGFUSE_INIT_ORG_ID=secureassist-org \
    LANGFUSE_INIT_ORG_NAME=SecureAssist \
    LANGFUSE_INIT_PROJECT_ID=secureassist \
    LANGFUSE_INIT_PROJECT_NAME=SecureAssist-Helpdesk \
    LANGFUSE_INIT_USER_EMAIL=admin@secureassist.local \
    LANGFUSE_INIT_USER_NAME=SecureAssist-Admin

# The base image already runs as the unprivileged user "nextjs"; use its numeric
# UID so Kubernetes can enforce runAsNonRoot.
USER 1001

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/api/public/health || exit 1
