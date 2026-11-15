FROM postgres:18
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
COPY backend/requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt \
    && useradd --uid 10001 --create-home agentconnect
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./
USER agentconnect
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
