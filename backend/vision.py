import base64
import json
import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
GEMINI_MODEL          = os.environ.get("GEMINI_MODEL",          "gemini-2.5-flash")
# Fallback model used when the primary is unavailable (503/429).
# A lighter/different model is less likely to be overloaded at the same time.
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash")

# How many frames to pack into one API call.
# Gemini's context window is large, but 10 images per call is a sweet spot
# between throughput and reliability of per-frame alignment.
BATCH_SIZE = 10

# How many API calls to run in parallel.
MAX_WORKERS = 4

# Retry configuration for transient Gemini errors (503, 429).
MAX_RETRIES   = 4      # up to 5 total attempts on the PRIMARY model
RETRY_BASE_S  = 5.0   # initial wait (seconds)
RETRY_BACKOFF = 2.0   # multiplier per attempt  →  5 → 10 → 20 → 40 s
RETRY_JITTER  = 2.0   # max random jitter added to each wait


# -------------------------------------------------------------------------
# Retry helper
# -------------------------------------------------------------------------

def _is_transient(exc: Exception) -> bool:
    """Return True for errors that are worth retrying (overload / rate-limit)."""
    s = str(exc)
    return any(tok in s for tok in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))


def _call_with_retry(
    fn: Callable[[], T],
    fallback_fn: Optional[Callable[[], T]] = None,
    label: str = "Gemini call",
) -> T:
    """
    Call `fn()` with exponential back-off retries for transient errors.

    Retry schedule (primary model):
        attempt 1 → wait  5 s (+jitter)
        attempt 2 → wait 10 s (+jitter)
        attempt 3 → wait 20 s (+jitter)
        attempt 4 → wait 40 s (+jitter)
        attempt 5 → give up on primary

    If `fallback_fn` is provided and the primary model exhausts all retries
    with a transient error, the fallback is tried once (also with its own
    retry cycle at a shorter schedule).

    Non-transient errors (auth failures, bad requests, …) raise immediately.
    """
    last_exc: Optional[Exception] = None
    delay = RETRY_BASE_S

    # ── Primary model ─────────────────────────────────────────────────────────
    for attempt in range(1, MAX_RETRIES + 2):   # attempts 1 … MAX_RETRIES+1
        try:
            return fn()
        except Exception as exc:
            if not _is_transient(exc):
                raise   # don't retry auth errors, invalid requests, etc.

            last_exc = exc
            if attempt > MAX_RETRIES:
                break   # fall through to fallback

            jitter    = random.uniform(0, RETRY_JITTER)
            wait_time = delay + jitter
            logger.warning(
                "%s — transient error on attempt %d/%d (%s). "
                "Retrying in %.1f s...",
                label, attempt, MAX_RETRIES + 1, exc, wait_time,
            )
            time.sleep(wait_time)
            delay *= RETRY_BACKOFF

    # ── Fallback model ─────────────────────────────────────────────────────────
    if fallback_fn is not None:
        logger.warning(
            "%s — primary model failed after %d attempts; "
            "switching to fallback model (%s).",
            label, MAX_RETRIES + 1, GEMINI_FALLBACK_MODEL,
        )
        fb_delay = RETRY_BASE_S
        for fb_attempt in range(1, MAX_RETRIES + 2):
            try:
                return fallback_fn()
            except Exception as exc:
                if not _is_transient(exc):
                    raise

                last_exc = exc
                if fb_attempt > MAX_RETRIES:
                    break

                jitter    = random.uniform(0, RETRY_JITTER)
                wait_time = fb_delay + jitter
                logger.warning(
                    "%s [fallback] — transient error on attempt %d/%d (%s). "
                    "Retrying in %.1f s...",
                    label, fb_attempt, MAX_RETRIES + 1, exc, wait_time,
                )
                time.sleep(wait_time)
                fb_delay *= RETRY_BACKOFF

        logger.error(
            "%s — fallback model also failed after %d attempts.",
            label, MAX_RETRIES + 1,
        )

    assert last_exc is not None
    raise last_exc


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _build_prompt(num_frames: int, known_products: Optional[List[Dict]] = None) -> str:
    """
    Prompt that asks Gemini to analyse exactly `num_frames` images and return
    a strict JSON array — one element per frame, in order.

    `known_products` is an optional list of {name, brand} dicts accumulated from
    previous batches. The model is asked to reuse those exact names/brands when
    it detects the same item, preventing naming drift across batches.
    """
    known_section = ""
    if known_products:
        lines = []
        for p in known_products:
            brand_str = f" (brand: {p['brand']})" if p.get("brand") else " (brand unknown)"
            lines.append(f"  - {p['name']}{brand_str}")
        known_section = (
            "\nPreviously detected products in this video — if you see the same item, "
            "use EXACTLY these names and brands (do not invent variations):\n"
            + "\n".join(lines)
            + "\n"
        )

    return f"""You are a product-detection assistant. You will be shown {num_frames} video frame(s) in order.
{known_section}
For EACH frame identify every clearly visible PHYSICAL, PURCHASABLE product that a viewer could actually buy.

BE SPECIFIC — use the exact product name or model number if it is legible (e.g. "Sony WH-1000XM5" not "headphones", "IKEA POÄNG chair" not "chair", "Apple MacBook Pro 16-inch" not "laptop"). Only include a product if you are reasonably confident it is a specific, real, buyable item — not a vague object category.

Return a JSON array of exactly {num_frames} objects — one per frame, same order as the images.
Each object must follow this schema:

{{
  "items": [
    {{
      "name": "specific product name or model number",
      "brand": "brand name if clearly legible, otherwise null",
      "category": "one of: clothing, electronics, food, beverage, vehicle, accessory, appliance, sporting goods, furniture, other",
      "confidence": <float 0.0 to 1.0>
    }}
  ]
}}

Rules:
- Only include items where BOTH the specific product name/model AND the brand are clearly identifiable. If either is missing or uncertain, skip the item entirely.
- If nothing meets this bar, return {{"items": []}}.
- EXCLUDE under any circumstances:
    • Software, apps, or app icons
    • OS/UI elements, desktop widgets, on-screen interfaces
    • Videos, thumbnails, browser/web content visible on a screen
    • Digital services or subscriptions
    • People, faces, or text-only graphics
- Do NOT wrap the array in any other key. Output raw JSON only."""


def _analyze_batch(
    client: genai.Client,
    batch: List[Dict],
    known_products: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Send one batch of frames to Gemini in a single API call.

    `known_products` is a snapshot of all products detected in previous rounds;
    passing it to the prompt prevents the model from naming the same item
    differently across batches.

    Returns a list of per-frame result dicts aligned to the input batch:
      [{"timestamp", "frame_path", "products": [{"name", "brand",
        "category", "confidence"}]}, ...]
    """
    num_frames = len(batch)

    # Build the content: text prompt first, then one image part per frame
    parts: List[types.Part] = [
        types.Part.from_text(text=_build_prompt(num_frames, known_products))
    ]
    for frame in batch:
        image_bytes = base64.b64decode(frame["frame_b64"])
        parts.append(
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        )

    _contents = [types.Content(parts=parts, role="user")]
    _cfg      = types.GenerateContentConfig(response_mime_type="application/json")

    response = _call_with_retry(
        fn=lambda: client.models.generate_content(
            model=GEMINI_MODEL, contents=_contents, config=_cfg,
        ),
        fallback_fn=lambda: client.models.generate_content(
            model=GEMINI_FALLBACK_MODEL, contents=_contents, config=_cfg,
        ),
        label=f"_analyze_batch ({len(batch)} frames)",
    )

    frame_array = json.loads(response.text.strip())

    # Align response to batch — model always returns exactly num_frames objects
    results = []
    for i, frame in enumerate(batch):
        frame_data = frame_array[i] if i < len(frame_array) else {"items": []}
        raw_items = frame_data.get("items", [])

        products = []
        for item in raw_items:
            name  = (item.get("name")  or "").strip()
            brand = (item.get("brand") or "").strip()
            # Both a specific name and a brand are required — skip vague/unbranded items
            if not name or not brand:
                continue
            products.append({
                "name": name,
                "brand": brand,
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
# Post-processing: Gemini-powered refinement
# -------------------------------------------------------------------------

def _build_refinement_prompt(products: List[Dict]) -> str:
    """
    Prompt that asks Gemini to clean up a flat product list extracted from
    multiple frames:
      1. Remove any entry that is too vague or generic to be shoppable.
      2. Consolidate near-duplicate names/brands into a single canonical entry.

    Input products are indexed by "id" so the response can be mapped back
    to the original detections.
    """
    product_list_json = json.dumps(products, indent=2)
    return f"""You are a product data quality assistant.

Below is a list of products detected across multiple frames of a video. Each entry has an "id", "name", "brand", and "category".

{product_list_json}

Your tasks:

1. REMOVE any product that is too vague or generic to be clearly shoppable on Google Shopping.
   Examples of entries to REMOVE:
     - "laptop" (not a product name — just a category)
     - "headphones" with brand "Unknown"
     - "chair" (no model number, no clear brand)
     - Any product where you cannot imagine a precise Google Shopping search that would find it.
   Keep only products with a specific, searchable model name or product title AND a real, known brand.

2. CONSOLIDATE: if multiple entries clearly refer to the same physical product — even if their
   names are slightly different (e.g., "Sony WH-1000XM5 Wireless Headphones" and "Sony WH1000XM5",
   or "Apple MacBook Pro 16 inch" and "MacBook Pro 16-inch (Apple)") — group them together.
   Choose the single most accurate, specific, and easily shoppable name and brand for the group.

Return a JSON array. Each element represents one canonical product:

{{
  "ids": [<list of integer ids from the input that belong to this product>],
  "name": "<the best, most specific product name — exact model number/title if known>",
  "brand": "<brand name>",
  "category": "<one of: clothing, electronics, food, beverage, vehicle, accessory, appliance, sporting goods, furniture, other>"
}}

Rules:
- Every input id must appear in exactly one output entry, OR be omitted entirely (meaning it was removed as too vague).
- Do NOT invent or fabricate details you are not confident about.
- If only one entry exists and it is specific enough, return an array with that single entry.
- Output raw JSON only — no markdown, no extra prose."""


def _refine_detections(frames_out: List[Dict], client: genai.Client) -> List[Dict]:
    """
    Post-processing pass that calls Gemini once on the full set of unique
    products gathered across all frames.

    Two things happen in this single API call:
      (a) Vague / non-shoppable products are dropped (e.g., "headphones" with
          no model, "a chair" with no brand).
      (b) Near-duplicate names caused by batch naming drift are consolidated
          into a single canonical (name, brand) pair — the most accurate and
          searchable one in the group.

    The canonical names are then written back into every frame, and products
    that were removed are stripped out.

    Falls back gracefully to the original frames if the API call fails.
    """
    # ── 1. Collect all unique (name, brand) pairs and assign stable integer IDs
    raw_key_to_id: Dict[str, int] = {}
    id_to_entry: Dict[int, Dict] = {}
    next_id = 0

    for frame in frames_out:
        for p in frame.get("products", []):
            name  = (p.get("name")  or "").strip()
            brand = (p.get("brand") or "").strip()
            if not name:
                continue
            key = f"{name.lower()}|{brand.lower()}"
            if key not in raw_key_to_id:
                raw_key_to_id[key] = next_id
                id_to_entry[next_id] = {
                    "id":       next_id,
                    "name":     name,
                    "brand":    brand,
                    "category": p.get("category", "other"),
                }
                next_id += 1

    if not id_to_entry:
        logger.debug("Refinement skipped — no products detected.")
        return frames_out

    logger.info(
        "Refining %d unique product(s) — removing vague entries and "
        "consolidating near-duplicates via Gemini...",
        len(id_to_entry),
    )

    # ── 2. Single Gemini call for the full product list ───────────────────────
    product_list = list(id_to_entry.values())
    _ref_contents = [
        types.Content(
            parts=[types.Part.from_text(text=_build_refinement_prompt(product_list))],
            role="user",
        )
    ]
    _ref_cfg = types.GenerateContentConfig(response_mime_type="application/json")

    try:
        response = _call_with_retry(
            fn=lambda: client.models.generate_content(
                model=GEMINI_MODEL, contents=_ref_contents, config=_ref_cfg,
            ),
            fallback_fn=lambda: client.models.generate_content(
                model=GEMINI_FALLBACK_MODEL, contents=_ref_contents, config=_ref_cfg,
            ),
            label="refine_detections",
        )
        canonical_groups = json.loads(response.text.strip())
    except Exception as exc:
        logger.error(
            "Refinement API call failed (%s) — keeping raw detections.", exc
        )
        return frames_out

    # ── 3. Build id → canonical mapping; IDs absent from output were removed ──
    id_to_canonical: Dict[int, Dict] = {}

    for group in canonical_groups:
        canonical_name  = (group.get("name")  or "").strip()
        canonical_brand = (group.get("brand") or "").strip()
        if not canonical_name or not canonical_brand:
            # Model returned an incomplete group — treat as removed
            continue
        canonical_entry = {
            "name":     canonical_name,
            "brand":    canonical_brand,
            "category": group.get("category", "other"),
        }
        for gid in group.get("ids", []):
            try:
                id_to_canonical[int(gid)] = canonical_entry
            except (ValueError, TypeError):
                pass

    kept    = len({v["name"] + "|" + v["brand"] for v in id_to_canonical.values()})
    removed = len(id_to_entry) - len(id_to_canonical)
    logger.info(
        "Refinement complete — %d canonical product(s) kept, %d removed.",
        kept, removed,
    )
    if removed > 0:
        removed_names = [
            id_to_entry[i]["name"]
            for i in id_to_entry
            if i not in id_to_canonical
        ]
        logger.debug("Removed products: %s", removed_names)

    # ── 4. Rewrite every frame's product list with canonical names ─────────────
    new_frames: List[Dict] = []
    for frame in frames_out:
        seen_in_frame: set = set()
        new_products: List[Dict] = []

        for p in frame.get("products", []):
            name  = (p.get("name")  or "").strip()
            brand = (p.get("brand") or "").strip()
            if not name:
                continue
            raw_id   = raw_key_to_id.get(f"{name.lower()}|{brand.lower()}")
            canonical = id_to_canonical.get(raw_id) if raw_id is not None else None
            if canonical is None:
                continue  # product was removed in the refinement step

            c_key = f"{canonical['name'].lower()}|{canonical['brand'].lower()}"
            if c_key not in seen_in_frame:
                seen_in_frame.add(c_key)
                new_products.append({
                    "name":       canonical["name"],
                    "brand":      canonical["brand"],
                    "category":   canonical["category"],
                    "confidence": p.get("confidence"),  # keep original confidence
                })

        new_frames.append({**frame, "products": new_products})

    return new_frames


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
    total_batches = len(batches)

    logger.info(
        "Starting frame analysis: %d frames → %d batches "
        "(batch_size=%d, workers=%d, model=%s)",
        len(frames), total_batches, batch_size, max_workers, GEMINI_MODEL,
    )

    # Pre-allocate result slots so we can write results in original order
    per_frame_results: List[Optional[Dict]] = [None] * len(frames)

    # Accumulated known products — passed as context to each subsequent round
    # so the model reuses consistent names/brands across batches.
    known_products: List[Dict] = []
    known_products_keys: set = set()

    # Process in rounds of max_workers batches each.
    # After every round, collect newly detected products and add them to
    # known_products so the next round can reference them.
    for round_start in range(0, total_batches, max_workers):
        round_batches = batches[round_start : round_start + max_workers]
        round_offsets = batch_offsets[round_start : round_start + max_workers]
        round_end = min(round_start + max_workers, total_batches)

        logger.debug(
            "Round %d–%d / %d batches (known_products context: %d items)",
            round_start + 1, round_end, total_batches, len(known_products),
        )

        # Take a stable snapshot of known_products for all batches in this round
        known_snapshot = list(known_products)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _analyze_batch, client, batch, known_snapshot
                ): (round_start + idx, offset)
                for idx, (batch, offset) in enumerate(zip(round_batches, round_offsets))
            }

            for future in as_completed(future_map):
                batch_idx, offset = future_map[future]
                try:
                    batch_results = future.result()
                    for j, frame_result in enumerate(batch_results):
                        per_frame_results[offset + j] = frame_result
                    logger.debug(
                        "Batch %d/%d done (%d frames)",
                        batch_idx + 1, total_batches, len(batch_results),
                    )
                except Exception as e:
                    logger.error("Batch %d/%d failed: %s", batch_idx + 1, total_batches, e)
                    for j, frame in enumerate(batches[batch_idx]):
                        if per_frame_results[offset + j] is None:
                            per_frame_results[offset + j] = {
                                "timestamp": frame["timestamp"],
                                "frame_path": frame.get("frame_path", ""),
                                "products": [],
                                "error": str(e),
                            }

        # After this round completes, accumulate any new products for next round
        for slot in per_frame_results:
            if slot is None:
                continue
            for product in slot.get("products", []):
                name = (product.get("name") or "").strip()
                brand = (product.get("brand") or "").strip()
                if not name:
                    continue
                key = f"{name.lower()}|{brand.lower()}"
                if key not in known_products_keys:
                    known_products_keys.add(key)
                    known_products.append({"name": name, "brand": brand or None})

    per_frame_raw = [r for r in per_frame_results if r is not None]

    # Deduplicate products within each frame (guards against the model
    # repeating the same item inside a single batch response).
    frames_out: List[Dict] = []
    for frame in per_frame_raw:
        frame_seen: set = set()
        unique_frame_products: List[Dict] = []
        for product in frame.get("products", []):
            key = f"{product['name'].lower().strip()}|{(product.get('brand') or '').lower().strip()}"
            if key not in frame_seen:
                frame_seen.add(key)
                unique_frame_products.append(product)
        frames_out.append({
            "timestamp": frame["timestamp"],
            "frame_path": frame.get("frame_path", ""),
            "products": unique_frame_products,
        })

    # Refinement pass — single Gemini call that:
    #   (a) drops vague / non-shoppable entries, and
    #   (b) consolidates near-duplicate names from different batches into
    #       one canonical (name, brand) pair.
    frames_out = _refine_detections(frames_out, client)

    frames_with_detections = sum(1 for f in frames_out if f["products"])
    global_unique_count = len({
        f"{p['name'].lower()}|{(p.get('brand') or '').lower()}"
        for f in frames_out for p in f["products"]
    })

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

Sample the video at every {interval_seconds:.1f} second(s) and identify every clearly visible PHYSICAL, PURCHASABLE product at each sample point.

BE SPECIFIC — use the exact product name or model number if it is legible (e.g. "Sony WH-1000XM5" not "headphones", "Samsung 65-inch QLED TV" not "TV", "Nike Air Max 90" not "shoes"). Only include a product if you are reasonably confident it is a specific, real, buyable item — not a vague object category. Use consistent names throughout the entire video; if you see the same product at multiple points, use the exact same name and brand each time.

Return a JSON array where each element represents one sample point:

[
  {{
    "timestamp": <seconds as a float>,
    "items": [
      {{
        "name": "specific product name or model number",
        "brand": "brand name if clearly legible, otherwise null",
        "category": "one of: clothing, electronics, food, beverage, vehicle, accessory, appliance, sporting goods, furniture, other",
        "confidence": <float 0.0 to 1.0>
      }}
    ]
  }}
]

Rules:
- Include an entry for every sample point, even if items is [].
- Only include items where BOTH the specific product name/model AND the brand are clearly identifiable. If either is missing or uncertain, skip the item entirely.
- EXCLUDE under any circumstances:
    • Software, apps, or app icons
    • OS/UI elements, desktop widgets, on-screen interfaces
    • Videos, thumbnails, browser/web content visible on a screen
    • Digital services or subscriptions
    • People, faces, or text-only graphics
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

    _yt_cfg = types.GenerateContentConfig(response_mime_type="application/json")

    logger.debug("Sending request to Gemini (model=%s)...", GEMINI_MODEL)
    response = _call_with_retry(
        fn=lambda: client.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=_yt_cfg,
        ),
        fallback_fn=lambda: client.models.generate_content(
            model=GEMINI_FALLBACK_MODEL, contents=contents, config=_yt_cfg,
        ),
        label="analyze_youtube_url",
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
            name  = (item.get("name")  or "").strip()
            brand = (item.get("brand") or "").strip()
            # Both a specific name and a brand are required — skip vague/unbranded items
            if not name or not brand:
                continue
            products.append({
                "name": name,
                "brand": brand,
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

    # Deduplicate products within each frame
    frames_out: List[Dict] = []
    for frame in per_frame:
        frame_seen: set = set()
        unique_frame_products: List[Dict] = []
        for product in frame.get("products", []):
            key = f"{product['name'].lower().strip()}|{(product.get('brand') or '').lower().strip()}"
            if key not in frame_seen:
                frame_seen.add(key)
                unique_frame_products.append(product)
        frames_out.append({
            "timestamp": frame["timestamp"],
            "frame_path": frame.get("frame_path"),   # None for direct URL analysis
            "products": unique_frame_products,
        })

    # Refinement pass — drops vague entries and consolidates near-duplicate names
    frames_out = _refine_detections(frames_out, client)

    frames_with_detections = sum(1 for f in frames_out if f["products"])
    global_unique_count = len({
        f"{p['name'].lower()}|{(p.get('brand') or '').lower()}"
        for f in frames_out for p in f["products"]
    })

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
