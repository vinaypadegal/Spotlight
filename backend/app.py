from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging — configure before importing ingest so the module-level logger
# picks up the right level immediately.
# Set DEBUG=true in .env (or the environment) to see debug-level messages.
# ---------------------------------------------------------------------------
_log_level = logging.DEBUG if os.environ.get("DEBUG", "false").lower() == "true" else logging.INFO
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from ingest import (
    get_video_info,
    get_transcript,
    get_video_with_transcript,
    extract_video_id,
    download_video,
    VIDEOS_DIR,
    TRANSCRIPTS_DIR,
)
from frames import extract_frames
from vision import analyze_frames, analyze_youtube_url
from merge import merge as merge_results
from enrich import enrich_detections, ENRICH_PRODUCTS

app = FastAPI(
    title="Spotlight API",
    description="YouTube video and transcript fetching API",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
class VideoRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")

class TranscriptRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    languages: Optional[str] = Field(default="en", description="Comma-separated language codes (e.g., 'en,es')")

class VideoWithTranscriptRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    languages: Optional[str] = Field(default="en", description="Comma-separated language codes (e.g., 'en,es')")

class DownloadVideoRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    download_path: Optional[str] = Field(default="downloads", description="Directory path for saving the video")
    format: Optional[str] = Field(default="mp4", description="Video format/extension (e.g., 'mp4', 'webm')")

class FramesRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    interval_seconds: Optional[float] = Field(
        default=1.0,
        description="Gap between extracted frames in seconds (default 1.0).",
        gt=0,
    )

class VisionRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    interval_seconds: Optional[float] = Field(
        default=1.0,
        description="Gap between analyzed frames in seconds (default 1.0). "
                    "Larger values = fewer frames = faster + cheaper.",
        gt=0,
    )
    use_direct: Optional[bool] = Field(
        default=False,
        description="If true, pass the YouTube URL directly to Gemini (no download "
                    "or frame extraction). Faster but requires a public video.",
    )


class PipelineRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    interval_seconds: Optional[float] = Field(
        default=2.0,
        description="Gap between extracted/analyzed frames in seconds (default 2.0).",
        gt=0,
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Backend is running"}


@app.get("/api/hello")
async def hello():
    """Sample API endpoint"""
    return {"message": "Hello from Python backend!"}


@app.get("/api/youtube/video")
@app.post("/api/youtube/video")
async def fetch_video_info(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    request_body: Optional[VideoRequest] = Body(None)
):
    """
    Fetch YouTube video information.
    
    Can be called with GET (query parameter) or POST (JSON body).
    """
    try:
        # Support both GET (query param) and POST (body)
        video_url = url or (request_body.url if request_body else None)
        
        if not video_url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
        
        video_info = get_video_info(video_url)
        return {"success": True, "data": video_info}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/youtube/transcript")
@app.post("/api/youtube/transcript")
async def fetch_transcript(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    languages: Optional[str] = Query(None, description="Ignored - only English transcripts are supported"),
    request_body: Optional[TranscriptRequest] = Body(None)
):
    """
    Fetch English transcript for a YouTube video.
    
    Note: Only English transcripts are currently supported. If English is not available,
    an error will be returned.
    
    Can be called with GET (query parameters) or POST (JSON body).
    """
    try:
        # Support both GET (query params) and POST (body)
        if request_body:
            video_url = request_body.url
        else:
            video_url = url
        
        if not video_url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
        
        video_id = extract_video_id(video_url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or video ID")
        
        # Only fetch English transcript
        transcript_data = get_transcript(video_id)
        return {"success": True, "data": transcript_data}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/youtube/video-with-transcript")
@app.post("/api/youtube/video-with-transcript")
async def fetch_video_with_transcript(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    languages: Optional[str] = Query(None, description="Ignored - only English transcripts are supported"),
    request_body: Optional[VideoWithTranscriptRequest] = Body(None)
):
    """
    Fetch both YouTube video information and English transcript.
    
    Note: Only English transcripts are currently supported.
    
    Can be called with GET (query parameters) or POST (JSON body).
    """
    try:
        # Support both GET (query params) and POST (body)
        if request_body:
            video_url = request_body.url
        else:
            video_url = url
        
        if not video_url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
        
        # Only fetch English transcript
        result = get_video_with_transcript(video_url)
        return {"success": True, "data": result}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/youtube/download")
@app.post("/api/youtube/download")
async def download_video_endpoint(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    download_path: Optional[str] = Query("videos", description="Directory path for saving the video"),
    format: Optional[str] = Query("mp4", description="Video format/extension"),
    request_body: Optional[DownloadVideoRequest] = Body(None)
):
    """
    Download YouTube video to a specific location with filename being the video ID.
    
    Can be called with GET (query parameters) or POST (JSON body).
    """
    try:
        # Support both GET (query params) and POST (body)
        if request_body:
            video_url = request_body.url
            download_path_value = request_body.download_path or "videos"
            format_value = request_body.format or "mp4"
        else:
            video_url = url
            download_path_value = download_path or "videos"
            format_value = format or "mp4"
        
        if not video_url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
        
        result = download_video(video_url, download_path_value, format_value)
        return {"success": True, "data": result}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/youtube/frames")
@app.post("/api/youtube/frames")
async def extract_video_frames(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    interval_seconds: Optional[float] = Query(1.0, description="Seconds between extracted frames", gt=0),
    request_body: Optional[FramesRequest] = Body(None),
):
    """
    Extract frames from a YouTube video at a regular interval.

    The video is downloaded first (if not already on disk), then OpenCV seeks
    to each target timestamp and saves a JPEG under frames/<video_id>/.

    Returns per-frame metadata (timestamp, file path) and a summary.
    Note: frame_b64 is omitted from the response to keep payload size small.

    Can be called with GET (query parameters) or POST (JSON body).
    """
    try:
        if request_body:
            video_url = request_body.url
            interval = request_body.interval_seconds or 1.0
        else:
            video_url = url
            interval = interval_seconds or 1.0

        if not video_url:
            raise HTTPException(status_code=400, detail="url parameter is required")

        video_id = extract_video_id(video_url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or video ID")

        video_path = f"{VIDEOS_DIR}/{video_id}.mp4"

        # Always (re-)download — yt-dlp will overwrite the file if it exists,
        # ensuring the local copy is never stale.
        download_video(video_url, download_path=VIDEOS_DIR, format="mp4")

        frames = extract_frames(
            video_path=video_path,
            video_id=video_id,
            interval_seconds=interval,
        )

        # Strip frame_b64 from the response — it's only needed internally for
        # vision analysis and would make the payload unnecessarily large.
        # The full metadata is also persisted to frames/<video_id>/frames.json.
        frames_meta = [
            {"timestamp": f["timestamp"], "frame_path": f["frame_path"]}
            for f in frames
        ]

        return {
            "success": True,
            "data": {
                "video_id": video_id,
                "interval_seconds": interval,
                "frame_count": len(frames_meta),
                "frames": frames_meta,
            },
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/youtube/vision")
@app.post("/api/youtube/vision")
async def analyze_video_frames(
    url: Optional[str] = Query(None, description="YouTube video URL or video ID"),
    interval_seconds: Optional[float] = Query(1.0, description="Seconds between analyzed frames", gt=0),
    use_direct: Optional[bool] = Query(True, description="Pass URL directly to Gemini (no download)"),
    request_body: Optional[VisionRequest] = Body(None),
):
    """
    Detect brands, products and purchasable items in a YouTube video using
    Gemini Vision, and return Google Shopping links for each detected item.

    Two modes:
    - **use_direct=false** (default): downloads the video, extracts frames with
      OpenCV, then sends frame batches to Gemini. Requires ffmpeg + opencv.
    - **use_direct=true**: passes the YouTube URL straight to Gemini — no
      download or frame extraction needed. Only works for public videos.

    Can be called with GET (query parameters) or POST (JSON body).
    """
    try:
        # Resolve parameters from body or query string
        if request_body:
            video_url = request_body.url
            interval = request_body.interval_seconds or 1.0
            direct = request_body.use_direct or False
        else:
            video_url = url
            interval = interval_seconds or 1.0
            direct = use_direct or False

        if not video_url:
            raise HTTPException(status_code=400, detail="url parameter is required")

        video_id = extract_video_id(video_url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or video ID")

        if direct:
            # --- Fast path: YouTube URL → Gemini directly ---
            result = analyze_youtube_url(
                youtube_url=video_url,
                interval_seconds=interval,
            )
        else:
            # --- Full path: download → extract frames → Gemini ---
            video_path = f"{VIDEOS_DIR}/{video_id}.mp4"

            # Always (re-)download so the local copy is never stale
            download_video(video_url, download_path=VIDEOS_DIR, format="mp4")

            # Extract frames at the requested interval
            frames = extract_frames(
                video_path=video_path,
                video_id=video_id,
                interval_seconds=interval,
            )

            # Analyse with Gemini Vision
            result = analyze_frames(frames)

        return {"success": True, "data": result}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline endpoint — runs the full ingest → frames → vision pipeline in one
# request and returns a single consolidated response.
# ---------------------------------------------------------------------------

@app.post("/api/youtube/pipeline")
async def run_pipeline(request_body: PipelineRequest):
    """
    Run the full Spotlight pipeline for a YouTube video.

    Steps (in order):
      1. **download**     — Download the video with yt-dlp.
      2. **transcript**   — Fetch English transcript and save to
                            transcripts/<video_id>.json.
      3. **frames**       — Extract frames at `interval_seconds` and save to
                            frames/<video_id>/ (+ frames.json metadata file).
      4. **vision**       — Run Gemini Vision on the extracted frames to detect
                            brands, products and purchasable items.
      5. **integration**  — [TODO] Fuse vision detections with the transcript
                            (e.g. anchor products to the sentence where they
                            were mentioned, score prominence, rank by relevance).

    If the transcript is unavailable the pipeline continues — `transcript` will
    be marked as "skipped" and the rest of the steps proceed unaffected.

    All intermediate artefacts are written to disk:
      - data/videos/<video_id>.mp4
      - data/transcripts/<video_id>.json
      - data/frames/<video_id>/<timestamp>.jpg
      - data/frames/<video_id>/frames.json
    """
    steps: dict = {}

    # ------------------------------------------------------------------
    # Resolve video ID
    # ------------------------------------------------------------------
    video_url = request_body.url
    interval = request_body.interval_seconds or 2.0

    video_id = extract_video_id(video_url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or video ID")

    import time as _time
    _pipeline_start = _time.perf_counter()
    logger.info("=== Pipeline start: video_id='%s', interval=%.1fs ===", video_id, interval)

    # ------------------------------------------------------------------
    # Step 1: Download video + fetch metadata (title, duration)
    #   Skip if the video file is already on disk — saves bandwidth and
    #   time on re-runs.  We still call get_video_info() to obtain the
    #   title / duration without triggering a full download.
    # ------------------------------------------------------------------
    video_title: Optional[str] = None
    video_duration: Optional[float] = None
    video_path = str(Path(VIDEOS_DIR) / f"{video_id}.mp4")

    if Path(video_path).exists():
        logger.info(
            "[1/5] Video already on disk, skipping download → %s", video_path
        )
        try:
            info = get_video_info(video_url)
            video_title    = info.get("title")
            video_duration = info.get("duration")
        except Exception as meta_err:
            logger.warning("[1/5] Could not fetch video metadata: %s", meta_err)

        steps["download"] = {
            "status":     "skipped",
            "reason":     "Video file already exists on disk",
            "video_path": video_path,
            "title":      video_title,
            "duration":   video_duration,
        }
        logger.debug(
            "[1/5] Metadata — title=%r  duration=%ss",
            video_title, video_duration,
        )
    else:
        try:
            logger.info("[1/5] Downloading video...")
            download_result = download_video(video_url, download_path=VIDEOS_DIR, format="mp4")
            video_title    = download_result.get("title")
            video_duration = download_result.get("duration")
            steps["download"] = {
                "status":     "done",
                "video_path": download_result.get("file_path"),
                "title":      video_title,
                "duration":   video_duration,
            }
            logger.info(
                "[1/5] Download complete → %s (title=%r, duration=%ss)",
                download_result.get("file_path"), video_title, video_duration,
            )
            logger.debug("[1/5] Full download result:\n%s", json.dumps(download_result, indent=2, default=str))
        except Exception as e:
            logger.error("[1/5] Download failed: %s", e)
            steps["download"] = {"status": "failed", "error": str(e)}
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline failed at download step: {e}",
            )

    # ------------------------------------------------------------------
    # Step 2: Transcript
    #   Skip if the transcript JSON file is already saved to disk — load
    #   directly from file instead of hitting the YouTube API again.
    # ------------------------------------------------------------------
    transcript_data = None
    transcript_file = Path(TRANSCRIPTS_DIR) / f"{video_id}.json"

    if transcript_file.exists():
        try:
            transcript_data = json.loads(transcript_file.read_text(encoding="utf-8"))
            steps["transcript"] = {
                "status":       "skipped",
                "reason":       "Loaded from cached file on disk",
                "language":     transcript_data.get("language"),
                "word_count":   transcript_data.get("word_count"),
                "is_generated": transcript_data.get("is_generated"),
                "loaded_from":  str(transcript_file),
            }
            logger.info(
                "[2/5] Transcript already on disk, loaded → %s  (%d words, %s)",
                transcript_file,
                transcript_data.get("word_count", 0),
                "auto-generated" if transcript_data.get("is_generated") else "manual",
            )
            # Log first few segments so the user can inspect quality
            segments = transcript_data.get("transcript", [])
            if segments:
                preview = segments[:5]
                logger.debug(
                    "[2/5] Transcript preview (first %d/%d segments):\n%s",
                    len(preview), len(segments),
                    json.dumps(preview, indent=2, ensure_ascii=False),
                )
        except Exception as load_err:
            logger.warning(
                "[2/5] Failed to load cached transcript (%s), re-fetching...", load_err
            )
            transcript_data = None  # fall through to re-fetch below

    if transcript_data is None:
        try:
            logger.info("[2/5] Fetching transcript from YouTube...")
            transcript_data = get_transcript(video_id)
            steps["transcript"] = {
                "status":       "done",
                "language":     transcript_data.get("language"),
                "word_count":   transcript_data.get("word_count"),
                "is_generated": transcript_data.get("is_generated"),
                "saved_to":     str(transcript_file),
            }
            logger.info(
                "[2/5] Transcript fetched — %d words (%s)",
                transcript_data.get("word_count", 0),
                "auto-generated" if transcript_data.get("is_generated") else "manual",
            )
            segments = transcript_data.get("transcript", [])
            if segments:
                preview = segments[:5]
                logger.debug(
                    "[2/5] Transcript preview (first %d/%d segments):\n%s",
                    len(preview), len(segments),
                    json.dumps(preview, indent=2, ensure_ascii=False),
                )
        except Exception as e:
            # Transcript is optional — log a warning and continue
            logger.warning("[2/5] Transcript unavailable, skipping: %s", e)
            steps["transcript"] = {"status": "skipped", "reason": str(e)}

    # ------------------------------------------------------------------
    # Step 3: Frame extraction
    # ------------------------------------------------------------------
    frames = []
    try:
        logger.info("[3/5] Extracting frames at %.1fs intervals...", interval)
        frames = extract_frames(
            video_path=video_path,
            video_id=video_id,
            interval_seconds=interval,
        )
        steps["frames"] = {
            "status":           "done",
            "frame_count":      len(frames),
            "interval_seconds": interval,
            "saved_to":         f"frames/{video_id}/",
        }
        logger.info("[3/5] Frame extraction done — %d frames", len(frames))
        if frames:
            preview_ts = [f["timestamp"] for f in frames[:10]]
            logger.debug(
                "[3/5] First %d timestamps: %s%s",
                len(preview_ts), preview_ts,
                " …" if len(frames) > 10 else "",
            )
    except Exception as e:
        logger.error("[3/5] Frame extraction failed: %s", e)
        steps["frames"] = {"status": "failed", "error": str(e)}
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed at frame extraction step: {e}",
        )

    # ------------------------------------------------------------------
    # Step 4: Vision analysis (Gemini)
    # ------------------------------------------------------------------
    vision_result = None
    try:
        logger.info("[4/5] Running Gemini Vision on %d frames...", len(frames))
        vision_result = analyze_frames(frames)
        summary = vision_result.get("summary", {})
        steps["vision"] = {
            "status":                 "done",
            "frame_count":            summary.get("total_frames", 0),
            "frames_with_detections": summary.get("frames_with_detections", 0),
            "unique_product_count":   summary.get("unique_product_count", 0),
        }
        logger.info(
            "[4/5] Vision done — %d unique products across %d/%d frames",
            summary.get("unique_product_count", 0),
            summary.get("frames_with_detections", 0),
            summary.get("total_frames", 0),
        )

        # Log the unique product list so the user can see what was detected
        unique_products = vision_result.get("unique_products", [])
        if unique_products:
            logger.info(
                "[4/5] Unique products detected (%d):\n%s",
                len(unique_products),
                "\n".join(
                    f"  • {p.get('brand', '?')} — {p.get('name', '?')}  "
                    f"(conf={p.get('confidence', '?')}, cat={p.get('category', '?')})"
                    for p in unique_products
                ),
            )
        else:
            logger.info("[4/5] No products detected in this video.")

        # Full per-frame breakdown at DEBUG level
        vision_frames = vision_result.get("frames", [])
        frames_with_hits = [f for f in vision_frames if f.get("products")]
        logger.debug(
            "[4/5] Per-frame detections (%d frames with products):\n%s",
            len(frames_with_hits),
            json.dumps(
                [
                    {
                        "timestamp": f["timestamp"],
                        "products": [
                            {"name": p.get("name"), "brand": p.get("brand"),
                             "confidence": p.get("confidence")}
                            for p in f["products"]
                        ],
                    }
                    for f in frames_with_hits
                ],
                indent=2,
            ),
        )
    except Exception as e:
        logger.error("[4/5] Vision analysis failed: %s", e)
        steps["vision"] = {"status": "failed", "error": str(e)}
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed at vision step: {e}",
        )

    # ------------------------------------------------------------------
    # Step 5: Integration — fuse vision detections with transcript
    # ------------------------------------------------------------------
    merge_result = None
    try:
        logger.info("[5/5] Merging vision detections with transcript...")
        merge_result = merge_results(
            vision_frames=vision_result.get("frames", []),
            transcript_data=transcript_data,   # None if transcript was skipped
            video_id=video_id,
            title=video_title,
            duration=video_duration,
        )
        merge_summary = merge_result.get("summary", {})
        steps["integration"] = {
            "status":               "done",
            "total_products":       merge_summary.get("total_products", 0),
            "total_detections":     merge_summary.get("total_detections", 0),
            "brand_resolved_count": merge_summary.get("brand_resolved_count", 0),
        }
        logger.info(
            "[5/5] Merge done — %d products, %d detections, %d brands resolved from transcript",
            merge_summary.get("total_products", 0),
            merge_summary.get("total_detections", 0),
            merge_summary.get("brand_resolved_count", 0),
        )

        # Log the final detections list so the user can inspect the output
        final_detections = merge_result.get("detections", [])
        if final_detections:
            logger.info(
                "[5/5] Final detections (%d):\n%s",
                len(final_detections),
                "\n".join(
                    f"  [{d.get('show_at', '?'):.1f}s → {d.get('hide_at', '?'):.1f}s] "
                    f"{d.get('brand', '?')} — {d.get('name', '?')}  "
                    f"(conf={d.get('confidence', '?')}, src={d.get('source', '?')})"
                    for d in final_detections
                ),
            )
        else:
            logger.info("[5/5] No detections in merged output.")

        logger.debug(
            "[5/5] Full merged result:\n%s",
            json.dumps(merge_result, indent=2, default=str),
        )
    except Exception as e:
        logger.error("[5/5] Merge step failed: %s", e)
        steps["integration"] = {"status": "failed", "error": str(e)}
        # Non-fatal — still return vision + transcript raw results

    # ------------------------------------------------------------------
    # Step 6: Product enrichment (optional — ENRICH_PRODUCTS=true)
    #   Queries SerpAPI Google Shopping for each unique product to fill in
    #   real shopping_url, thumbnail_url, and price fields.
    #   When disabled this is a fast no-op that just stamps price=None.
    # ------------------------------------------------------------------
    if merge_result:
        try:
            if ENRICH_PRODUCTS:
                logger.info(
                    "[6/6] Enriching %d detections via SerpAPI Google Shopping...",
                    len(merge_result.get("detections", [])),
                )
            else:
                logger.info("[6/6] Product enrichment disabled (ENRICH_PRODUCTS=false) — skipping.")

            merge_result = enrich_detections(merge_result)

            enriched = sum(
                1 for d in merge_result.get("detections", [])
                if d.get("shopping_url") and "google.com/search" not in d["shopping_url"]
            )
            steps["enrichment"] = {
                "status":         "done" if ENRICH_PRODUCTS else "skipped",
                "enriched_count": enriched if ENRICH_PRODUCTS else 0,
                "reason":         None if ENRICH_PRODUCTS else "ENRICH_PRODUCTS=false",
            }

            # Re-save the detections file with enriched data
            if ENRICH_PRODUCTS:
                _det_path = (
                    Path(__file__).parent.parent / "data" / "detections" / f"{video_id}.json"
                )
                try:
                    with open(_det_path, "w", encoding="utf-8") as _fh:
                        json.dump(merge_result, _fh, ensure_ascii=False, indent=2)
                    logger.info("[6/6] Enriched detections saved to %s", _det_path)
                except Exception as _save_err:
                    logger.warning("[6/6] Could not re-save enriched detections: %s", _save_err)

        except Exception as e:
            logger.error("[6/6] Enrichment step failed: %s", e)
            steps["enrichment"] = {"status": "failed", "error": str(e)}
            # Non-fatal — pipeline continues with unenriched detections

    elapsed = round(_time.perf_counter() - _pipeline_start, 2)
    logger.info(
        "=== Pipeline complete: video_id='%s' in %.2fs ===",
        video_id, elapsed,
    )

    # ------------------------------------------------------------------
    # Build response
    # merge_result already contains video_id, title, duration, status,
    # detections[], and summary — surface it directly as the primary output.
    # ------------------------------------------------------------------
    return {
        "success": True,
        "data": {
            # Primary output — ready for the frontend ad overlay
            **(merge_result or {
                "video_id": video_id,
                "title":    video_title,
                "duration": video_duration,
                "status":   "partial",
                "detections": [],
            }),
            # Pipeline step diagnostics
            "steps": steps,
            "elapsed_seconds": elapsed,
        },
    }


@app.get("/api/youtube/detections/{video_id}")
async def get_cached_detections(video_id: str):
    """
    Serve cached detection results from data/detections/<video_id>.json.
    Returns 404 if the pipeline has not been run for this video yet.
    """
    detections_path = Path(__file__).parent.parent / "data" / "detections" / f"{video_id}.json"
    if not detections_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No cached detections found for '{video_id}'. Run the pipeline first.",
        )
    with open(detections_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {"success": True, "data": data}


@app.get("/api/debug/serper")
async def debug_serper(q: str = Query(..., description="Search query to send to Serper.dev Google Shopping")):
    """
    Debug endpoint: sends `q` directly to Serper.dev Google Shopping and returns
    the raw API response alongside the enriched result that enrich.py would pick.

    Useful for inspecting what Serper returns for a given product query so you can
    understand why a particular shopping_url / thumbnail / price was chosen.

    Example:
        GET /api/debug/serper?q=Great+Value+Quick+Oats
    """
    import requests as _requests
    from enrich import (
        SERPER_API_KEY as _KEY,
        _SERPER_ENDPOINT as _ENDPOINT,
        _GL,
        ENRICH_LOCATION,
        _GOOGLE_PREFIXES,
    )

    if not _KEY:
        raise HTTPException(
            status_code=503,
            detail="SERPER_API_KEY is not set. Add it to .env and restart.",
        )

    payload = {"q": q, "gl": _GL, "hl": "en", "num": 5}
    headers = {"X-API-KEY": _KEY, "Content-Type": "application/json"}

    try:
        resp = _requests.post(_ENDPOINT, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
    except _requests.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Serper.dev returned HTTP {exc.response.status_code}: {exc}",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Serper.dev request failed: {exc}")

    shopping: list = raw.get("shopping", [])

    # Replicate the same selection logic used in enrich.py
    def _is_direct(item: dict) -> bool:
        url = item.get("link") or ""
        return not any(url.startswith(p) for p in _GOOGLE_PREFIXES)

    chosen = next((r for r in shopping if _is_direct(r)), shopping[0] if shopping else None)

    return {
        "query":    q,
        "gl":       _GL,
        "location": ENRICH_LOCATION,
        "total_results": len(shopping),
        # What enrich.py would actually pick
        "chosen": {
            "index":        shopping.index(chosen) if chosen else None,
            "title":        chosen.get("title")    if chosen else None,
            "source":       chosen.get("source")   if chosen else None,
            "price":        chosen.get("price")    if chosen else None,
            "shopping_url": chosen.get("link")     if chosen else None,
            "thumbnail_url":chosen.get("imageUrl") if chosen else None,
            "snippet":      (chosen.get("snippet") or chosen.get("description")) if chosen else None,
            "is_direct_link": _is_direct(chosen)   if chosen else None,
        } if chosen else None,
        # Full raw Serper response for inspection
        "raw_shopping_results": [
            {
                "index":      i,
                "title":      r.get("title"),
                "source":     r.get("source"),
                "price":      r.get("price"),
                "link":       r.get("link"),
                "imageUrl":   r.get("imageUrl"),
                "snippet":    r.get("snippet") or r.get("description"),
                "rating":     r.get("rating"),
                "ratingCount":r.get("ratingCount"),
                "is_direct_link": _is_direct(r),
            }
            for i, r in enumerate(shopping)
        ],
    }


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    uvicorn.run(
        # reload requires an import string, not the app object directly
        'app:app' if debug else app,
        host='0.0.0.0',
        port=port,
        reload=debug,
        log_level='debug' if debug else 'info',
    )
