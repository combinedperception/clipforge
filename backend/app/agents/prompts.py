"""Prompt templates for agent nodes."""

TRANSCRIPT_CLEANING_PROMPT = """You are a transcript cleaning specialist.

Given the following raw transcript, clean it up:
- Remove filler words (um, uh, like, you know) where they don't add meaning
- Fix obvious transcription errors
- Preserve all timestamps exactly
- Keep the speaker's voice and style
- Do NOT change the meaning of any statement
- Do NOT add information that wasn't in the original

Return the cleaned transcript as a JSON array of segments, each with:
- "id": segment ID (preserve from input)
- "start_time": float
- "end_time": float
- "text": cleaned text
- "speaker": speaker name if known

Raw transcript segments:
{segments_json}
"""

SEGMENTATION_PROMPT = """You are a video content segmentation expert.

Given this transcript, identify the best candidate moments for short-form video clips.

Requirements:
- Each candidate should be {min_duration}-{max_duration} seconds long
- Each candidate must make sense as a standalone clip
- Look for strong hooks, clear insights, surprising statements, or compelling stories
- Prefer moments with high information density
- Avoid segments that start or end mid-sentence
- Target audience: {target_audience}
- Desired tone: {tone}

Return a JSON array of candidates, each with:
- "start_time": float (from the transcript timestamps)
- "end_time": float
- "text": the transcript text for this segment
- "reason": why this is a good candidate (1 sentence)

Transcript:
{transcript_text}
"""

CLIP_SELECTION_PROMPT = """You are a viral content strategist.

Score and rank these candidate clip moments. Select the top {top_n} clips.

For each candidate, provide scores (0.0 to 1.0) on:
- hook_strength: How compelling is the opening? Would someone stop scrolling?
- standalone_clarity: Does this make sense without context?
- insight_value: Is there a valuable takeaway?
- virality_potential: Would people share this?
- audience_fit: Does this match the target audience ({target_audience})?

Return a JSON array of the top {top_n} clips, each with:
- "start_time": float
- "end_time": float
- "text": transcript text
- "hook": the strongest opening line
- "selection_reason": why this clip was selected (1-2 sentences)
- "score": {{
    "hook_strength": float,
    "standalone_clarity": float,
    "insight_value": float,
    "virality_potential": float,
    "audience_fit": float,
    "overall": float (weighted average)
  }}

Candidates:
{candidates_json}
"""

EDIT_PLAN_PROMPT = """You are a professional video editor creating structured edit plans.

For each selected clip, create a detailed edit plan. You are deciding HOW the clip
should be edited, but you will NOT execute the edits yourself.

For each clip, specify:
1. Exact start and end times
2. Caption style (font, colors, position)
3. Any visual edits (zooms, CTA bars) with precise timestamps
4. Audio settings (normalize, noise reduction)
5. A strong hook line

Return a JSON array of edit plans following this exact schema:
{{
  "clip_id": "clip_XXX",
  "source_video_id": "{video_id}",
  "start_time": float,
  "end_time": float,
  "format": "vertical_9_16",
  "target_platform": "youtube_shorts",
  "hook": "string",
  "selection_reason": "string",
  "score": {{ ... }},
  "caption_style": {{
    "type": "basic",
    "font": "Inter",
    "position": "bottom",
    "primary_color": "#FFFFFF",
    "highlight_color": "#2DB8A0",
    "background_color": "#111827"
  }},
  "visual_edits": [],
  "audio": {{"normalize": true, "noise_reduction": false}},
  "metadata": {{"title": "", "description": "", "hashtags": []}}
}}

Selected clips:
{selected_clips_json}
"""

METADATA_PROMPT = """You are a social media content strategist.

Generate compelling metadata for each video clip to maximize engagement.

For each clip, create:
- title: Catchy, under 80 characters, curiosity-driving
- description: 1-2 sentences, clear value proposition, includes a call to action
- hashtags: 3-7 relevant hashtags (without # prefix)

Target platform: {target_platform}
Target audience: {target_audience}
Tone: {tone}

Return a JSON array of metadata objects:
{{
  "clip_id": "string",
  "title": "string",
  "description": "string",
  "hashtags": ["string"]
}}

Clips:
{clips_json}
"""
