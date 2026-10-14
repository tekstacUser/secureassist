# SecureAssist frontend image -> secureassist-frontend:1.0
# STUDENT TASK (Task 3): this is the reference solution.
# Build (from the project root):  docker build -t secureassist-frontend:1.0 app/frontend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY templates/ ./templates/
COPY static/ ./static/

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin secureassist
USER 10001

EXPOSE 8091

CMD ["gunicorn", "--bind", "0.0.0.0:8091", "--workers", "2", "--threads", "4", \
     "--timeout", "160", "--access-logfile", "-", "app:app"]
