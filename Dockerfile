FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 macrovision
COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[postgres]"
RUN mkdir -p /data && chown -R macrovision:macrovision /data /app
USER macrovision
VOLUME ["/data"]
EXPOSE 8000
CMD ["sh","-c","alembic upgrade head && uvicorn macrovision.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1"]
