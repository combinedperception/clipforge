"""Transcription service abstraction."""

from __future__ import annotations

import abc
import json
import math
from pathlib import Path

from app.core.logging import get_logger
from app.schemas.transcript import Transcript, TranscriptSegment, WordTimestamp

logger = get_logger(__name__)

# OpenAI Whisper API file-size limit (25 MB).
_WHISPER_MAX_BYTES = 25 * 1024 * 1024


class TranscriptionService(abc.ABC):
    """Abstract interface for audio-to-text transcription."""

    @abc.abstractmethod
    async def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        """Transcribe an audio file and return structured transcript."""


class OpenAIWhisperService(TranscriptionService):
    """Transcription via OpenAI Whisper API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    # ── helpers ───────────────────────────────────────────

    @staticmethod
    def _compress_audio(wav_path: Path) -> Path:
        """Compress a WAV file to MP3 to stay under the Whisper size limit.

        Returns the path to the compressed file (or the original if already
        small enough).
        """
        if wav_path.stat().st_size <= _WHISPER_MAX_BYTES:
            return wav_path

        from app.video_pipeline.audio import run_ffmpeg

        mp3_path = wav_path.with_suffix(".mp3")
        run_ffmpeg([
            "-i", str(wav_path),
            "-ac", "1",
            "-ar", "16000",
            "-b:a", "64k",
            str(mp3_path),
        ])
        logger.info(
            "audio_compressed",
            original_size=wav_path.stat().st_size,
            compressed_size=mp3_path.stat().st_size,
        )
        return mp3_path

    @staticmethod
    def _split_audio(audio_path: Path, max_chunk_bytes: int = _WHISPER_MAX_BYTES) -> list[tuple[Path, float]]:
        """Split an audio file into chunks that each fit under the Whisper API
        size limit.  Returns a list of ``(chunk_path, start_time)`` tuples where
        *start_time* is the absolute position (seconds) in the original audio.

        Chunks are re-encoded to PCM WAV so that boundaries are sample-accurate
        (stream-copy would snap to the nearest keyframe).
        """
        file_size = audio_path.stat().st_size
        if file_size <= max_chunk_bytes:
            return [(audio_path, 0.0)]

        from app.video_pipeline.audio import run_ffmpeg
        import subprocess

        # Probe duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True,
        )
        total_duration = float(probe.stdout.strip())

        # Estimate chunk duration so each chunk is comfortably under the limit.
        n_chunks = math.ceil(file_size / (max_chunk_bytes * 0.9))
        chunk_duration = total_duration / n_chunks

        chunks: list[tuple[Path, float]] = []
        for i in range(n_chunks):
            start = i * chunk_duration
            # Re-encode to MP3 (not stream copy) for accurate chunk boundaries.
            # Using MP3 instead of WAV keeps file size within the Whisper limit.
            chunk_path = audio_path.parent / f"{audio_path.stem}_chunk{i}.mp3"
            args = [
                "-ss", str(start),
                "-i", str(audio_path),
                "-t", str(chunk_duration),
                "-ac", "1",
                "-ar", "16000",
                "-b:a", "64k",
                str(chunk_path),
            ]
            run_ffmpeg(args)
            chunks.append((chunk_path, start))
            logger.info("audio_chunk_created", chunk=i, start=f"{start:.1f}s", path=str(chunk_path))

        return chunks

    # ── main method ───────────────────────────────────────

    async def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        import openai

        client = openai.AsyncOpenAI(api_key=self.api_key)

        logger.info("transcription_start", audio_path=str(audio_path), provider="openai")

        # Compress WAV → MP3 if needed
        send_path = self._compress_audio(audio_path)

        # Split into chunks if still too large
        chunks = self._split_audio(send_path)

        all_segments: list[TranscriptSegment] = []
        full_texts: list[str] = []
        seg_counter = 0

        for chunk_path, chunk_start in chunks:
            # Each chunk's offset is its absolute position in the original audio
            time_offset = chunk_start

            with open(chunk_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )

            # Build a flat list of word timestamps for this chunk
            chunk_words: list[WordTimestamp] = []
            if hasattr(response, "words") and response.words:
                chunk_words = [
                    WordTimestamp(
                        word=w.word,
                        start=w.start + time_offset,
                        end=w.end + time_offset,
                    )
                    for w in response.words
                ]

            for seg in response.segments or []:
                # Assign words that fall within this segment's time range
                seg_start = seg.start + time_offset
                seg_end = seg.end + time_offset
                words = [
                    w for w in chunk_words
                    if w.start >= seg_start - 0.05 and w.end <= seg_end + 0.05
                ]
                all_segments.append(
                    TranscriptSegment(
                        id=f"seg_{seg_counter:04d}",
                        start_time=seg_start,
                        end_time=seg_end,
                        text=seg.text.strip(),
                        words=words,
                    )
                )
                seg_counter += 1

            full_texts.append(response.text or "")

        full_text = " ".join(full_texts).strip()
        duration = all_segments[-1].end_time if all_segments else 0

        # Clean up temporary chunk/compressed files
        for chunk_path, _ in chunks:
            if chunk_path != audio_path:
                chunk_path.unlink(missing_ok=True)
        if send_path != audio_path:
            send_path.unlink(missing_ok=True)

        logger.info(
            "transcription_complete",
            segment_count=len(all_segments),
            word_count=len(full_text.split()),
            chunks_used=len(chunks),
        )

        return Transcript(
            video_id="",
            language=language,
            segments=all_segments,
            full_text=full_text,
            duration_seconds=duration,
        )


class MockTranscriptionService(TranscriptionService):
    """Mock transcription for testing – returns a pre-built transcript."""

    def __init__(self, fixture_path: Path | None = None):
        self.fixture_path = fixture_path

    async def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        logger.info("mock_transcription", audio_path=str(audio_path))

        if self.fixture_path and self.fixture_path.exists():
            data = json.loads(self.fixture_path.read_text())
            return Transcript.model_validate(data)

        # Generate a simple mock transcript
        return Transcript(
            video_id="mock",
            language=language,
            segments=[
                TranscriptSegment(
                    id="seg_0000",
                    start_time=0.0,
                    end_time=30.0,
                    text="This is a sample transcript segment for testing purposes.",
                ),
                TranscriptSegment(
                    id="seg_0001",
                    start_time=30.0,
                    end_time=60.0,
                    text="It contains multiple segments with timestamps.",
                ),
                TranscriptSegment(
                    id="seg_0002",
                    start_time=60.0,
                    end_time=90.0,
                    text="The AI will analyze these segments to find the best clips.",
                ),
            ],
            full_text=(
                "This is a sample transcript segment for testing purposes. "
                "It contains multiple segments with timestamps. "
                "The AI will analyze these segments to find the best clips."
            ),
            duration_seconds=90.0,
        )


def get_transcription_service(api_key: str = "") -> TranscriptionService:
    """Factory: return the appropriate transcription service."""
    if api_key:
        return OpenAIWhisperService(api_key=api_key)
    return MockTranscriptionService()
