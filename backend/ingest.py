import time
import logging
import shutil
import yt_dlp
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    RequestBlocked,
    IpBlocked,
    CouldNotRetrieveTranscript,
)
from youtube_transcript_api.formatters import TextFormatter

# NOTE: googleapiclient imports are referenced by the commented-out
# YouTube Data API implementation below; they are not used in active code.
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError

import json
import re
import os
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Anchor data directories to the project root so paths are consistent
# regardless of which working directory the server is launched from.
_PROJECT_ROOT = Path(__file__).parent.parent
VIDEOS_DIR      = str(_PROJECT_ROOT / "data" / "videos")
TRANSCRIPTS_DIR = str(_PROJECT_ROOT / "data" / "transcripts")
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
VIDEO_FORMAT = "mp4"

def extract_video_id(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from various URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - VIDEO_ID (if just the ID is provided)
    """
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _base_ydl_opts(*, quiet: bool = True) -> Dict:
    """
    Shared yt-dlp options used by both get_video_info and download_video.

    Notes on what we intentionally omit:
    - http_headers: yt-dlp sets correct per-client headers automatically; overriding
      them can interfere with client spoofing and cause 403 errors.
    - extractor_args / player_client: defaults for 2026+ are ('android_vr', 'web',
      'web_safari'), which work well without manual configuration.
    - nocheckcertificate / prefer_insecure / age_limit: left at their safe defaults.
    """
    return {
        'quiet': quiet,
        'no_warnings': quiet,
    }


def get_video_info(youtube_url: str) -> Dict:
    """
    Fetch video metadata (title, duration, thumbnail, etc.) without downloading.

    Args:
        youtube_url: Full YouTube URL or bare video ID

    Returns:
        Dictionary with video metadata fields
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID")

    if not youtube_url.startswith('http'):
        youtube_url = f'https://www.youtube.com/watch?v={video_id}'

    logger.info("Fetching video info for video_id='%s'", video_id)

    ydl_opts = _base_ydl_opts(quiet=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            logger.debug(
                "Video info retrieved: title='%s', duration=%ss",
                info.get('title'), info.get('duration'),
            )
            return {
                'video_id': info.get('id', ''),
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', ''),
                'upload_date': info.get('upload_date', ''),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
                'url': info.get('webpage_url', youtube_url),
            }
    except Exception as e:
        raise Exception(f"Error fetching video info: {str(e)}")


def get_transcript(video_id: str) -> Dict:
    """
    Fetch English transcript for a YouTube video using youtube-transcript-api v1.x.

    Idempotent — if a transcript JSON file already exists on disk it is loaded
    and returned immediately without hitting the YouTube API again (result
    includes ``cached=True``).

    Args:
        video_id: YouTube video ID (NOT the full URL)

    Returns:
        Dictionary containing:
          - video_id, language, transcript (list of snippets), text, word_count,
            is_generated, cached

    Raises:
        Exception: If English transcript is not available or cannot be fetched
    """
    # ------------------------------------------------------------------
    # Idempotency check — return cached file if already on disk
    # ------------------------------------------------------------------
    transcript_path = Path(TRANSCRIPTS_DIR) / f"{video_id}.json"
    if transcript_path.exists():
        try:
            result = json.loads(transcript_path.read_text(encoding='utf-8'))
            result['cached'] = True
            segments = result.get("transcript", [])
            logger.info(
                "Transcript already on disk, loaded from cache → %s  (%d words, %d segments)",
                transcript_path, result.get("word_count", 0), len(segments),
            )
            return result
        except Exception as cache_err:
            logger.warning(
                "Could not read cached transcript (%s), re-fetching from YouTube...", cache_err
            )

    logger.info("Starting transcript fetch for video_id='%s'", video_id)

    # --- Step 1: Instantiate the API ---
    ytt = YouTubeTranscriptApi()

    # --- Step 2: List available transcripts (one retry for transient network issues) ---
    logger.debug("Fetching available transcript list...")
    try:
        transcript_list = ytt.list(video_id)
        logger.debug("Transcript list retrieved successfully")
    except (RequestBlocked, IpBlocked) as e:
        raise Exception(
            f"YouTube is blocking requests from this server's IP. "
            f"Consider using a proxy. Details: {str(e)}"
        )
    except VideoUnavailable as e:
        raise Exception(f"Video is unavailable or has been removed. Details: {str(e)}")
    except CouldNotRetrieveTranscript as e:
        # One retry for other transient failures (network blips, etc.)
        logger.warning("First attempt failed (%s), retrying in 1s...", type(e).__name__)
        time.sleep(1)
        transcript_list = ytt.list(video_id)
        logger.debug("Retry successful")

    # --- Step 3: Locate English transcript (manual preferred over auto-generated) ---
    fetched = None
    is_generated = None

    # 3a. Try manually created English transcript first
    logger.debug("Looking for manually created English transcript...")
    try:
        transcript_obj = transcript_list.find_manually_created_transcript(['en'])
        logger.debug("Found manually created English transcript — fetching...")
        fetched = transcript_obj.fetch()
        is_generated = False
        logger.info("Fetched %d snippets (manual transcript)", len(fetched))
    except NoTranscriptFound:
        # 3b. Fall back to auto-generated English transcript
        logger.debug("No manual English transcript — trying auto-generated...")
        try:
            transcript_obj = transcript_list.find_generated_transcript(['en'])
            logger.debug("Found auto-generated English transcript — fetching...")
            fetched = transcript_obj.fetch()
            is_generated = True
            logger.info("Fetched %d snippets (auto-generated transcript)", len(fetched))
        except NoTranscriptFound:
            # Neither manual nor auto-generated English is available
            available = [
                f"{t.language} ({t.language_code}){' [auto]' if t.is_generated else ''}"
                for t in transcript_list
            ]
            if available:
                lang_list = ', '.join(available[:5])
                raise Exception(
                    f"English transcript is not available for this video. "
                    f"Available languages: {lang_list}"
                )
            else:
                raise Exception(
                    "English transcript is not available and no transcripts "
                    "exist for this video."
                )
    except TranscriptsDisabled:
        raise Exception("Transcripts are disabled for this video.")

    # --- Step 4: Convert FetchedTranscript dataclass to serialisable format ---
    # .to_raw_data() returns List[Dict] with keys: 'text', 'start', 'duration'
    logger.debug("Converting transcript data to serialisable format...")
    raw_snippets = fetched.to_raw_data()

    # --- Step 5: Build plain-text transcript using TextFormatter ---
    # TextFormatter.format_transcript() accepts a FetchedTranscript object in v1.x
    logger.debug("Building plain-text transcript...")
    formatter = TextFormatter()
    text_transcript = formatter.format_transcript(fetched)

    word_count = len(text_transcript.split())
    logger.info(
        "Transcript complete — %d words, %d snippets, language=%s, is_generated=%s",
        word_count, len(raw_snippets), fetched.language_code, is_generated,
    )

    result = {
        'video_id': video_id,
        'language': fetched.language_code,
        'transcript': raw_snippets,
        'text': text_transcript,
        'word_count': word_count,
        'is_generated': is_generated,
        'cached': False,
    }

    # --- Step 6: Persist transcript to transcripts/<video_id>.json ---
    # (cached flag is excluded from the saved file — it's runtime metadata only)
    save_data = {k: v for k, v in result.items() if k != 'cached'}
    transcript_path.write_text(json.dumps(save_data, indent=2, ensure_ascii=False), encoding='utf-8')
    logger.info("Transcript saved to '%s'", transcript_path)

    return result


# Format selectors when ffmpeg IS available — separate video+audio streams give
# the best quality because yt-dlp can mux them together.
# ---------------------------------------------------------------------------
# Format selectors
#
# Priority (when ffmpeg IS available):
#   1. Best H.264 (avc1) video up to 1080p + best m4a audio
#      → cleanest result for OpenCV frame extraction; no transcode needed.
#   2. Any video codec up to 1080p + best audio
#      → ffmpeg will remux to mp4 (VP9 / AV1 end up in an mp4 container).
#   3. Best progressive stream up to 1080p, then absolute fallback.
#
# We deliberately cap at 1080p — Gemini Vision doesn't benefit from 4K
# frames, and 4K downloads are 4-8× larger and slower to process.
#
# merge_output_format='mp4' (set in download_video) ensures the output
# file is always an mp4 container that OpenCV can reliably read, even
# when the selected video stream is VP9 or AV1.
# ---------------------------------------------------------------------------
_FORMAT_SELECTORS_WITH_FFMPEG = {
    'mp4': (
        'bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]'   # H.264 1080p — best for OpenCV
        '/bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]'                # H.264 any height
        '/bestvideo[height<=1080]+bestaudio'                          # Any codec up to 1080p
        '/best[height<=1080]'                                         # Progressive 1080p fallback
        '/best'                                                        # Absolute fallback
    ),
    'webm': 'bestvideo[ext=webm][height<=1080]+bestaudio[ext=webm]/best[ext=webm]/best',
    'mkv':  'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
}

# Format selectors when ffmpeg is NOT available — restrict to pre-merged
# progressive streams so no muxing step is needed.
_FORMAT_SELECTORS_NO_FFMPEG = {
    'mp4':  'best[height<=1080][ext=mp4]/best[ext=mp4]/best',
    'webm': 'best[height<=1080][ext=webm]/best[ext=webm]/best',
    'mkv':  'best[height<=1080]/best',
}


def download_video(youtube_url: str, download_path: str = "videos", format: str = "mp4") -> Dict:
    """
    Download a YouTube video, saving it as <video_id>.<ext> inside download_path.

    Idempotent — if the file already exists on disk the download is skipped and
    metadata is fetched without re-downloading (result includes ``cached=True``).

    Args:
        youtube_url:   Full YouTube URL or bare video ID
        download_path: Directory to save the file (created if it does not exist)
        format:        Preferred container format — 'mp4' (default), 'webm', or 'mkv'

    Returns:
        Dictionary with download result: video_id, title, filename, file_path,
        file_size, file_size_mb, format, download_path, success, cached
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID")

    if not youtube_url.startswith('http'):
        youtube_url = f'https://www.youtube.com/watch?v={video_id}'

    download_dir = Path(download_path)
    download_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Idempotency check — skip the download if the file is already on disk.
    # We still call get_video_info() so the caller always receives accurate
    # title / duration metadata regardless of whether we downloaded or not.
    # ------------------------------------------------------------------
    existing_file = download_dir / f"{video_id}.mp4"
    if existing_file.exists():
        logger.info("Video already on disk, skipping download → %s", existing_file)
        try:
            info = get_video_info(youtube_url)
        except Exception as meta_err:
            logger.warning("Could not fetch video metadata (using stubs): %s", meta_err)
            info = {}
        file_size = existing_file.stat().st_size
        return {
            'video_id':     video_id,
            'title':        info.get('title', ''),
            'filename':     existing_file.name,
            'file_path':    str(existing_file),
            'file_size':    file_size,
            'file_size_mb': round(file_size / (1024 * 1024), 2),
            'format':       'mp4',
            'download_path': str(download_dir),
            'success':      True,
            'cached':       True,
        }

    download_dir = Path(download_path)
    download_dir.mkdir(parents=True, exist_ok=True)

    # Use yt-dlp's template system: %(id)s is replaced with the video ID,
    # %(ext)s with the actual container extension after muxing.
    outtmpl = str(download_dir / '%(id)s.%(ext)s')

    ffmpeg_available = shutil.which('ffmpeg') is not None
    if ffmpeg_available:
        format_selector = _FORMAT_SELECTORS_WITH_FFMPEG.get(format, _FORMAT_SELECTORS_WITH_FFMPEG['mp4'])
        logger.debug(
            "ffmpeg found — using high-quality format selector (H.264 ≤1080p preferred, "
            "merge_output_format=mp4): %s", format_selector,
        )
    else:
        format_selector = _FORMAT_SELECTORS_NO_FFMPEG.get(format, _FORMAT_SELECTORS_NO_FFMPEG['mp4'])
        logger.warning(
            "ffmpeg not found — falling back to pre-merged progressive streams (≤1080p). "
            "Install ffmpeg for best quality: brew install ffmpeg"
        )

    def _progress_hook(d: Dict) -> None:
        status = d.get('status')
        if status == 'downloading':
            pct = d.get('_percent_str', '?%').strip()
            speed = d.get('_speed_str', '?').strip()
            eta = d.get('_eta_str', '?').strip()
            logger.debug("Downloading %s — %s at %s, ETA %s", video_id, pct, speed, eta)
        elif status == 'finished':
            logger.debug("Download finished, now post-processing...")

    ydl_opts = {
        **_base_ydl_opts(quiet=False),  # show yt-dlp's own output in the terminal
        'format': format_selector,
        'outtmpl': outtmpl,
        # When ffmpeg is available, always produce an mp4 container so OpenCV
        # can read the file reliably — this remuxes (fast) if the selected
        # streams are already avc1/m4a, or transcodes (slower) otherwise.
        **({"merge_output_format": "mp4"} if ffmpeg_available else {}),
        # Retry fragmented streams and file writes robustly
        'retries': 10,
        'fragment_retries': 10,
        'file_access_retries': 3,
        'progress_hooks': [_progress_hook],
    }

    logger.info(
        "Starting download for video_id='%s', format=%s, dest='%s'",
        video_id, format, download_dir,
    )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Fetch metadata first so we have the title even if download fails
            info = ydl.extract_info(youtube_url, download=False)
            logger.debug("Metadata fetched: title='%s'", info.get('title'))

            ydl.download([youtube_url])

        # Locate the downloaded file — yt-dlp resolves the actual extension
        downloaded_files = list(download_dir.glob(f"{video_id}.*"))
        if not downloaded_files:
            raise Exception("Download completed but file not found in destination directory")

        actual_file = max(downloaded_files, key=lambda f: f.stat().st_size)
        file_size = actual_file.stat().st_size

        logger.info(
            "Download complete: '%s' (%.2f MB)",
            actual_file.name, file_size / (1024 * 1024),
        )

        return {
            'video_id': video_id,
            'title': info.get('title', ''),
            'filename': actual_file.name,
            'file_path': str(actual_file),
            'file_size': file_size,
            'file_size_mb': round(file_size / (1024 * 1024), 2),
            'format': actual_file.suffix.lstrip('.') or format,
            'download_path': str(download_dir),
            'success': True,
            'cached': False,
        }

    except Exception as e:
        error_msg = str(e)

        # Clean up any partial downloads
        for partial in download_dir.glob(f"{video_id}*"):
            try:
                partial.unlink()
                logger.debug("Removed partial file: %s", partial.name)
            except OSError:
                pass

        if '403' in error_msg or 'Forbidden' in error_msg:
            raise Exception(
                f"HTTP 403: YouTube blocked the download. The video may be "
                f"age-restricted or region-locked, or the server IP is rate-limited. "
                f"Original error: {error_msg}"
            )
        elif 'private' in error_msg.lower():
            raise Exception(f"Cannot download a private video. Original error: {error_msg}")
        elif 'unavailable' in error_msg.lower():
            raise Exception(
                f"Video is unavailable — it may have been deleted or made private. "
                f"Original error: {error_msg}"
            )
        else:
            raise Exception(f"Error downloading video: {error_msg}")
