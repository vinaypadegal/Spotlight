import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# How many frames to pack into one API call.
# Gemini's context window is large, but 10 images per call is a sweet spot
# between throughput and reliability of per-frame alignment.
BATCH_SIZE = 10

# How many API calls to run in parallel.
MAX_WORKERS = 4


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _build_prompt(num_frames: int) -> str:
    """
    Prompt that asks Gemini to analyse exactly `num_frames` images and return
    a strict JSON array — one element per frame, in order.
    """
    return f"""You are a product-detection assistant. You will be shown {num_frames} video frame(s) in order.

For EACH frame identify every clearly visible PHYSICAL, PURCHASABLE product — things a viewer could actually buy (e.g. a camera, a desk lamp, a pair of shoes, a laptop, a food product, a water bottle, a piece of furniture).

Return a JSON array of exactly {num_frames} objects — one per frame, same order as the images.
Each object must follow this schema:

{{
  "items": [
    {{
      "name": "specific product name or description",
      "brand": "brand name if clearly legible, otherwise null",
      "category": "one of: clothing, electronics, food, beverage, vehicle, accessory, appliance, sporting goods, furniture, other",
      "confidence": <float 0.0 to 1.0>,
    }}
  ]
}}

Rules:
- Only include PHYSICAL products that can be purchased.
- EXCLUDE the following — do not include them under any circumstances:
    • Software, apps, or app icons (e.g. YouTube app, iCloud icon, Mail icon, Launchpad)
    • On-screen UI elements, operating system interfaces, or desktop widgets
    • Videos, thumbnails, or other media content visible on a screen
    • Websites, social media posts, or browser content
    • Digital services or subscriptions
    • People, faces, or text-only graphics
- Set brand to null if the brand is not legible — do NOT omit the physical item.
- If a frame has no identifiable physical products, return {{"items": []}}.
- Do NOT wrap the array in any other key. Output raw JSON only."""


def _analyze_batch(client: genai.Client, batch: List[Dict]) -> List[Dict]:
    """
    Send one batch of frames to Gemini in a single API call.

    Returns a list of per-frame result dicts aligned to the input batch:
      [{"timestamp", "frame_path", "products": [{"name", "brand",
        "category", "confidence"}]}, ...]
    """
    num_frames = len(batch)

    # Build the content: text prompt first, then one image part per frame
    parts: List[types.Part] = [types.Part.from_text(text=_build_prompt(num_frames))]
    for frame in batch:
        image_bytes = base64.b64decode(frame["frame_b64"])
        parts.append(
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    frame_array = json.loads(response.text.strip())

    # Align response to batch — model always returns exactly num_frames objects
    results = []
    for i, frame in enumerate(batch):
        frame_data = frame_array[i] if i < len(frame_array) else {"items": []}
        raw_items = frame_data.get("items", [])

        products = []
        for item in raw_items:
            name = item.get("name", "").strip()
            if not name:
                continue
            # brand may be null — merge.py will attempt to resolve it from the transcript
            products.append({
                "name": name,
                "brand": (item.get("brand") or "").strip() or None,
                "category": item.get("category", "other"),
                "confidence": item.get("confidence"),
            })

        results.append({
            "timestamp": frame["timestamp"],
            "frame_path": frame.get("frame_path", ""),
            "products": products,
        })

    return results


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

def analyze_frames(
    frames: List[Dict],
    api_key: Optional[str] = None,
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
) -> Dict:
    """
    Analyse video frames with Gemini Vision to detect brands, products and
    purchasable items, then generate Google Shopping links for each.

    Efficiency strategy:
      - Batching   — multiple frames are packed into a single API call,
                     reducing round-trips and prompt overhead.
      - Parallelism — batches are dispatched concurrently via a thread pool,
                     so API latency doesn't compound across batches.
      - Dedup      — products are deduplicated by search_query across all
                     frames so the final shopping list has no redundancy.

    Args:
        frames:      Output of frames.extract_frames() — list of dicts with
                     keys: timestamp, frame_path, frame_b64.
        api_key:     Gemini API key. Falls back to GEMINI_API_KEY env var.
        batch_size:  Frames per Gemini API call (default 10).
        max_workers: Max concurrent API calls (default 4).

    Returns:
        {
          "frames": [
            {
              "timestamp":  <float>,        # position in seconds
              "frame_path": <str>,          # path to saved JPEG
              "products":   [               # unique detections for this frame
                {
                  "name":       <str>,
                  "brand":      <str|null>,
                  "category":   <str>,
                  "confidence": <float>,
                }
              ]
            },
            ...
          ],
          "summary": {
            "total_frames":           <int>,
            "frames_with_detections": <int>,
            "unique_product_count":   <int>,  # across all frames globally
          }
        }
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )

    if not frames:
        logger.warning("No frames provided — returning empty result")
        return {
            "frames": [],
            "summary": {
                "total_frames": 0,
                "frames_with_detections": 0,
                "unique_product_count": 0,
            },
        }

    client = genai.Client(api_key=api_key)

    # Split frames into batches
    batches = [frames[i:i + batch_size] for i in range(0, len(frames), batch_size)]
    batch_offsets = list(range(0, len(frames), batch_size))

    logger.info(
        "Starting frame analysis: %d frames → %d batches "
        "(batch_size=%d, workers=%d, model=%s)",
        len(frames), len(batches), batch_size, max_workers, GEMINI_MODEL,
    )

    # Pre-allocate result slots so we can write results in original order
    per_frame_results: List[Optional[Dict]] = [None] * len(frames)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_analyze_batch, client, batch): (idx, offset)
            for idx, (batch, offset) in enumerate(zip(batches, batch_offsets))
        }

        for future in as_completed(future_map):
            batch_idx, offset = future_map[future]
            try:
                batch_results = future.result()
                for j, frame_result in enumerate(batch_results):
                    per_frame_results[offset + j] = frame_result
                logger.debug(
                    "Batch %d/%d done (%d frames)",
                    batch_idx + 1, len(batches), len(batch_results),
                )
            except Exception as e:
                logger.error("Batch %d/%d failed: %s", batch_idx + 1, len(batches), e)
                # Fill slots with empty results so indices stay correct
                for j, frame in enumerate(batches[batch_idx]):
                    if per_frame_results[offset + j] is None:
                        per_frame_results[offset + j] = {
                            "timestamp": frame["timestamp"],
                            "frame_path": frame.get("frame_path", ""),
                            "products": [],
                            "error": str(e),
                        }

    per_frame_raw = [r for r in per_frame_results if r is not None]

    # Build the per-frame output, deduplicating products within each frame
    # by normalised name + brand (guards against the model repeating an item).
    frames_out: List[Dict] = []
    global_seen: set = set()
    global_unique_count = 0

    for frame in per_frame_raw:
        frame_seen: set = set()
        unique_frame_products: List[Dict] = []
        for product in frame.get("products", []):
            key = f"{product['name'].lower().strip()}|{(product.get('brand') or '').lower().strip()}"
            if key not in frame_seen:
                frame_seen.add(key)
                unique_frame_products.append(product)
            if key not in global_seen:
                global_seen.add(key)
                global_unique_count += 1

        frames_out.append({
            "timestamp": frame["timestamp"],
            "frame_path": frame.get("frame_path", ""),
            "products": unique_frame_products,
        })

    frames_with_detections = sum(1 for f in frames_out if f["products"])

    logger.info(
        "Analysis complete — %d frames (%d with detections), %d unique products total",
        len(frames_out), frames_with_detections, global_unique_count,
    )

    return {
        "frames": frames_out,
        "summary": {
            "total_frames": len(frames_out),
            "frames_with_detections": frames_with_detections,
            "unique_product_count": global_unique_count,
        },
    }


# -------------------------------------------------------------------------
# YouTube URL → Gemini direct (no download, no frame extraction)
# -------------------------------------------------------------------------

def _build_video_prompt(interval_seconds: float) -> str:
    """
    Prompt for native video input. Asks Gemini to sample the video at a
    regular interval and return per-sample detections as structured JSON.
    """
    return f"""You are a product-detection assistant analyzing a video.

Sample the video at every {interval_seconds:.1f} second(s) and identify every clearly visible PHYSICAL, PURCHASABLE product at each sample point — things a viewer could actually buy (e.g. a camera, a desk lamp, a pair of shoes, a laptop, a food product, a water bottle, a piece of furniture).

Return a JSON array where each element represents one sample point:

[
  {{
    "timestamp": <seconds as a float>,
    "items": [
      {{
        "name": "specific product name or description",
        "brand": "brand name if clearly legible, otherwise null",
        "category": "one of: clothing, electronics, food, beverage, vehicle, accessory, appliance, sporting goods, furniture, other",
        "timestamp": "the time in seconds when it first appears or is mentioned",
        "confidence": "0.0 to 1.0",
      }}
    ]
  }}
]

Rules:
- Include an entry for every sample point, even if items is [].
- Only include PHYSICAL products that can be purchased.
- EXCLUDE the following — do not include them under any circumstances:
    • Software, apps, or app icons (e.g. YouTube app, iCloud icon, Mail icon, Launchpad)
    • On-screen UI elements, operating system interfaces, or desktop widgets
    • Videos, thumbnails, or other media content visible on a screen
    • Websites, social media posts, or browser content
    • Digital services or subscriptions
    • People, faces, or text-only graphics
- Set brand to null if the brand is not legible — do NOT omit the physical item.
- Output raw JSON only — no markdown, no extra keys."""


def _extract_video_id(url: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def analyze_youtube_url(
    youtube_url: str,
    interval_seconds: float = 1.0,
    api_key: Optional[str] = None,
) -> Dict:
    """
    Detect brands, products and purchasable items in a YouTube video by
    passing the URL directly to Gemini — no download or frame extraction needed.

    Gemini natively understands YouTube URLs and processes the video server-side,
    so this bypasses yt-dlp and OpenCV entirely. The trade-off vs analyze_frames()
    is that timing precision depends on the model rather than exact seek positions.

    Args:
        youtube_url:       Full YouTube URL or bare video ID.
        interval_seconds:  Requested sampling interval in seconds (default 1.0).
                           Gemini uses this as a guide, not a hard guarantee.
        api_key:           Gemini API key. Falls back to GEMINI_API_KEY env var.

    Returns:
        Same structure as analyze_frames():
        {
          "frames":  [{ "timestamp", "frame_path", "products": [...] }, ...],
          "summary": { "total_frames", "frames_with_detections", "unique_product_count" }
        }
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )

    # Normalise to a full watch URL
    video_id = _extract_video_id(youtube_url)
    if not video_id:
        raise ValueError(f"Could not extract a video ID from: '{youtube_url}'")
    watch_url = f"https://www.youtube.com/watch?v={video_id}"

    logger.info(
        "Analyzing YouTube video directly via Gemini: video_id='%s', interval=%.1fs",
        video_id, interval_seconds,
    )

    client = genai.Client(api_key=api_key)

    # Pass the YouTube URL natively — Gemini fetches and processes it server-side
    contents = [
        types.Content(
            parts=[
                types.Part(file_data=types.FileData(file_uri=watch_url)),
                types.Part.from_text(text=_build_video_prompt(interval_seconds)),
            ],
            role="user",
        )
    ]

    logger.debug("Sending request to Gemini (model=%s)...", GEMINI_MODEL)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    logger.debug("Response received from Gemini")

    raw_samples = json.loads(response.text.strip())

    # Normalise into the same shape as analyze_frames() output
    per_frame = []
    for sample in raw_samples:
        timestamp = float(sample.get("timestamp", 0.0))
        raw_items = sample.get("items", [])

        products = []
        for item in raw_items:
            name = item.get("name", "").strip()
            if not name:
                continue
            # brand may be null — merge.py will attempt to resolve it from the transcript
            products.append({
                "name": name,
                "brand": (item.get("brand") or "").strip() or None,
                "category": item.get("category", "other"),
                "confidence": item.get("confidence"),
            })

        per_frame.append({
            "timestamp": round(timestamp, 3),
            "frame_path": None,   # no local file — video was processed by Gemini
            "products": products,
        })

    # Sort by timestamp in case the model returned them out of order
    per_frame.sort(key=lambda x: x["timestamp"])

    # Build the per-frame output, deduplicating products within each frame
    frames_out: List[Dict] = []
    global_seen: set = set()
    global_unique_count = 0

    for frame in per_frame:
        frame_seen: set = set()
        unique_frame_products: List[Dict] = []
        for product in frame.get("products", []):
            key = f"{product['name'].lower().strip()}|{(product.get('brand') or '').lower().strip()}"
            if key not in frame_seen:
                frame_seen.add(key)
                unique_frame_products.append(product)
            if key not in global_seen:
                global_seen.add(key)
                global_unique_count += 1

        frames_out.append({
            "timestamp": frame["timestamp"],
            "frame_path": frame.get("frame_path"),   # None for direct URL analysis
            "products": unique_frame_products,
        })

    frames_with_detections = sum(1 for f in frames_out if f["products"])

    logger.info(
        "Direct analysis complete — %d samples (%d with detections), %d unique products total",
        len(frames_out), frames_with_detections, global_unique_count,
    )

    return {
        "frames": frames_out,
        "summary": {
            "total_frames": len(frames_out),
            "frames_with_detections": frames_with_detections,
            "unique_product_count": global_unique_count,
        },
    }
