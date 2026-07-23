FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MACROVISION_DATABASE_URL=sqlite:////data/macrovision.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .

RUN mkdir /data
VOLUME ["/data"]
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn macrovision.main:app --host 0.0.0.0 --port 8000"]
