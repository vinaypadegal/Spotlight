from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import os
import logging
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
    download_video
)
from frames import extract_frames
from vision import analyze_frames, analyze_youtube_url
from merge import merge as merge_results

app = FastAPI(
    title="Spotlight API",
    description="YouTube video and transcript fetching API",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
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

        video_path = f"data/videos/{video_id}.mp4"

        # Always (re-)download — yt-dlp will overwrite the file if it exists,
        # ensuring the local copy is never stale.
        download_video(video_url, download_path="videos", format="mp4")

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
            video_path = f"data/videos/{video_id}.mp4"

            # Always (re-)download so the local copy is never stale
            download_video(video_url, download_path="videos", format="mp4")

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

    logger.info("=== Pipeline start: video_id='%s', interval=%.1fs ===", video_id, interval)

    # ------------------------------------------------------------------
    # Step 1: Download video
    # ------------------------------------------------------------------
    try:
        logger.info("[1/5] Downloading video...")
        download_result = download_video(video_url, download_path="videos", format="mp4")
        steps["download"] = {
            "status": "done",
            "video_path": download_result.get("file_path"),
        }
        logger.info("[1/5] Download complete → %s", download_result.get("file_path"))
    except Exception as e:
        logger.error("[1/5] Download failed: %s", e)
        steps["download"] = {"status": "failed", "error": str(e)}
        # Cannot continue without the video
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed at download step: {e}",
        )

    video_path = f"data/videos/{video_id}.mp4"

    # ------------------------------------------------------------------
    # Step 2: Transcript
    # ------------------------------------------------------------------
    transcript_data = None
    try:
        logger.info("[2/5] Fetching transcript...")
        transcript_data = get_transcript(video_id)
        steps["transcript"] = {
            "status": "done",
            "language": transcript_data.get("language"),
            "word_count": transcript_data.get("word_count"),
            "is_generated": transcript_data.get("is_generated"),
            "saved_to": f"transcripts/{video_id}.json",
        }
        logger.info(
            "[2/5] Transcript done — %d words (%s)",
            transcript_data.get("word_count", 0),
            "auto-generated" if transcript_data.get("is_generated") else "manual",
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
            "status": "done",
            "frame_count": len(frames),
            "interval_seconds": interval,
            "saved_to": f"frames/{video_id}/",
        }
        logger.info("[3/5] Frame extraction done — %d frames", len(frames))
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
        logger.info(vision_result)
        summary = vision_result.get("summary", {})
        steps["vision"] = {
            "status": "done",
            "frame_count": summary.get("total_frames", 0),
            "frames_with_detections": summary.get("frames_with_detections", 0),
            "unique_product_count": summary.get("unique_product_count", 0),
        }
        logger.info(
            "[4/5] Vision done — %d unique products detected",
            summary.get("unique_product_count", 0),
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
        )
        merge_summary = merge_result.get("summary", {})
        steps["integration"] = {
            "status": "done",
            "total_products": merge_summary.get("total_products", 0),
            "vision_only": merge_summary.get("vision_only", 0),
            "transcript_only": merge_summary.get("transcript_only", 0),
            "both": merge_summary.get("both", 0),
            "brand_resolved_count": merge_summary.get("brand_resolved_count", 0),
        }
        logger.info(
            "[5/5] Merge done — %d products total (%d brands resolved from transcript)",
            merge_summary.get("total_products", 0),
            merge_summary.get("brand_resolved_count", 0),
        )
    except Exception as e:
        logger.error("[5/5] Merge step failed: %s", e)
        steps["integration"] = {"status": "failed", "error": str(e)}
        # Non-fatal — still return vision + transcript raw results

    logger.info("=== Pipeline complete: video_id='%s' ===", video_id)

    # ------------------------------------------------------------------
    # Build response
    # ------------------------------------------------------------------
    return {
        "success": True,
        "data": {
            "video_id": video_id,
            "interval_seconds": interval,
            # Per-step status summary
            "steps": steps,
            # Fully hydrated outputs
            "merged": merge_result,        # primary output — fused product list
            "transcript": transcript_data, # raw transcript (for reference)
            "vision": vision_result,       # raw per-frame detections (for reference)
        },
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
