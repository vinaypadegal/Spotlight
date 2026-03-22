"""
merge.py
--------
Fuses vision detections (from vision.py) with product/brand mentions found
in the video transcript (from ingest.py), then emits a flat list of timed
detection events ready for the frontend ad overlay.

Pipeline
--------
1. extract_mentions()   — Ask Gemini to read the timestamped transcript and
                          return every product/brand mention it can find, each
                          anchored to a transcript timestamp.

2. merge()              — Consolidates vision detections into time-windowed
                          intervals, uses transcript mentions to resolve missing
                          brands, then flattens everything into a sorted list
                          of individual detection events.

3. enrich_thumbnails()  — (stub) Fill in thumbnail_url for each detection.
                          To be implemented in a later iteration.

Output shape (merge return value)
----------------------------------
{
  "video_id":  str,
  "title":     str | null,
  "duration":  float | null,   # video length in seconds
  "status":    "complete",
  "detections": [
    {
      "id":           "det_001",   # sequential, zero-padded, sorted by show_at
      "name":         str,
      "brand":        str | null,
      "category":     str,
      "show_at":      float,       # seconds — when to show the ad overlay
      "hide_at":      float,       # seconds — when to hide it
      "confidence":   float | null,
      "shopping_url":  str | null,  # real product URL (enrich.py) or Google Shopping search URL
      "thumbnail_url": str | null,  # product image (enrich.py); null when enrichment is off
      "price":         str | null,  # price string e.g. "$29.99" (enrich.py); null when off
      "snippet":       str | null,  # short product description (enrich.py); null when off
      "source":        str | null   # retailer name e.g. "Amazon" (enrich.py); null when off
    },
    ...
  ],
  "summary": {
    "total_products":       int,
    "total_detections":     int,
    "brand_resolved_count": int
  }
}

Detection windowing rules
--------------------------
• Each raw vision timestamp spawns a window [ts, ts + DETECTION_WINDOW_S].
• If a subsequent timestamp falls within MERGE_GAP_S seconds of the current
  window's end, the window is extended: end = max(end, ts + DETECTION_WINDOW_S).
• Otherwise a new detection window is started.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Anchor to project root so the path is consistent regardless of launch directory
_PROJECT_ROOT = Path(__file__).parent.parent
DETECTIONS_DIR = str(_PROJECT_ROOT / "data" / "detections")
os.makedirs(DETECTIONS_DIR, exist_ok=True)

# Default duration to extend a detection window past a frame timestamp.
DETECTION_WINDOW_S: float = 5.0

# If the next raw timestamp is within this many seconds of the current window's
# end, the windows are merged rather than creating a new detection.
MERGE_GAP_S: float = 10.0

# Seconds before/after a transcript mention's timestamp to search for a
# matching vision product (used in time-aware matching).
DEFAULT_CONTEXT_WINDOW: float = 15.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _shopping_url(name: str, brand: Optional[str]) -> Optional[str]:
    """Build a Google Shopping search URL for a product."""
    query = f"{brand} {name}".strip() if brand else name.strip()
    if not query:
        return None
    return f"https://www.google.com/search?tbm=shop&q={quote_plus(query)}"


def _build_detections(
    timestamps: List[float],
    detection_window: float = DETECTION_WINDOW_S,
    merge_gap: float = MERGE_GAP_S,
) -> List[Dict]:
    """
    Collapse a list of raw frame timestamps into merged detection windows.

    Algorithm:
      1. Sort timestamps.
      2. Open a window [ts, ts + detection_window] at the first timestamp.
      3. For each subsequent ts:
           - If ts < current_end + merge_gap  →  extend: end = max(end, ts + detection_window)
           - Otherwise                         →  save the current window, open a new one.
      4. Save the final window.

    Returns a list of {"show_at": float, "hide_at": float} dicts.
    """
    if not timestamps:
        return []

    sorted_ts = sorted(timestamps)
    detections: List[Dict] = []

    start = sorted_ts[0]
    end   = start + detection_window

    for ts in sorted_ts[1:]:
        if ts < end + merge_gap:
            end = max(end, ts + detection_window)
        else:
            detections.append({"show_at": round(start, 3), "hide_at": round(end, 3)})
            start = ts
            end   = ts + detection_window

    detections.append({"show_at": round(start, 3), "hide_at": round(end, 3)})
    return detections


def _name_matches(a: str, b: str) -> bool:
    """Return True if one name is a substring of the other (case-insensitive)."""
    a, b = a.lower(), b.lower()
    return a in b or b in a


def _find_matching_key(
    registry: Dict[str, Dict],
    m_name: str,
    m_ts: float,
    context_window: float,
) -> Optional[str]:
    """
    Find the registry key whose product best matches a transcript mention.

    Matching is done in two passes:
      1. Time-aware  — name matches AND any of the product's vision timestamps
                       fall within context_window seconds of m_ts.
      2. Name-only   — name matches regardless of timestamp (fallback for
                       cases where the transcript timestamp is imprecise).

    Returns the first matching key, or None.
    """
    # Pass 1: time-aware (preferred)
    for key, entry in registry.items():
        if not _name_matches(m_name, entry["name"]):
            continue
        if any(abs(ts - m_ts) <= context_window for ts in entry["_raw_timestamps"]):
            return key

    # Pass 2: name-only fallback
    # for key, entry in registry.items():
    #     if _name_matches(m_name, entry["name"]):
    #         return key

    return None


def _build_extraction_prompt(timestamped_transcript: str) -> str:
    return f"""You are a product and brand extraction assistant.

Analyze the following video transcript (each line is prefixed with its timestamp in [MM:SS.ss] format) and identify every product name and brand mention.

For each mention return:
- name: the product or item being discussed
- brand: the brand name if mentioned in the transcript; null if not explicitly named
- timestamp: the time in seconds when it is first mentioned (convert from the [MM:SS.ss] prefix)

Return a JSON array:
[
  {{
    "name": "product name",
    "brand": "brand name or null",
    "timestamp": <float seconds>
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
                           'text':        plain-text version (for logging)
        api_key:         Gemini API key; falls back to GEMINI_API_KEY env var.

    Returns:
        List of {name, brand, timestamp} dicts — one per mention found.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY is not set. Add it to your .env file.")

    snippets: List[Dict] = transcript_data.get("transcript", [])
    if not snippets:
        logger.warning("No transcript snippets provided — skipping mention extraction")
        return []

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
    video_id: Optional[str] = None,
    title: Optional[str] = None,
    duration: Optional[float] = None,
    context_window: float = DEFAULT_CONTEXT_WINDOW,
    detection_window: float = DETECTION_WINDOW_S,
    merge_gap: float = MERGE_GAP_S,
    api_key: Optional[str] = None,
) -> Dict:
    """
    Merge vision detections with transcript product/brand mentions and emit
    a flat list of timed detection events, sorted by show_at.

    Args:
        vision_frames:    Output of analyze_frames() / analyze_youtube_url().
        transcript_data:  Output of get_transcript(). Pass None to skip
                          transcript enrichment.
        video_id:         YouTube video ID (included in output for reference).
        title:            Video title (included in output; optional).
        duration:         Video duration in seconds (included in output; optional).
        context_window:   Seconds around a transcript mention's timestamp used
                          when matching it to a vision detection (default 15s).
        detection_window: Duration (seconds) to extend each detection past its
                          frame timestamp (default 5s).
        merge_gap:        Max gap (seconds) between a new timestamp and the
                          current window's end before a new window is opened
                          (default 10s).
        api_key:          Gemini API key; falls back to GEMINI_API_KEY env var.

    Returns:
        See module docstring for the full output schema.
    """
    # -------------------------------------------------------------------
    # Step 1: Extract product/brand mentions from transcript
    # -------------------------------------------------------------------
    transcript_mentions: List[Dict] = []
    if transcript_data:
        try:
            transcript_mentions = extract_mentions(transcript_data, api_key=api_key)
        except Exception as e:
            logger.warning(
                "Transcript mention extraction failed — proceeding with vision only: %s", e
            )

    # -------------------------------------------------------------------
    # Step 2: Seed the product registry from vision detections.
    #
    # Internal registry fields (stripped before output):
    #   _raw_timestamps  — all raw frame timestamps for this product
    # -------------------------------------------------------------------
    registry: Dict[str, Dict] = {}

    for frame in vision_frames:
        ts: float = frame["timestamp"]

        for product in frame.get("products", []):
            name  = (product.get("name")  or "").strip()
            brand = (product.get("brand") or "").strip()
            if not name or not brand:
                continue

            key = f"{name.lower()}|{brand.lower()}"

            if key not in registry:
                registry[key] = {
                    "name":            name,
                    "brand":           brand or None,
                    "category":        product.get("category", "other"),
                    "confidence":      product.get("confidence"),
                    "_raw_timestamps": [ts],
                }
            else:
                entry = registry[key]
                entry["_raw_timestamps"].append(ts)
                if (
                    product.get("confidence") is not None
                    and (
                        entry["confidence"] is None
                        or product["confidence"] > entry["confidence"]
                    )
                ):
                    entry["confidence"] = product["confidence"]

    # -------------------------------------------------------------------
    # Step 3: Enrich registry with transcript mentions
    # -------------------------------------------------------------------
    brand_resolved_count = 0

    for mention in transcript_mentions:
        m_name  = (mention.get("name")  or "").strip()
        m_brand = (mention.get("brand") or "").strip()
        m_ts    = float(mention.get("timestamp") or 0.0)

        if not m_name:
            continue

        matched_key = _find_matching_key(registry, m_name, m_ts, context_window)

        if matched_key:
            entry = registry[matched_key]

            # Resolve missing brand from transcript — only if transcript also
            # has a concrete brand; don't overwrite with an empty string.
            if not entry["brand"] and m_brand:
                old_key = matched_key
                new_key = f"{entry['name'].lower()}|{m_brand.lower()}"
                entry["brand"] = m_brand
                brand_resolved_count += 1
                logger.debug(
                    "Brand resolved from transcript: '%s' → '%s'",
                    entry["name"], m_brand,
                )
                if new_key not in registry:
                    registry[new_key] = entry
                    del registry[old_key]
        else:
            # Product mentioned in transcript but never visually detected —
            # skip entirely. We only surface products the model actually saw.
            logger.debug(
                "Ignoring transcript-only mention '%s' (not seen visually).", m_name
            )

    # -------------------------------------------------------------------
    # Step 4: Flatten into a sorted list of individual detection events.
    #
    # Each (product, detection_window) pair becomes its own entry so the
    # frontend can treat every row as an independent "show ad at T" event.
    # IDs are assigned after sorting by show_at.
    # -------------------------------------------------------------------
    flat: List[Dict] = []

    # Belt-and-suspenders: drop any registry entry that still has no brand.
    # This can happen if vision refinement fell back to raw results (e.g. after
    # a 503) or a transcript mention snuck through without a resolved brand.
    brandless = [k for k, v in registry.items() if not (v.get("brand") or "").strip()]
    if brandless:
        logger.debug(
            "Dropping %d brand-less product(s) before flattening: %s",
            len(brandless),
            [registry[k]["name"] for k in brandless],
        )
        for k in brandless:
            del registry[k]

    for entry in registry.values():
        raw_ts  = entry.pop("_raw_timestamps", [])
        windows = _build_detections(raw_ts, detection_window, merge_gap)

        shop_url = _shopping_url(entry["name"], entry["brand"])

        for window in windows:
            flat.append({
                "name":          entry["name"],
                "brand":         entry["brand"],
                "category":      entry["category"],
                "show_at":       window["show_at"],
                "hide_at":       window["hide_at"],
                "confidence":    entry["confidence"],
                "shopping_url":  shop_url,
                "thumbnail_url": None,   # populated by enrich.enrich_detections()
                "price":         None,   # populated by enrich.enrich_detections()
                "snippet":       None,   # populated by enrich.enrich_detections()
                "source":        None,   # populated by enrich.enrich_detections()
            })

    # Sort by show_at, then assign sequential IDs
    flat.sort(key=lambda d: d["show_at"])
    for i, det in enumerate(flat, start=1):
        det["id"] = f"det_{i:03d}"

    # Re-order keys so id comes first (cosmetic)
    detections = [
        {
            "id":            d["id"],
            "name":          d["name"],
            "brand":         d["brand"],
            "category":      d["category"],
            "show_at":       d["show_at"],
            "hide_at":       d["hide_at"],
            "confidence":    d["confidence"],
            "shopping_url":  d["shopping_url"],
            "thumbnail_url": d["thumbnail_url"],
            "price":         d.get("price"),
            "snippet":       d.get("snippet"),
            "source":        d.get("source"),
        }
        for d in flat
    ]

    # Unique product count = number of distinct name|brand combinations
    unique_products = len(registry)

    logger.info(
        "Merge complete — %d detections across %d products "
        "(%d brands resolved from transcript)",
        len(detections), unique_products, brand_resolved_count,
    )

    result = {
        "video_id":   video_id,
        "title":      title,
        "duration":   duration,
        "status":     "complete",
        "detections": detections,
        "summary": {
            "total_products":       unique_products,
            "total_detections":     len(detections),
            "brand_resolved_count": brand_resolved_count,
        },
    }

    # --- Persist to data/detections/<video_id>.json ---
    if video_id:
        detections_path = Path(DETECTIONS_DIR) / f"{video_id}.json"
        try:
            with open(detections_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            logger.info("Detections saved to '%s'", detections_path)
        except Exception as e:
            logger.error("Failed to save detections file '%s': %s", detections_path, e)

    return result


def enrich_thumbnails(result: Dict, api_key: Optional[str] = None) -> Dict:
    """
    Populate thumbnail_url for each detection in a merge() result.

    This is a stub — the actual implementation will query a product image API
    (e.g. Google Custom Search, SerpAPI, or similar) to find a representative
    thumbnail for each brand + product name and fill in the thumbnail_url field.

    Args:
        result:  Output of merge() — modified in-place and also returned.
        api_key: API key for the thumbnail service (TBD).

    Returns:
        The same result dict with thumbnail_url fields populated where possible.
    """
    # TODO: implement thumbnail fetching
    # Suggested approach:
    #   for det in result["detections"]:
    #       det["thumbnail_url"] = _fetch_thumbnail(det["brand"], det["name"], api_key)
    logger.warning("enrich_thumbnails() is not yet implemented — thumbnail_url remains null")
    return result
