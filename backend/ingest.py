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

    Args:
        video_id: YouTube video ID (NOT the full URL)

    Returns:
        Dictionary containing:
          - video_id, language, transcript (list of snippets), text, word_count, is_generated

    Raises:
        Exception: If English transcript is not available or cannot be fetched
    """
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
    }

    # --- Step 6: Persist transcript to transcripts/<video_id>.json ---
    transcript_path = Path(TRANSCRIPTS_DIR) / f"{video_id}.json"
    transcript_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    logger.info("Transcript saved to '%s'", transcript_path)

    return result


# def get_transcript(video_id: str) -> Dict:
#     """
#     Fetch English transcript for a YouTube video using YouTube Data API.
    
#     Args:
#         video_id: YouTube video ID
        
#     Returns:
#         Dictionary containing transcript data
        
#     Raises:
#         Exception: If English transcript is not available or API key is missing
#     """
#     # Get YouTube Data API key from environment
#     os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
#     api_key = os.environ.get('YOUTUBE_API_KEY')
#     if not api_key:
#         raise Exception("YOUTUBE_API_KEY environment variable is not set. Please set it in your .env file.")
    
#     try:
#         # Build YouTube Data API service
#         youtube = build('youtube', 'v3', developerKey=api_key)
        
#         # List caption tracks for the video
#         captions_list_response = youtube.captions().list(
#             part='snippet',
#             videoId=video_id
#         ).execute()

#         print(captions_list_response)
        
#         if not captions_list_response.get('items'):
#             raise Exception("No captions available for this video.")
        
#         # Find English caption track (prefer manually created over auto-generated)
#         english_caption_id = None
#         is_auto_generated = None
        
#         # First, try to find manually created English caption
#         for caption in captions_list_response['items']:
#             snippet = caption.get('snippet', {})
#             if snippet.get('language') == 'en' and not snippet.get('trackKind') == 'ASR':
#                 english_caption_id = caption['id']
#                 is_auto_generated = False
#                 break
        
#         # If no manually created, try auto-generated
#         if not english_caption_id:
#             for caption in captions_list_response['items']:
#                 snippet = caption.get('snippet', {})
#                 if snippet.get('language') == 'en' and snippet.get('trackKind') == 'ASR':
#                     english_caption_id = caption['id']
#                     is_auto_generated = True
#                     break
        
#         if not english_caption_id:
#             # List available languages for error message
#             available_languages = []
#             for caption in captions_list_response['items']:
#                 snippet = caption.get('snippet', {})
#                 lang = snippet.get('language', 'unknown')
#                 lang_name = snippet.get('name', lang)
#                 is_asr = snippet.get('trackKind') == 'ASR'
#                 available_languages.append(f"{lang_name} ({lang}){' [auto-generated]' if is_asr else ''}")
            
#             if available_languages:
#                 lang_list = ', '.join(available_languages[:5])
#                 raise Exception(f"English transcript is not available for this video. Available languages: {lang_list}")
#             else:
#                 raise Exception("English transcript is not available for this video. No transcripts are available for this video.")
        
#         # Download the caption track (returns bytes)
#         import io
#         caption_response = youtube.captions().download(
#             id=english_caption_id,
#             tfmt='srt'  # SubRip format
#         ).execute()
        
#         # Parse the SRT format and convert to our format
#         transcript_data = []
#         text_lines = []
        
#         # SRT format parsing - response is bytes
#         srt_content = caption_response.decode('utf-8') if isinstance(caption_response, bytes) else str(caption_response)
#         srt_blocks = srt_content.strip().split('\n\n')
        
#         def srt_time_to_seconds(srt_time):
#             """Convert SRT time format (HH:MM:SS,mmm) to seconds"""
#             try:
#                 time_part, ms = srt_time.split(',')
#                 h, m, s = map(int, time_part.split(':'))
#                 return h * 3600 + m * 60 + s + int(ms) / 1000.0
#             except:
#                 return 0.0
        
#         for block in srt_blocks:
#             lines = [line.strip() for line in block.split('\n') if line.strip()]
#             if len(lines) >= 3:
#                 # Parse timecode (format: 00:00:00,000 --> 00:00:05,000)
#                 timecode = lines[1]
#                 if '-->' in timecode:
#                     try:
#                         start_str, end_str = timecode.split(' --> ')
#                         start = srt_time_to_seconds(start_str)
#                         end = srt_time_to_seconds(end_str)
#                         duration = end - start
                        
#                         # Get text (all lines after timecode)
#                         text = ' '.join(lines[2:])
                        
#                         transcript_data.append({
#                             'text': text,
#                             'start': start,
#                             'duration': duration
#                         })
#                         text_lines.append(text)
#                     except Exception as e:
#                         # Skip malformed blocks
#                         continue
        
#         # Combine all text
#         text_transcript = ' '.join(text_lines)
        
#         return {
#             'video_id': video_id,
#             'language': 'en',
#             'transcript': transcript_data,
#             'text': text_transcript,
#             'word_count': len(text_transcript.split()),
#             'is_auto_generated': is_auto_generated
#         }
        
#     except HttpError as e:
#         error_content = e.content.decode('utf-8') if e.content else str(e)
#         if e.resp.status == 403:
#             raise Exception(f"YouTube Data API error: Access forbidden. Check your API key and quota. {error_content}")
#         elif e.resp.status == 404:
#             raise Exception(f"Video or caption not found: {error_content}")
#         else:
#             raise Exception(f"YouTube Data API error: {error_content}")
#     except Exception as e:
#         error_msg = str(e)
#         if "not available" in error_msg.lower():
#             raise Exception(error_msg)
#         else:
#             raise Exception(f"Error fetching English transcript: {error_msg}")


# Format selectors when ffmpeg IS available — separate video+audio streams give
# the best quality because yt-dlp can mux them together.
_FORMAT_SELECTORS_WITH_FFMPEG = {
    'mp4':  'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'webm': 'bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best',
    'mkv':  'bestvideo+bestaudio/best',
}

# Format selectors when ffmpeg is NOT available — restrict to pre-merged
# progressive streams so no muxing step is needed.
_FORMAT_SELECTORS_NO_FFMPEG = {
    'mp4':  'best[ext=mp4]/best',
    'webm': 'best[ext=webm]/best',
    'mkv':  'best',
}


def download_video(youtube_url: str, download_path: str = "videos", format: str = "mp4") -> Dict:
    """
    Download a YouTube video, saving it as <video_id>.<ext> inside download_path.

    Args:
        youtube_url:   Full YouTube URL or bare video ID
        download_path: Directory to save the file (created if it does not exist)
        format:        Preferred container format — 'mp4' (default), 'webm', or 'mkv'

    Returns:
        Dictionary with download result: video_id, title, filename, file_path,
        file_size, file_size_mb, format, download_path, success
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID")

    if not youtube_url.startswith('http'):
        youtube_url = f'https://www.youtube.com/watch?v={video_id}'

    download_dir = Path(download_path)
    download_dir.mkdir(parents=True, exist_ok=True)

    # Use yt-dlp's template system: %(id)s is replaced with the video ID,
    # %(ext)s with the actual container extension after muxing.
    outtmpl = str(download_dir / '%(id)s.%(ext)s')

    ffmpeg_available = shutil.which('ffmpeg') is not None
    if ffmpeg_available:
        format_selector = _FORMAT_SELECTORS_WITH_FFMPEG.get(format, _FORMAT_SELECTORS_WITH_FFMPEG['mp4'])
        logger.debug("ffmpeg found — using high-quality muxed format selector")
    else:
        format_selector = _FORMAT_SELECTORS_NO_FFMPEG.get(format, _FORMAT_SELECTORS_NO_FFMPEG['mp4'])
        logger.warning(
            "ffmpeg not found — falling back to pre-merged formats. "
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


def get_video_with_transcript(youtube_url: str, languages: List[str] = None) -> Dict:
    """
    Fetch video metadata and English transcript in a single call.

    The transcript fetch is best-effort: if it fails, video info is still
    returned with a 'transcript_error' key describing what went wrong.

    Args:
        youtube_url: Full YouTube URL or bare video ID
        languages:   Ignored — only English transcripts are supported for now

    Returns:
        Video info dictionary, with 'transcript' key populated on success
        or 'transcript_error' key on failure
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID")

    logger.info("Fetching video + transcript for video_id='%s'", video_id)

    video_info = get_video_info(youtube_url)

    try:
        video_info['transcript'] = get_transcript(video_id)
        logger.info("Video + transcript fetch complete for video_id='%s'", video_id)
    except Exception as e:
        logger.warning(
            "Transcript fetch failed for video_id='%s': %s", video_id, str(e)
        )
        video_info['transcript'] = None
        video_info['transcript_error'] = str(e)

    return video_info
