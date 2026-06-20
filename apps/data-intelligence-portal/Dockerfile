FROM python:3.12-slim

WORKDIR /app

# Build context is the suranku-public repo root (see docker-compose.yml).
COPY apps/data-intelligence-portal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source (backend, demo, contracts, agents) at /app; shared published site at /app/site.
COPY apps/data-intelligence-portal/ .
COPY site/ ./site/

ENV PORTAL_HOME=/app
ENV PORTAL_SITE=/app/site
EXPOSE 8080

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
