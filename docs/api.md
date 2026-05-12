# API Reference

Base URL: `http://localhost:8000`

Interactive documentation (Swagger UI): http://localhost:8000/docs

---

## Health Check

```
GET /api/health
```

**Response:**
```json
{
  "status": "ok",
  "app": "ClipForge AI",
  "version": "0.1.0"
}
```

---

## Video Upload

```
POST /api/videos/upload
Content-Type: multipart/form-data
```

Upload a video file for processing. The file is streamed to disk in 64KB chunks (never fully loaded into memory).

### Request

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | File | *(required)* | Video file (.mp4, .mov, .avi, .mkv, .webm). Max 500MB. |
| `target_audience` | string | `""` | Description of the target audience |
| `desired_clip_count` | int | `5` | Number of clips to generate (1–20) |
| `clip_duration_min` | int | `30` | Minimum clip duration in seconds (10–120) |
| `clip_duration_max` | int | `60` | Maximum clip duration in seconds (15–180) |
| `target_platforms` | string | `"youtube_shorts"` | Target platform: `youtube_shorts`, `tiktok`, `instagram_reels`, `linkedin` |
| `tone` | string | `"professional"` | Content tone: `professional`, `educational`, `energetic`, `humorous` |

### Response (201 Created)

```json
{
  "id": "a1b2c3d4e5f6...",
  "original_filename": "webinar.mp4",
  "status": "uploaded",
  "current_stage_message": "Video uploaded successfully",
  "error_message": null,
  "clip_count": 0,
  "created_at": "2026-05-09T12:00:00Z",
  "updated_at": "2026-05-09T12:00:00Z"
}
```

### Example (curl)

```bash
curl -X POST http://localhost:8000/api/videos/upload \
  -F "file=@webinar.mp4" \
  -F "desired_clip_count=3" \
  -F "clip_duration_min=30" \
  -F "clip_duration_max=60" \
  -F "target_platforms=youtube_shorts" \
  -F "tone=professional" \
  -F "target_audience=SaaS founders"
```

### Errors

| Status | Cause |
|--------|-------|
| 422 | Unsupported file extension, invalid MIME type, or empty file |
| 413 | File exceeds `MAX_UPLOAD_SIZE_MB` |

---

## Jobs

### List Jobs

```
GET /api/jobs?page=1&page_size=20
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | `1` | Page number (≥ 1) |
| `page_size` | int | `20` | Results per page (1–100) |

**Response:**

```json
{
  "jobs": [
    {
      "id": "a1b2c3d4...",
      "original_filename": "webinar.mp4",
      "status": "ready_for_review",
      "current_stage_message": "3 clips ready for review",
      "error_message": null,
      "clip_count": 3,
      "created_at": "2026-05-09T12:00:00Z",
      "updated_at": "2026-05-09T12:05:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### Get Job Detail

```
GET /api/jobs/{job_id}
```

**Response:** `VideoJobDetail` — extends `VideoJobResponse` with:

```json
{
  "id": "a1b2c3d4...",
  "original_filename": "webinar.mp4",
  "status": "ready_for_review",
  "current_stage_message": "3 clips ready for review",
  "error_message": null,
  "clip_count": 3,
  "file_size_bytes": 52428800,
  "storage_path": "jobs/a1b2c3d4/original.mp4",
  "params": {
    "target_audience": "SaaS founders",
    "desired_clip_count": 3,
    "clip_duration_min": 30,
    "clip_duration_max": 60,
    "target_platforms": ["youtube_shorts"],
    "tone": "professional"
  },
  "transcript_path": "jobs/a1b2c3d4/transcript.json",
  "edit_plans_path": "jobs/a1b2c3d4/edit_plans.json",
  "created_at": "2026-05-09T12:00:00Z",
  "updated_at": "2026-05-09T12:05:00Z"
}
```

| Status | Cause |
|--------|-------|
| 404 | Job not found |

### List Job Clips

```
GET /api/jobs/{job_id}/clips
```

**Response:** Array of `CandidateClipResponse`:

```json
[
  {
    "id": "clip-uuid-1",
    "job_id": "a1b2c3d4...",
    "clip_index": 0,
    "status": "pending",
    "edit_plan": {
      "clip_id": "clip-uuid-1",
      "source_video_id": "a1b2c3d4...",
      "start_time": 120.5,
      "end_time": 165.0,
      "format": "vertical_9_16",
      "target_platform": "youtube_shorts",
      "hook": "The key insight we found was...",
      "selection_reason": "High engagement signals",
      "score": {
        "hook_strength": 0.85,
        "standalone_clarity": 0.72,
        "insight_value": 0.90,
        "virality_potential": 0.65,
        "audience_fit": 0.78,
        "overall": 0.78
      },
      "caption_style": {
        "type": "basic",
        "font": "Inter",
        "position": "bottom",
        "primary_color": "#FFFFFF",
        "highlight_color": "#2DB8A0",
        "background_color": "#111827"
      },
      "visual_edits": [],
      "audio": {
        "normalize": true,
        "noise_reduction": false
      },
      "metadata": {
        "title": "The Key Insight We Found Was...",
        "description": "The key insight we found was that most teams...",
        "hashtags": ["#SaaS", "#ProductManagement", "#Insights"]
      }
    },
    "rendered_url": "/storage/jobs/a1b2c3d4/clips/clip_0.mp4",
    "transcript_snippet": "The key insight we found was that most teams underestimate...",
    "created_at": "2026-05-09T12:05:00Z",
    "updated_at": "2026-05-09T12:05:00Z"
  }
]
```

---

## Clips

### Approve Clip

```
POST /api/clips/{clip_id}/approve
```

**Response:**
```json
{
  "clip_id": "clip-uuid-1",
  "action": "approve",
  "success": true,
  "message": "Clip approved"
}
```

### Reject Clip

```
POST /api/clips/{clip_id}/reject
```

**Response:**
```json
{
  "clip_id": "clip-uuid-1",
  "action": "reject",
  "success": true,
  "message": "Clip rejected"
}
```

### Regenerate Metadata

```
POST /api/clips/{clip_id}/regenerate-metadata
```

Re-runs metadata generation (title, description, hashtags) for a single clip.

**Response:**
```json
{
  "clip_id": "clip-uuid-1",
  "action": "regenerate-metadata",
  "success": true,
  "message": "Metadata regenerated"
}
```

### Re-render Clip

```
POST /api/clips/{clip_id}/render
```

Re-runs FFmpeg rendering for a single clip using its current `EditPlan`.

**Response:**
```json
{
  "clip_id": "clip-uuid-1",
  "action": "render",
  "success": true,
  "message": "Clip re-rendered"
}
```

### Download Clip

```
GET /api/clips/{clip_id}/download
```

Returns the rendered `.mp4` file as a binary download.

**Response:** `video/mp4` file attachment

| Status | Cause |
|--------|-------|
| 404 | Clip not found or not yet rendered |

---

## Brand Profile

### Get Brand Profile

```
GET /api/brand-profile
```

Returns the current brand profile or defaults if none is set.

**Response:**
```json
{
  "id": "default",
  "brand_name": "ClipForge",
  "primary_color": "#2DB8A0",
  "secondary_color": "#111827",
  "accent_color": "#6366F1",
  "font": "Inter",
  "caption_type": "basic",
  "caption_position": "bottom",
  "caption_primary_color": "#FFFFFF",
  "caption_highlight_color": "#2DB8A0",
  "caption_background_color": "#111827",
  "cta_text": "",
  "logo_url": "",
  "outro_text": "",
  "platform_presets": []
}
```

### Update Brand Profile

```
PUT /api/brand-profile
Content-Type: application/json
```

Accepts a partial or full `BrandProfile` object. Only included fields are updated.

**Request body:**
```json
{
  "brand_name": "My Brand",
  "primary_color": "#FF6B35",
  "font": "Montserrat"
}
```

**Response:** Full updated `BrandProfile` (same schema as GET).

---

## Job Status Values

| Status | Description |
|--------|-------------|
| `pending` | Job created, not yet started |
| `uploaded` | File uploaded, waiting for worker |
| `extracting_audio` | FFmpeg extracting audio track |
| `transcribing` | Whisper API transcribing audio |
| `segmenting` | Agent pipeline: segmenting transcript |
| `selecting_clips` | Agent pipeline: scoring and selecting clips |
| `generating_edit_plans` | Agent pipeline: creating edit plans |
| `rendering` | FFmpeg rendering clips |
| `generating_metadata` | Agent pipeline: generating metadata |
| `ready_for_review` | Processing complete, clips ready for user review |
| `approved` | User approved clips |
| `failed` | Processing failed (check `error_message`) |

## Clip Status Values

| Status | Description |
|--------|-------------|
| `pending` | Clip generated, awaiting review |
| `approved` | User approved the clip |
| `rejected` | User rejected the clip |

## Error Response Format

All errors return a JSON body:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request |
| 404 | Resource not found |
| 413 | File too large |
| 422 | Validation error (bad input) |
| 500 | Internal server error |
