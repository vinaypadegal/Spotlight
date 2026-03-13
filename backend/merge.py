"""
merge.py
--------
Fuses vision detections (from vision.py) with product/brand mentions found
in the video transcript (from ingest.py).

Pipeline
--------
1. extract_mentions()   — Ask Gemini to read the timestamped transcript and
                          return every product/brand mention it can find, each
                          anchored to a transcript timestamp.

2. merge()              — For each visually detected product:
                          • Attach nearby transcript snippets as context.
                          • If the brand was not identified visually, try to
                            resolve it from a nearby transcript mention.
                          • Mark detection_source as "vision", "transcript",
                            or "both".
                          Also surfaces products that were mentioned in the
                          transcript but never detected visually.

Output shape (merge return value)
----------------------------------
{
  "products": [
    {
      "name":                 str,
      "brand":                str | null,
      "brand_source":         "vision" | "transcript" | null,
      "category":             str,
      "confidence":           float | null,   # from vision; null if transcript-only
      "first_seen_at":        float,          # earliest timestamp in seconds
      "timestamps":           [float],        # all vision timestamps
      "transcript_mentions":  [               # nearby transcript hits
        { "timestamp": float, "context": str, "brand": str | null }
      ],
      "detection_source":     "vision" | "transcript" | "both",
    },
    ...
  ],
  "summary": {
    "total_products":        int,
    "vision_only":           int,
    "transcript_only":       int,
    "both":                  int,
    "brand_resolved_count":  int,   # brands filled in from transcript
  }
}
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# How many seconds before/after a vision frame's timestamp to search for
# relevant transcript context.
DEFAULT_CONTEXT_WINDOW = 15.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_nearby_snippets(
    snippets: List[Dict],
    timestamp: float,
    window: float,
) -> Tuple[str, List[Dict]]:
    """
    Return transcript snippets whose start time falls within
    [timestamp - window, timestamp + window] and a single joined text string.
    """
    nearby = [s for s in snippets if abs(s["start"] - timestamp) <= window]
    text = " ".join(s["text"] for s in nearby).strip()
    return text, nearby


def _build_extraction_prompt(timestamped_transcript: str) -> str:
    """
    Prompt that asks Gemini to extract structured product/brand mentions from
    a timestamped transcript.
    """
    return f"""You are a product and brand extraction assistant.

Analyze the following video transcript (each line is prefixed with its timestamp in [MM:SS.ss] format) and identify every product name and brand mention.

For each mention return:
- name: the product or item being discussed
- brand: the brand name if mentioned in the transcript; null if not explicitly named
- timestamp: the time in seconds when it is first mentioned (convert from the [MM:SS.ss] prefix)
- context: the exact 1–2 sentence quote from the transcript where this product/brand is mentioned

Return a JSON array:
[
  {{
    "name": "product name",
    "brand": "brand name or null",
    "timestamp": <float seconds>,
    "context": "exact quote"
  }}
]

Rules:
- Only include genuine product or brand references, not generic descriptions.
- If the same product is mentioned multiple times, include each mention with its own timestamp.
- Output raw JSON only — no markdown, no extra keys.

TRANSCRIPT:
{timestamped_transcript}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_mentions(
    transcript_data: Dict,
    api_key: Optional[str] = None,
) -> List[Dict]:
    """
    Use Gemini to extract structured product/brand mentions from a transcript.

    Args:
        transcript_data: Output of get_transcript() — must contain:
                           'transcript': list of {text, start, duration}
                           'text':        plain-text version (used for logging only)
        api_key:         Gemini API key; falls back to GEMINI_API_KEY env var.

    Returns:
        List of dicts: [{name, brand, timestamp, context}, ...]
        Each dict represents one product/brand mention found in the transcript.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY is not set. Add it to your .env file.")

    snippets: List[Dict] = transcript_data.get("transcript", [])
    if not snippets:
        logger.warning("No transcript snippets provided — skipping mention extraction")
        return []

    # Build a human-readable timestamped transcript for the model.
    # Format: [MM:SS.ss] text
    lines = []
    for s in snippets:
        mins = int(s["start"] // 60)
        secs = s["start"] % 60
        lines.append(f"[{mins:02d}:{secs:05.2f}] {s['text']}")
    timestamped_text = "\n".join(lines)

    logger.info(
        "Extracting product mentions from transcript (%d snippets, ~%d words)...",
        len(snippets),
        transcript_data.get("word_count", len(timestamped_text.split())),
    )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Content(
                parts=[types.Part.from_text(text=_build_extraction_prompt(timestamped_text))],
                role="user",
            )
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    mentions: List[Dict] = json.loads(response.text.strip())
    logger.info("Extracted %d product/brand mentions from transcript", len(mentions))
    return mentions


def merge(
    vision_frames: List[Dict],
    transcript_data: Optional[Dict],
    context_window: float = DEFAULT_CONTEXT_WINDOW,
    api_key: Optional[str] = None,
) -> Dict:
    """
    Merge vision detections with transcript product/brand mentions.

    Args:
        vision_frames:   Output of analyze_frames() / analyze_youtube_url() —
                         list of {timestamp, frame_path, products} dicts.
        transcript_data: Output of get_transcript() — has 'transcript' and 'text'.
                         Pass None to skip transcript enrichment entirely.
        context_window:  Seconds before/after each vision frame to look for
                         matching transcript snippets (default 15s).
        api_key:         Gemini API key; falls back to GEMINI_API_KEY env var.

    Returns:
        See module docstring for the full output schema.
    """
    snippets: List[Dict] = []
    transcript_mentions: List[Dict] = []

    # --- Step 1: extract structured mentions from transcript ---
    if transcript_data:
        snippets = transcript_data.get("transcript", [])
        try:
            transcript_mentions = extract_mentions(transcript_data, api_key=api_key)
        except Exception as e:
            logger.warning(
                "Transcript mention extraction failed — proceeding with vision only: %s", e
            )

    # -------------------------------------------------------------------
    # Step 2: seed the product registry from vision detections
    # Each entry is keyed by normalised "name|brand" so the same product
    # appearing in multiple frames is consolidated into one record.
    # -------------------------------------------------------------------
    registry: Dict[str, Dict] = {}

    for frame in vision_frames:
        ts: float = frame["timestamp"]

        for product in frame.get("products", []):
            name = (product.get("name") or "").strip()
            brand = (product.get("brand") or "").strip()
            if not name:
                continue

            # Use lowercased name+brand as the dedup key.
            # Products without a brand get a key ending in "|" so they can be
            # updated later if the brand is resolved from the transcript.
            key = f"{name.lower()}|{brand.lower()}"

            if key not in registry:
                registry[key] = {
                    "name": name,
                    "brand": brand or None,
                    "brand_source": "vision" if brand else None,
                    "category": product.get("category", "other"),
                    "confidence": product.get("confidence"),
                    "first_seen_at": ts,
                    "timestamps": [ts],
                    "transcript_mentions": [],
                    "detection_source": "vision",
                }
            else:
                entry = registry[key]
                entry["timestamps"].append(ts)
                if ts < entry["first_seen_at"]:
                    entry["first_seen_at"] = ts
                # Take the highest confidence seen across frames
                if (
                    product.get("confidence") is not None
                    and (entry["confidence"] is None or product["confidence"] > entry["confidence"])
                ):
                    entry["confidence"] = product["confidence"]

    # -------------------------------------------------------------------
    # Step 3: enrich registry with transcript mentions
    # -------------------------------------------------------------------
    brand_resolved_count = 0
    transcript_only_count = 0

    for mention in transcript_mentions:
        m_name = (mention.get("name") or "").strip()
        m_brand = (mention.get("brand") or "").strip()
        m_ts = float(mention.get("timestamp") or 0.0)
        m_context = (mention.get("context") or "").strip()

        if not m_name:
            continue

        mention_payload = {
            "timestamp": m_ts,
            "context": m_context,
            "brand": m_brand or None,
        }

        # --- Try to match this mention to an existing vision detection ---
        # Matching rule: one name is a substring of the other (case-insensitive).
        # This is intentionally lenient — e.g. "Air Max" matches "Nike Air Max 90".
        matched_key: Optional[str] = None
        m_name_lower = m_name.lower()

        for key, entry in registry.items():
            entry_name_lower = entry["name"].lower()
            if m_name_lower in entry_name_lower or entry_name_lower in m_name_lower:
                matched_key = key
                break

        if matched_key:
            entry = registry[matched_key]
            entry["transcript_mentions"].append(mention_payload)
            entry["detection_source"] = "both"

            # Resolve missing brand from transcript
            if not entry["brand"] and m_brand:
                old_key = matched_key
                # Re-key the registry entry with the resolved brand
                new_key = f"{entry['name'].lower()}|{m_brand.lower()}"
                entry["brand"] = m_brand
                entry["brand_source"] = "transcript"
                brand_resolved_count += 1
                logger.debug(
                    "Brand resolved from transcript: '%s' → '%s'",
                    entry["name"], m_brand,
                )
                # Move to the new key if it doesn't already exist
                if new_key not in registry:
                    registry[new_key] = entry
                    del registry[old_key]
        else:
            # Product mentioned in transcript but never detected visually
            key = f"{m_name.lower()}|{m_brand.lower()}"
            if key not in registry:
                registry[key] = {
                    "name": m_name,
                    "brand": m_brand or None,
                    "brand_source": "transcript" if m_brand else None,
                    "category": "other",
                    "confidence": None,
                    "first_seen_at": m_ts,
                    "timestamps": [],
                    "transcript_mentions": [mention_payload],
                    "detection_source": "transcript",
                }
                transcript_only_count += 1
            else:
                # Already registered (e.g. duplicate mention) — just append
                registry[key]["transcript_mentions"].append(mention_payload)

    # -------------------------------------------------------------------
    # Step 4: sort by first appearance and build summary
    # -------------------------------------------------------------------
    product_list = sorted(registry.values(), key=lambda p: p["first_seen_at"])

    vision_only = sum(1 for p in product_list if p["detection_source"] == "vision")
    both = sum(1 for p in product_list if p["detection_source"] == "both")

    logger.info(
        "Merge complete — %d total products "
        "(%d vision-only, %d transcript-only, %d both, %d brands resolved from transcript)",
        len(product_list), vision_only, transcript_only_count, both, brand_resolved_count,
    )

    return {
        "products": product_list,
        "summary": {
            "total_products": len(product_list),
            "vision_only": vision_only,
            "transcript_only": transcript_only_count,
            "both": both,
            "brand_resolved_count": brand_resolved_count,
        },
    }
