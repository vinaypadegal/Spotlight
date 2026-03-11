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
