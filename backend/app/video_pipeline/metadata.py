"""Metadata generation for clips (deterministic fallback)."""

from __future__ import annotations

import re
from collections import Counter

from app.schemas.clip import PublishMetadata
from app.schemas.transcript import TranscriptSegment

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "of", "by", "with", "from", "into", "about",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can",
    "it", "its", "this", "that", "these", "those",
    "i", "we", "you", "he", "she", "they", "me", "us", "him", "her", "them",
    "my", "our", "your", "his", "their",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "not", "no", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "than", "too", "very", "just",
})


def generate_metadata_heuristic(
    segment: TranscriptSegment,
    hook: str = "",
) -> PublishMetadata:
    """Generate basic metadata from a transcript segment.

    The agentic workflow produces higher-quality metadata via LLM.
    This is a deterministic fallback.
    """
    text = segment.text.strip()

    # Title: first sentence or first 60 chars
    sentences = re.split(r"[.!?]+", text)
    title = sentences[0].strip()[:80] if sentences else text[:80]

    # Description: first 2 sentences
    description = ". ".join(s.strip() for s in sentences[:2] if s.strip())
    if description and not description.endswith("."):
        description += "."

    # Hashtags: frequency-based keyword extraction
    raw_words = re.sub(r"[^\w\s]", "", text).lower().split()
    filtered = [w for w in raw_words if w not in _STOPWORDS and len(w) >= 4]
    hashtags = [word for word, _ in Counter(filtered).most_common(5)]

    if hook and hook not in title:
        title = hook[:80]

    return PublishMetadata(
        title=title,
        description=description,
        hashtags=hashtags,
    )
