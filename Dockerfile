FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
COPY requirements-lock.txt .
RUN pip install --no-cache-dir --timeout 60 --retries 3 -r requirements.txt -c requirements-lock.txt
COPY app ./app
COPY scripts ./scripts
COPY mock_services ./mock_services
COPY migrations ./migrations
COPY alembic.ini .
RUN mkdir -p /data && useradd -m -u 10001 appuser && chown -R appuser:appuser /app /data
USER appuser
ENV DATABASE_URL=sqlite+aiosqlite:////data/support_agent.db
ENV SYNC_DATABASE_URL=sqlite:////data/support_agent.db
ENV CHECKPOINT_DATABASE_URL=sqlite:////data/checkpoints.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
