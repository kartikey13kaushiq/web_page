FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/entries.sqlite3
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src src
RUN pip install --no-cache-dir ".[serve]" && useradd --system app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
# Set SECRET_KEY (sessions/CSRF) and ADMIN_TOKEN (CSV export) in production.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "contest:create_app()"]
