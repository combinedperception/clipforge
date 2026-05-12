# Production Engineering Notes

This document describes the production engineering principles applied in ClipForge AI, the current hardening measures, and considerations for evolving the system toward a production deployment.

## Codebase Principles

### Typed Interfaces

Every boundary between components uses Pydantic v2 models:
- **API contracts:** `VideoJobResponse`, `CandidateClipResponse`, `BrandProfile`
- **AI ↔ Rendering:** `EditPlan` — the central contract
- **Pipeline state:** `PipelineState` TypedDict with typed fields
- **Configuration:** `Settings(BaseSettings)` with typed, validated environment variables

Pydantic enforces type validation at runtime. Invalid data is rejected at the boundary, not deep inside business logic.

### Structured Logging

All backend logging uses **structlog** (`backend/app/core/logging.py`):
- JSON output in production (machine-parseable)
- Colored console output in development (human-readable)
- Contextual key-value pairs: `logger.info("job_started", job_id=job_id, stage="extracting_audio")`
- Configured via `LOG_LEVEL` environment variable

### Error Hierarchy

Custom exceptions inherit from `ClipForgeError` (`backend/app/core/errors.py`):

```
ClipForgeError (base)
├── VideoNotFoundError (404)
├── JobNotFoundError (404)
├── ClipNotFoundError (404)
├── InvalidVideoError (422)
├── PipelineError (500)
├── FFmpegError (500)
└── StorageError (500)
```

Global exception handlers registered in `main.py` catch these and return structured JSON error responses with appropriate HTTP status codes.

### Deterministic Media Processing

AI agents produce structured decisions (`EditPlan`). FFmpeg executes them deterministically. This means:
- Same `EditPlan` → same rendered output (reproducible)
- Failed renders are debuggable by inspecting the plan JSON
- AI decisions can be audited, edited, and replayed

### Configuration via Environment Variables

All configuration is managed through environment variables, loaded by `pydantic-settings`:
- No hardcoded secrets or connection strings
- Secrets (`openai_api_key`, `youtube_client_id`, `youtube_client_secret`) use `Field(repr=False)` to prevent leakage in logs, tracebacks, and debug output
- Settings are cached via `@lru_cache` (`get_settings()`)

### Storage Abstraction

File storage is behind a `StorageBackend` abstract base class:
- MVP uses `LocalStorage` (filesystem)
- Interface supports `save`, `save_file`, `get`, `get_path`, `delete`, `exists`, `get_url`
- Switching backends requires one environment variable change + implementing the interface

### Idempotent Background Jobs

The Celery task `process_video_job` is designed for safe retries:
- Job status is updated at each stage, so a retry can skip completed stages
- Database operations use explicit commits
- File writes are to unique paths (no overwrites)
- The task uses `autoretry_for=(IOError, ConnectionError)` with `retry_backoff=30` (exponential)

## Current Production Hardening

These measures are implemented in the current codebase:

### Streaming Upload
`routes_upload.py` streams uploaded files to disk in **64KB chunks**. The file is never fully loaded into memory. Mid-stream size validation aborts and cleans up partial files if the upload exceeds `MAX_UPLOAD_SIZE_MB`.

### Path Traversal Protection
The download endpoint in `routes_clips.py` validates that the resolved file path stays within the configured `storage_root` directory. The `LocalStorage` backend also validates paths.

### Secret Masking
Sensitive configuration fields (`openai_api_key`, `youtube_client_id`, `youtube_client_secret`) use `Field(repr=False)` in the Pydantic `Settings` class, preventing them from appearing in logs, tracebacks, or debug output.

### Lazy Database Initialization
The SQLAlchemy async engine is created lazily via `@lru_cache` (`_build_engine()` in `session.py`), not at import time. This prevents import-time side effects and makes testing easier.

### Shared Sync Engine in Celery
Celery tasks share a single `@lru_cache` synchronous engine (`_sync_engine()` in `tasks.py`) instead of creating a new `create_engine()` on every status update. This prevents connection leaks.

### Automatic Task Retries
The `process_video_job` task uses `autoretry_for=(IOError, ConnectionError)` with `retry_backoff=30` and `max_retries=2`. Transient network errors (API timeouts, Redis hiccups) are retried automatically with exponential backoff. Non-retryable errors (bad video file, validation failures) fail immediately.

### Frontend API Timeout
The frontend API client (`lib/api.ts`) uses `AbortController` with a **15-second timeout** to prevent indefinite hangs on slow or unresponsive backends.

### Backend Offline Detection
The frontend dashboard detects when the backend is unreachable and shows a "Backend unavailable" banner, falling back to mock data for continued UI development.

## Deployment Considerations

### Recommended Production Stack

```
                    ┌───────────────┐
                    │  Nginx / CDN  │
                    │  (reverse     │
                    │   proxy)      │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
     ┌────────▼──────┐  ┌──▼───────┐  ┌──▼──────────┐
     │  Next.js      │  │ FastAPI  │  │  Static      │
     │  (Vercel or   │  │ (Gunicorn│  │  Storage     │
     │   standalone) │  │  +Uvicorn│  │  (S3/CDN)    │
     └───────────────┘  │  workers)│  └──────────────┘
                        └────┬─────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐  ┌───▼──────┐  ┌───▼──────────┐
     │  PostgreSQL   │  │  Redis   │  │  Celery      │
     │  (managed:    │  │  (managed│  │  Workers     │
     │   RDS/Cloud   │  │   or     │  │  (1+ per     │
     │   SQL)        │  │   self-  │  │   queue)     │
     └───────────────┘  │   hosted)│  └──────────────┘
                        └──────────┘
```

### Key decisions for production:

| Area | Recommendation |
|------|----------------|
| **ASGI server** | Gunicorn with Uvicorn workers (`gunicorn -k uvicorn.workers.UvicornWorker`) |
| **Database** | Managed PostgreSQL (RDS, Cloud SQL, Supabase) |
| **Redis** | Managed Redis (ElastiCache, Upstash) |
| **File storage** | S3 or R2 with CDN (set `STORAGE_BACKEND=s3`) |
| **Celery workers** | Separate containers/processes, scaled by queue depth |
| **Frontend** | Vercel or standalone `next start` behind a CDN |
| **HTTPS** | Required — terminate at reverse proxy |
| **CORS** | Configure `allowed_origins` in FastAPI for production domain |

### Scaling Notes

- **Celery workers** are the primary scaling target. Each worker processes one video at a time. Add workers to increase throughput.
- **FFmpeg rendering** is CPU-bound and memory-intensive. Workers should run on compute-optimized instances.
- **Whisper transcription** is an API call — scaling is limited by OpenAI rate limits, not local compute.
- **Database** load is light (metadata only). A small managed PostgreSQL instance is sufficient.
- **Storage** scales with video volume. Use object storage (S3/R2) for production.

## Security Posture

### Implemented
- Streaming upload with size validation (no memory bombs)
- Path traversal protection on downloads
- Secret masking in configuration (`repr=False`)
- Pydantic validation on all API inputs
- CORS configured for allowed origins
- Custom error handlers (no stack traces in API responses)

### Not yet implemented (MVP limitations)
| Gap | Risk | Mitigation Path |
|-----|------|-----------------|
| No authentication | Anyone can upload/access | Add OAuth 2.0 / JWT authentication |
| No authorization | All users see all jobs | Add user-scoped access control |
| No rate limiting | DoS via upload spam | Add rate limiter middleware (slowapi) |
| No HTTPS enforcement | Man-in-the-middle | Terminate TLS at reverse proxy |
| No input sanitization on metadata | XSS if metadata rendered raw | Sanitize HTML in frontend rendering |
| No audit logging | No visibility into who did what | Add audit log table with user/action/timestamp |

## Monitoring and Observability

### Current
- Structured logging via structlog (JSON output in production)
- Job status tracking in database (11 states, with error messages)
- Health check endpoint (`GET /api/health`)

### Recommended additions for production
| Tool | Purpose |
|------|---------|
| **Prometheus + Grafana** | Metrics: job processing time, queue depth, error rate |
| **Sentry** | Exception tracking with context |
| **OpenTelemetry** | Distributed tracing across API → Worker → FFmpeg |
| **Celery Flower** | Real-time Celery worker monitoring (`celery -A app.workers.celery_app flower`) |
| **pgAdmin / pg_stat** | Database query performance monitoring |
