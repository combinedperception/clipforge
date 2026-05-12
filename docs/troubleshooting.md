# Troubleshooting

Common issues and how to resolve them.

---

## FFmpeg Not Found

**Symptom:** `FFmpegError: command not found` or tasks fail at the `extracting_audio` stage.

**Cause:** FFmpeg is not installed or not on your system PATH.

**Fix:**
```bash
# Verify FFmpeg is installed
ffmpeg -version

# If not installed:
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Ubuntu/Debian
choco install ffmpeg         # Windows

# Verify it's on PATH
which ffmpeg                 # Should print a path
```

If FFmpeg is installed but not on PATH, add its directory to your shell profile (`~/.zshrc`, `~/.bashrc`).

---

## Redis Connection Refused

**Symptom:** Celery worker fails to start with `ConnectionRefusedError` or `redis.exceptions.ConnectionError`.

**Cause:** Redis is not running.

**Fix:**
```bash
# Start Redis via Docker
docker compose up -d redis

# Verify Redis is running
docker compose ps
redis-cli ping    # Should return "PONG"

# Check the URL in .env
# REDIS_URL=redis://localhost:6379/0
```

If you're not using Docker, install Redis locally:
```bash
brew install redis && brew services start redis    # macOS
sudo apt install redis-server                       # Ubuntu
```

---

## Database Connection Errors

### SQLite

**Symptom:** `OperationalError: database is locked` or `no such table`.

**Fix:**
```bash
# Reset the database (all data lost)
rm backend/clipforge.db

# Restart the backend — tables are auto-created
uvicorn app.main:app --reload
```

### PostgreSQL

**Symptom:** `asyncpg.CannotConnectNowError` or `connection refused`.

**Fix:**
```bash
# Start PostgreSQL
docker compose up -d postgres

# Verify connection
docker compose exec postgres pg_isready -U clipforge

# Check the URL in .env
# DATABASE_URL=postgresql+asyncpg://clipforge:clipforge@localhost:5432/clipforge

# Apply migrations
cd backend && alembic upgrade head
```

---

## CORS Errors

**Symptom:** Browser console shows `Access-Control-Allow-Origin` errors. API calls from the frontend fail.

**Cause:** The frontend origin is not in the backend's CORS allowed origins list.

**Fix:** The backend allows `localhost:3000` by default. If you're running the frontend on a different port or domain, check the CORS configuration in `backend/app/main.py`.

---

## Upload Failures

### File Too Large

**Symptom:** `413 Request Entity Too Large` or `422` error mentioning file size.

**Fix:** Check `MAX_UPLOAD_SIZE_MB` in `.env` (default: 500). Increase if needed. Also check reverse proxy limits (Nginx `client_max_body_size`).

### Invalid File Type

**Symptom:** `422` error: "Unsupported file extension" or "Invalid content type".

**Fix:** Supported formats are `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`. Convert other formats before uploading:
```bash
ffmpeg -i input.flv -c copy output.mp4
```

### Empty File

**Symptom:** `422` error: "File is empty".

**Fix:** Check that the file was correctly selected. Verify the file has content:
```bash
ls -la your-video.mp4    # Should show non-zero size
```

---

## Celery Worker Not Processing Jobs

**Symptom:** Jobs stay in `uploaded` status and never progress.

**Cause:** No Celery worker is running, or the worker can't connect to Redis.

**Fix:**
```bash
# 1. Make sure Redis is running
docker compose up -d redis

# 2. Start a worker
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info

# 3. Verify the worker registered the task
# Look for: "process_video_job" in the worker's startup output

# 4. Check the broker URL matches .env
# CELERY_BROKER_URL=redis://localhost:6379/0
```

---

## Transcription Failures

**Symptom:** Job fails at the `transcribing` stage.

### Missing API Key
**Cause:** `OPENAI_API_KEY` is not set or empty.

**Fix:** Set a valid key in `.env`. Without it, the system uses `MockTranscriptionService` which returns fixture data — fine for development, but not real transcription.

### API Rate Limits
**Cause:** OpenAI rate limit exceeded.

**Fix:** The Celery task retries up to 2 times with 30s exponential backoff. If it still fails:
- Check your OpenAI usage dashboard for rate limits
- Use a higher-tier API key
- Reduce concurrent video processing (fewer Celery workers)

### Audio File Too Large
**Cause:** Whisper has a 25MB file size limit.

**Fix:** For very long videos, the audio file may exceed this limit. Currently, the system sends the full audio file. A future improvement would chunk the audio.

---

## Rendering Failures

**Symptom:** Job fails at the `rendering` stage with `FFmpegError`.

**Common causes:**
1. **FFmpeg not installed** — See "FFmpeg Not Found" above
2. **Corrupt source video** — Try playing the video locally. If it's corrupt, re-upload.
3. **Missing libass** — Caption burning requires libass support in FFmpeg.

**Check libass support:**
```bash
ffmpeg -filters 2>/dev/null | grep subtitles
# Should show: "subtitles" in the filter list
```

**Check FFmpeg stderr** — The error message includes FFmpeg's stderr output. Look for specific codec or filter errors.

---

## Frontend Shows "Backend Unavailable"

**Symptom:** Yellow banner says "Backend unavailable — showing sample data."

**Cause:** The frontend can't reach the backend API.

**Fix:**
1. Verify the backend is running: `curl http://localhost:8000/api/health`
2. Check `NEXT_PUBLIC_API_URL` in `frontend/.env.local` (should match backend URL)
3. Check for CORS issues (see above)
4. If the backend just started, wait a few seconds for initialization

---

## Frontend Shows Mock Data (No Banner)

**Symptom:** Dashboard shows sample jobs and metrics, but no warning banner.

**Cause:** The frontend falls back to mock data when the API returns no data (e.g., empty database).

**Fix:** This is expected behavior on a fresh install. Upload a video to see real data.

---

## Debug Mode

For verbose logging, set these in `.env`:

```bash
DEBUG=true
LOG_LEVEL=DEBUG
```

This enables:
- SQLAlchemy query echo (all SQL queries logged)
- Detailed structlog output
- FFmpeg command logging (full command lines)

**Warning:** Debug mode produces a lot of output. Don't use it in production.

---

## Common Log Messages

| Message | Meaning |
|---------|---------|
| `job_started` | Celery worker picked up a job |
| `audio_extracted` | FFmpeg audio extraction completed |
| `transcription_complete` | Whisper API returned transcript |
| `pipeline_complete` | Agent pipeline finished |
| `clip_rendered` | One clip finished rendering |
| `job_completed` | All clips rendered, job ready for review |
| `job_failed` | Job failed with error (check `error_message`) |
| `database_initialized` | SQLite tables auto-created on startup |
| `app_started` | FastAPI application started successfully |

---

## Getting Help

1. **Check the logs** — Backend logs show structured error messages with context
2. **Check job status** — `GET /api/jobs/{job_id}` includes `error_message` field
3. **Check the docs** — [docs/api.md](api.md) for API reference, [docs/architecture.md](architecture.md) for system overview
4. **Run tests** — `cd backend && pytest -v` to verify your local setup
5. **Health check** — `curl http://localhost:8000/api/health` to verify the backend is running
