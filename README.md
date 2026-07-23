# MacroVision

MacroVision is an Investment Decision Intelligence Platform. Version 0.1 provides a
local, auditable foundation for investor profiles, risk budgets, and hypothesis-driven
research journals. It is not a trading signal bot and does not connect to brokers or
execute trades.

## Decision principles

- Preserve capital before pursuing return.
- Treat cash as a valid asset allocation.
- Begin decisions with a falsifiable hypothesis.
- Express conclusions as probabilities and confidence levels, never certainty.
- Keep Research AI (evidence gathering) and Critic AI (adversarial review) as separate roles.
- Learn only from outcomes and lessons documented in the research journal.

The API makes these principles explicit through required supporting evidence, opposing
evidence, critic review, invalidation conditions, probability, and confidence fields.

## Architecture

```text
HTTP / OpenAPI       src/macrovision/api.py, main.py
Validation           src/macrovision/schemas.py
Decision workflows   src/macrovision/services.py
Persistence          src/macrovision/models.py, database.py
Schema history       migrations/
Configuration        src/macrovision/config.py
```

The first release uses FastAPI, Pydantic, SQLAlchemy 2, Alembic, and SQLite. Database
schema changes are owned by Alembic rather than application startup.

## Prerequisites

- Python 3.11 or later
- Windows PowerShell 5.1 or later
- Optional: Docker Desktop

## Install on Windows

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The script creates `.venv`, installs the application and development tools, copies
`.env.example` to `.env` when `.env` does not exist, and applies all migrations.

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Run

```powershell
.\scripts\run.ps1
```

Then open:

- API health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

## Quality checks

```powershell
.\scripts\check.ps1
```

Or run each check:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

## Docker

```powershell
docker build -t macrovision:0.1 .
docker run --rm -p 8000:8000 -v macrovision-data:/data macrovision:0.1
```

The container applies pending migrations before starting the API and persists SQLite
data in the `macrovision-data` volume.

## API workflow

1. Create an investor profile and its risk profile/risk budget with
   `POST /api/v1/investors`.
2. Record independent research and critic review with `POST /api/v1/journals`.
3. Close the journal with a documented outcome and lesson using
   `POST /api/v1/journals/{journal_id}/close`.

This version is for research and decision documentation only. It does not offer
personalized financial advice, market data ingestion, authentication, AI model calls,
portfolio optimization, real trading, or brokerage integration.
