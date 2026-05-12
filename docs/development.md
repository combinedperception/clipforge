# Development Guide

This guide walks you through setting up a local development environment for ClipForge AI. By the end, you'll have the backend, frontend, and background worker running locally.

## Start Here

If you're new to the project, read these first:
1. **This page** — Get the system running locally
2. [docs/architecture.md](architecture.md) — Understand how the components fit together
3. [docs/agents.md](agents.md) — Understand the AI pipeline
4. [docs/video-pipeline.md](video-pipeline.md) — Understand the FFmpeg rendering pipeline
5. [docs/api.md](api.md) — Explore the REST API
6. [docs/testing.md](testing.md) — Run and write tests

## Prerequisites

| Tool | Version | Required | Purpose |
|------|---------|----------|---------|
| Python | 3.11+ | Yes | Backend runtime |
| Node.js | 20+ | Yes | Frontend runtime |
| FFmpeg | Any recent | Yes (for video processing) | Media processing |
| Docker + Docker Compose | Any recent | Recommended | PostgreSQL + Redis |
| OpenAI API Key | — | Optional | Whisper transcription + LLM scoring |

> **Minimal mode:** You can run the backend + frontend without Docker by using SQLite and skipping the Celery worker. Video processing won't work, but you can develop the API and UI.

## Install FFmpeg

FFmpeg is required for all video processing operations (audio extraction, clip rendering, caption burning).

```bash
# macOS (Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Windows (Chocolatey)
choco install ffmpeg

# Windows (Scoop)
scoop install ffmpeg

# Verify installation
ffmpeg -version
which ffmpeg    # Should print a path
```

## Step 1: Clone and Configure

```bash
git clone <repo-url>
cd videoEdit
cp .env.example .env
```

Edit `.env` and set at minimum:
```bash
# Required for transcription (optional for UI/API dev)
OPENAI_API_KEY=sk-proj-your-key-here
```

## Step 2: Start Infrastructure (Docker)

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** on port 5432 (user: `clipforge`, password: `clipforge`, db: `clipforge`)
- **Redis** on port 6379

Verify services are running:
```bash
docker compose ps
docker compose logs postgres   # Check PostgreSQL
docker compose logs redis      # Check Redis
```

### Skip Docker (SQLite Mode)

For lightweight development without Docker, edit `.env`:

```bash
DATABASE_URL=sqlite+aiosqlite:///./clipforge.db
```

SQLite mode auto-creates the database on startup. No Redis is needed unless you want background processing with Celery.

## Step 3: Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows (cmd)
# .venv\Scripts\Activate.ps1     # Windows (PowerShell)

# Install dependencies (including dev tools)
pip install -e ".[dev]"
```

### Start the API Server

```bash
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000
- Interactive docs (Swagger): http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health check: http://localhost:8000/api/health

The `--reload` flag enables auto-restart on file changes.

## Step 4: Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

- UI: http://localhost:3000
- The frontend connects to `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)

### Frontend environment

Create `frontend/.env.local` if you need to override the backend URL:
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Step 5: Celery Worker (Background Processing)

The Celery worker is required for actual video processing. Without it, uploads are accepted but jobs stay in `uploaded` status.

```bash
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

> **Requires Redis.** The worker uses Redis as its message broker. Make sure Redis is running (via Docker or locally).

### Worker configuration

| Setting | Value | Source |
|---------|-------|--------|
| Broker | Redis (port 6379/0) | `CELERY_BROKER_URL` |
| Result backend | Redis (port 6379/1) | `CELERY_RESULT_BACKEND` |
| Soft time limit | 30 minutes | `celery_app.py` |
| Hard time limit | 60 minutes | `celery_app.py` |
| Max retries | 2 | `tasks.py` |
| Retry backoff | 30s (exponential) | `tasks.py` |

## Database Migrations (Alembic)

For PostgreSQL deployments, use Alembic for schema migrations:

```bash
cd backend
source .venv/bin/activate

# Create a new migration after modifying models.py
alembic revision --autogenerate -m "Add retry_count to VideoJob"

# Apply pending migrations
alembic upgrade head

# Rollback the last migration
alembic downgrade -1

# Show current migration state
alembic current
```

> **SQLite dev mode** auto-creates tables on startup. Alembic is only needed for PostgreSQL.

## API Exploration

FastAPI provides an interactive API explorer at http://localhost:8000/docs. You can:
- Try every endpoint directly in the browser
- See request/response schemas
- Upload files via the Swagger UI
- View Pydantic model definitions

See [docs/api.md](api.md) for the complete API reference.

## Common Development Commands

| Task | Command |
|------|---------|
| Start backend | `cd backend && uvicorn app.main:app --reload` |
| Start frontend | `cd frontend && npm run dev` |
| Start Celery worker | `cd backend && celery -A app.workers.celery_app worker --loglevel=info` |
| Start infrastructure | `docker compose up -d` |
| Stop infrastructure | `docker compose down` |
| Run all tests | `cd backend && pytest` |
| Run tests (verbose) | `cd backend && pytest -v` |
| Run specific test file | `cd backend && pytest tests/test_api.py` |
| Run with coverage | `cd backend && pytest --cov=app` |
| Lint backend | `cd backend && ruff check .` |
| Format backend | `cd backend && ruff format .` |
| Lint frontend | `cd frontend && npm run lint` |
| Build frontend | `cd frontend && npm run build` |
| Reset SQLite database | `rm backend/clipforge.db` (re-created on next startup) |
| View backend logs | Set `LOG_LEVEL=DEBUG` in `.env` |
| Apply DB migrations | `cd backend && alembic upgrade head` |

## Code Quality

### Backend (Ruff)

```bash
cd backend

# Check for lint errors
ruff check .

# Auto-fix lint errors
ruff check . --fix

# Format code
ruff format .
```

Configuration in `pyproject.toml`: Python 3.11 target, 100-char line length, rules: E, F, I, N, W, UP.

### Frontend (ESLint)

```bash
cd frontend
npm run lint
```

## Debugging Tips

- **Enable debug logging:** Set `DEBUG=true` and `LOG_LEVEL=DEBUG` in `.env`
- **API docs:** http://localhost:8000/docs — test endpoints interactively
- **Health check:** `curl http://localhost:8000/api/health`
- **Check Celery:** Look at worker terminal for task execution logs
- **Inspect job storage:** Files are in `backend/storage/jobs/{job_id}/`
- **Frontend mock mode:** If the backend is down, the frontend shows sample data with a warning banner

See [docs/troubleshooting.md](troubleshooting.md) for common issues and solutions.
