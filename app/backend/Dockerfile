# SecureAssist backend image -> secureassist-backend:1.0
# STUDENT TASK (Task 3): this is the reference solution.
# Build (from the project root):  docker build -t secureassist-backend:1.0 app/backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer is cached between code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the application modules (tests and secrets are excluded by .dockerignore)
COPY app.py guardrails.py ollama_client.py mcp_client.py monitoring.py ./

# Run as an unprivileged user
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin secureassist
USER 10001

EXPOSE 8092

# 2 workers x 4 threads; long timeout because phi3:mini on CPU can be slow
CMD ["gunicorn", "--bind", "0.0.0.0:8092", "--workers", "2", "--threads", "4", \
     "--timeout", "150", "--access-logfile", "-", "app:app"]
