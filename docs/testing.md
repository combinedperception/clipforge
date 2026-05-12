# Testing Guide

This document covers the test architecture, how to run tests, and how to add new tests to ClipForge AI.

## Test Architecture

| Tool | Purpose |
|------|---------|
| **pytest** | Test runner and assertion framework |
| **pytest-asyncio** | Async test support (auto mode — no manual `@pytest.mark.asyncio` needed) |
| **aiosqlite** | In-memory SQLite for database tests |
| **httpx** | Async HTTP client for API endpoint tests |
| **unittest.mock** | Mocking external services (FFmpeg, Whisper API) |

All tests run against an **in-memory SQLite database** and mock external services. No Docker, FFmpeg, Redis, or API keys are needed to run the test suite.

## Test Files

| File | Tests | What It Covers |
|------|-------|----------------|
| `tests/test_schemas.py` | Schema validation | Pydantic model validation, field constraints, enums, computed properties |
| `tests/test_api.py` | API endpoints | Health check, upload validation, job listing, clip actions, brand profile |
| `tests/test_ffmpeg.py` | FFmpeg utilities | Audio extraction, normalization, clip cutting, cropping, caption burning (all mocked) |
| `tests/test_pipeline.py` | Pipeline functions | Video validation, SRT generation, transcript segmentation, clip scoring, metadata |
| `tests/test_agents.py` | Agent nodes | All 7 pipeline nodes: clean, segment, score, select, edit plans, metadata, QA |

**Total: 87 tests**

## Running Tests

```bash
cd backend
source .venv/bin/activate

# Run all tests
pytest

# Verbose output (see each test name)
pytest -v

# Run a specific test file
pytest tests/test_api.py

# Run tests matching a name pattern
pytest -k "test_valid"
pytest -k "test_upload"

# Run a specific test class
pytest tests/test_ffmpeg.py::TestExtractAudio

# Run a specific test method
pytest tests/test_ffmpeg.py::TestExtractAudio::test_creates_output_dir_and_calls_ffmpeg

# Run with coverage report
pytest --cov=app

# Run with coverage and show missing lines
pytest --cov=app --cov-report=term-missing
```

## Test Fixtures

Fixtures are defined in `tests/conftest.py`:

### `test_client`
An async `httpx.AsyncClient` configured with the FastAPI test app. Uses `ASGITransport` for in-process testing (no network).

### `test_db`
An async SQLAlchemy session connected to an in-memory SQLite database. Tables are created fresh for each test session.

### Database Override
The `get_db` dependency is overridden to use the test database:
```python
app.dependency_overrides[get_db] = override_get_db
```

This means all API tests hit the in-memory database, not your development database.

## Test Patterns

### Schema validation test
```python
class TestEditPlan:
    def test_valid_plan(self):
        plan = EditPlan(
            clip_id="test-1",
            source_video_id="vid-1",
            start_time=10.0,
            end_time=40.0,
            hook="The key insight is...",
            selection_reason="High engagement",
            score=ClipScore(hook_strength=0.8, ...),
            ...
        )
        assert plan.duration == 30.0

    def test_negative_start_time(self):
        with pytest.raises(ValidationError):
            EditPlan(start_time=-1.0, ...)
```

### API endpoint test
```python
async def test_upload_invalid_extension(test_client):
    files = {"file": ("test.txt", b"content", "text/plain")}
    response = await test_client.post("/api/videos/upload", files=files)
    assert response.status_code == 422
```

### FFmpeg mock test
```python
class TestExtractAudio:
    def test_creates_output_dir_and_calls_ffmpeg(self, tmp_path):
        video = tmp_path / "input.mp4"
        video.write_bytes(b"fake video")
        output = tmp_path / "out" / "audio.wav"

        with patch("app.video_pipeline.audio.run_ffmpeg") as mock:
            extract_audio(video, output)
            mock.assert_called_once()
            args = mock.call_args[0][0]
            assert "-vn" in args
            assert "-ar" in args
```

### Agent node test
```python
class TestScoreCandidatesNode:
    def test_scores_all_candidates(self):
        state = make_pipeline_state(candidates=[seg1, seg2, seg3])
        result = score_candidates_node(state)
        assert len(result["candidate_scores"]) == 3
        for score in result["candidate_scores"]:
            assert 0 <= score.overall <= 1
```

## Adding New Tests

1. **Choose the right file** based on what you're testing:
   - New schema → `test_schemas.py`
   - New endpoint → `test_api.py`
   - New FFmpeg operation → `test_ffmpeg.py`
   - New pipeline function → `test_pipeline.py`
   - New agent node → `test_agents.py`

2. **Follow existing patterns** in that file. Group related tests into classes.

3. **Mock external dependencies:**
   - FFmpeg subprocess calls → `unittest.mock.patch`
   - OpenAI API → Use `MockTranscriptionService`
   - File system → Use `tmp_path` fixture

4. **Run your new tests:**
   ```bash
   pytest tests/test_your_file.py -v
   ```

5. **Run the full suite** to check for regressions:
   ```bash
   pytest
   ```

## Configuration

Test configuration is in `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- `asyncio_mode = "auto"` — Async test functions are detected automatically, no decorator needed
- `testpaths = ["tests"]` — pytest looks for tests in the `tests/` directory
