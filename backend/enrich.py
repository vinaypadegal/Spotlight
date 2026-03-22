"""
enrich.py
---------
Optional product-enrichment step: for each unique product in a merge() result,
queries Serper.dev's Google Shopping endpoint to fetch a real shopping URL,
product thumbnail, and price near the user's location.

Why Serper.dev?
  - 2,500 free searches/month (vs SerpAPI's 100/month)
  - Simple REST API: POST https://google.serper.dev/shopping
  - No third-party SDK — uses the standard `requests` library
  - Sub-100ms latency per request

Controlled entirely by environment variables:

  ENRICH_PRODUCTS=true       Enable enrichment (default: false)
  SERPER_API_KEY=<your_key>  Serper.dev API key
                             Get a free key at https://serper.dev
  ENRICH_LOCATION=<place>    Location for price/availability localisation
                             (default: "United States")
                             Example: "New York, New York, United States"
  ENRICH_CURRENCY=<code>     Preferred currency (default: "USD")
                             Two-letter country code for `gl` param:
                             "us", "gb", "in", "au", etc.

When ENRICH_PRODUCTS is false (the default) this module is a no-op — calling
enrich_detections() returns the result unchanged with zero network I/O.

Implementation notes
--------------------
* Unique products are deduplicated by (brand, name) so we fire at most one
  Serper request per product regardless of how many detection windows it
  appears in.
* Requests run in parallel via ThreadPoolExecutor (capped at MAX_WORKERS)
  so a 20-product video takes ~4 parallel batches, not 20 serial calls.
* The enriched data is fanned back out to every matching detection.
* On any error (bad key, quota exceeded, network timeout) a warning is logged
  and that product keeps its stub values — the pipeline never fails.
"""

import logging
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import time)
# ---------------------------------------------------------------------------
ENRICH_PRODUCTS = os.environ.get("ENRICH_PRODUCTS", "false").lower() == "true"
SERPER_API_KEY  = os.environ.get("SERPER_API_KEY", "")
ENRICH_LOCATION = os.environ.get("ENRICH_LOCATION", "United States")
# Two-letter country code used as the `gl` (geo-location) parameter
# Maps common currency codes to Serper gl codes; falls back to "us"
_CURRENCY_TO_GL = {
    "USD": "us", "GBP": "gb", "EUR": "de", "AUD": "au",
    "CAD": "ca", "INR": "in", "JPY": "jp", "SGD": "sg",
}
_ENRICH_CURRENCY = os.environ.get("ENRICH_CURRENCY", "USD")
_GL = _CURRENCY_TO_GL.get(_ENRICH_CURRENCY.upper(), "us")

_SERPER_ENDPOINT  = "https://google.serper.dev/search"
_MAX_WORKERS      = 5     # parallel requests — stay well within rate limits
_TIMEOUT_S        = 10    # per-request timeout in seconds

# URLs that start with these prefixes are Google Shopping intermediary links,
# not direct retailer product pages.
_GOOGLE_PREFIXES = (
    "https://www.google.com/",
    "http://www.google.com/",
    "https://google.com/",
    "http://google.com/",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _search_product(name: str, brand: Optional[str]) -> Dict:
    """
    POST a single Google Shopping search to Serper.dev and return the best
    result's shopping_url, thumbnail_url, and price.

    Returns a dict with those three keys; any value may be None if the search
    returns no results or encounters an error.

    Serper.dev request shape:
        POST https://google.serper.dev/shopping
        Headers: X-API-KEY, Content-Type: application/json
        Body: {"q": "...", "gl": "us", "hl": "en", "num": 5}

    Serper.dev response shape:
        {
          "shopping": [
            {
              "title":       "Apple MacBook Pro 14-inch",
              "link":        "https://www.amazon.com/...",
              "source":      "Amazon",
              "price":       "$1,599.00",
              "imageUrl":    "https://m.media-amazon.com/...",
              "snippet":     "M3 chip, 14-inch Liquid Retina, 18GB RAM, 512GB SSD",
              "rating":      4.8,
              "ratingCount": 1234
            },
            ...
          ]
        }

    Returns a dict with keys: shopping_url, thumbnail_url, price, snippet,
    source.  Any value may be None.
    """
    _stub = {
        "shopping_url": None, "thumbnail_url": None,
        "price": None, "snippet": None, "source": None,
    }
    query = f"{brand} {name}".strip() if brand else name.strip()
    if not query:
        return _stub

    headers = {
        "X-API-KEY":    SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "q":   query,
        "gl":  _GL,
        "hl":  "en",
        "num": 5,    # fetch a few so we can pick the most relevant
    }

    try:
        resp = requests.post(
            _SERPER_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()

        shopping: List[Dict] = data.get("shopping", [])

        if not shopping:
            logger.debug("[enrich] No shopping results from Serper for %r", query)
            return _stub

        # Prefer a result whose link goes directly to a retailer page
        # (some Serper results are Google Shopping intermediary URLs).
        def _is_direct(item: Dict) -> bool:
            url = item.get("link") or ""
            return not any(url.startswith(p) for p in _GOOGLE_PREFIXES)

        best: Dict = next((r for r in shopping if _is_direct(r)), shopping[0])

        shopping_url  = best.get("link")
        thumbnail_url = best.get("imageUrl")
        price         = best.get("price")          # e.g. "$29.99" or "From $299"
        # `snippet` is a short product description when available
        snippet       = best.get("snippet") or best.get("description") or None
        source        = best.get("source")         # retailer name e.g. "Amazon"

        logger.debug(
            "[enrich] %r -> source=%r  price=%r  snippet=%r  url=%s",
            query,
            source,
            price,
            (snippet or "")[:80],
            (shopping_url or "")[:100],
        )
        return {
            "shopping_url":  shopping_url,
            "thumbnail_url": thumbnail_url,
            "price":         price,
            "snippet":       snippet,
            "source":        source,
        }

    except requests.exceptions.Timeout:
        logger.warning("[enrich] Serper request timed out for %r", query)
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        logger.warning("[enrich] Serper HTTP %s for %r: %s", status, query, exc)
    except Exception as exc:
        logger.warning("[enrich] Serper request failed for %r: %s", query, exc)

    return _stub


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_detections(result: Dict) -> Dict:
    """
    Enrich the detections in a merge() result with real shopping data from
    Serper.dev Google Shopping.

    Behaviour
    ---------
    * If ENRICH_PRODUCTS=false (default) this is a no-op that stamps
      price=None on every detection and returns immediately.
    * Deduplicates by (brand, name) so each unique product fires exactly one
      Serper request regardless of how many detection windows it has.
    * Parallel execution: up to MAX_WORKERS concurrent HTTP requests.
    * Results are fanned back out to all matching detection windows.
    * Non-fatal: errors are logged as warnings; detections keep their stub
      shopping_url (Google Shopping search URL) so links always work.
    * Adds a `price` field to each detection (None when enrichment is off).

    Args:
        result: Output dict from merge.merge() — modified in-place.

    Returns:
        The same dict with shopping_url, thumbnail_url, and price updated.
    """
    # Stamp enrichment fields as None so the schema is consistent regardless of mode
    for det in result.get("detections", []):
        det.setdefault("price",   None)
        det.setdefault("snippet", None)
        det.setdefault("source",  None)

    if not ENRICH_PRODUCTS:
        logger.debug(
            "[enrich] ENRICH_PRODUCTS=false — skipping. "
            "Set ENRICH_PRODUCTS=true and SERPER_API_KEY in .env to enable."
        )
        return result

    if not SERPER_API_KEY:
        logger.error(
            "[enrich] ENRICH_PRODUCTS=true but SERPER_API_KEY is not set. "
            "Add SERPER_API_KEY=<your_key> to .env (free key at https://serper.dev)."
        )
        return result

    detections: List[Dict] = result.get("detections", [])
    if not detections:
        return result

    # ------------------------------------------------------------------
    # Build a deduplicated map: (brand, name) -> {brand, name}
    # ------------------------------------------------------------------
    unique: Dict[tuple, Dict] = {}
    for det in detections:
        key = (det.get("brand") or "", det.get("name") or "")
        if key not in unique:
            unique[key] = {"brand": det.get("brand"), "name": det.get("name")}

    logger.info(
        "[enrich] Querying Serper.dev Google Shopping for %d unique products "
        "(gl=%r, location=%r)...",
        len(unique), _GL, ENRICH_LOCATION,
    )

    # ------------------------------------------------------------------
    # Parallel Serper requests — one per unique product
    # ------------------------------------------------------------------
    enrichment_map: Dict[tuple, Dict] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_to_key = {
            pool.submit(_search_product, p["name"], p["brand"]): key
            for key, p in unique.items()
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                enrichment_map[key] = future.result()
            except Exception as exc:
                logger.warning("[enrich] Unexpected future error for %r: %s", key, exc)
                enrichment_map[key] = {
                    "shopping_url": None, "thumbnail_url": None,
                    "price": None, "snippet": None, "source": None,
                }

    # ------------------------------------------------------------------
    # Fan enrichment data back out to all matching detections
    # ------------------------------------------------------------------
    enriched_count = 0
    for det in detections:
        key  = (det.get("brand") or "", det.get("name") or "")
        data = enrichment_map.get(key, {})

        # Only overwrite stub shopping_url when Serper returned a real one;
        # keep the Google Shopping search URL as a working fallback otherwise.
        if data.get("shopping_url"):
            det["shopping_url"] = data["shopping_url"]
            enriched_count += 1
        if data.get("thumbnail_url"):
            det["thumbnail_url"] = data["thumbnail_url"]

        # Always apply enrichment fields (may be None)
        det["price"]   = data.get("price")
        det["snippet"] = data.get("snippet")
        det["source"]  = data.get("source")

    logger.info(
        "[enrich] Done — %d/%d detections enriched with real Serper shopping URL.",
        enriched_count, len(detections),
    )
    return result
