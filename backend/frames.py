import json
import logging
import base64
import os
import shutil
from pathlib import Path
from typing import List, Dict

import cv2

logger = logging.getLogger(__name__)

# Anchor to project root so the path is consistent regardless of launch directory
_PROJECT_ROOT = Path(__file__).parent.parent
FRAMES_DIR = str(_PROJECT_ROOT / "data" / "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)


def extract_frames(
    video_path: str,
    video_id: str,
    interval_seconds: float = 2.0,
) -> List[Dict]:
    """
    Extract one frame every `interval_seconds` from a video file.

    Frames are saved as JPEGs under frames/<video_id>/ and also returned
    as base64 strings so they can be passed directly to vision APIs
    (e.g. Gemini Vision) without a second file read.

    Uses direct frame seeking (CAP_PROP_POS_MSEC) instead of reading every
    frame and discarding most of them, which is significantly faster on
    long videos.

    Args:
        video_path:        Path to the video file.
        video_id:          Used to name the output folder and files.
        interval_seconds:  Gap between extracted frames in seconds (default 1.0).

    Returns:
        List of dicts, each containing:
          - timestamp    (float)  — position in the video in seconds
          - frame_path   (str)    — path to the saved JPEG on disk
          - frame_b64    (str)    — base64-encoded JPEG for direct API use
    """
    video_path = str(video_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: '{video_path}'")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        cap.release()
        raise ValueError(f"Could not read FPS from video: '{video_path}'")

    duration_seconds = total_frames / fps
    expected_count = int(duration_seconds / interval_seconds) + 1

    logger.info(
        "Extracting frames from '%s': duration=%.1fs, fps=%.2f, "
        "interval=%.1fs, expected ~%d frames",
        video_id, duration_seconds, fps, interval_seconds, expected_count,
    )

    # Create (or overwrite) a dedicated subfolder for this video's frames.
    # If the directory already exists from a previous run, wipe it first so
    # stale frames from different intervals don't accumulate.
    output_dir = Path(FRAMES_DIR) / video_id
    if output_dir.exists():
        shutil.rmtree(output_dir)
        logger.debug("Removed existing frames directory for '%s' (overwrite)", video_id)
    output_dir.mkdir(parents=True)

    frames: List[Dict] = []
    timestamp = 0.0

    while timestamp <= duration_seconds:
        # Seek directly to the target position — no wasted decoding
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ret, frame = cap.read()

        if not ret:
            logger.debug("Seek to %.3fs returned no frame — stopping", timestamp)
            break

        frame_path = output_dir / f"{timestamp:.3f}.jpg"
        cv2.imwrite(str(frame_path), frame)

        with open(frame_path, 'rb') as f:
            frame_b64 = base64.b64encode(f.read()).decode('utf-8')

        frames.append({
            "timestamp": round(timestamp, 3),
            "frame_path": str(frame_path),
            "frame_b64": frame_b64,
        })

        logger.debug("Saved frame at %.3fs → %s", timestamp, frame_path.name)
        timestamp += interval_seconds

    cap.release()
    logger.info("Done — extracted %d frames for '%s'", len(frames), video_id)

    # --- Save metadata to frames.json (frame_b64 omitted to keep file small) ---
    frames_json_path = output_dir / "frames.json"
    frames_meta = [
        {"timestamp": f["timestamp"], "frame_path": f["frame_path"]}
        for f in frames
    ]
    with open(frames_json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "video_id": video_id,
                "interval_seconds": interval_seconds,
                "frame_count": len(frames_meta),
                "frames": frames_meta,
            },
            fh,
            indent=2,
        )
    logger.info("Frame metadata written to '%s'", frames_json_path)

    return frames


def cleanup_frames(video_id: str) -> int:
    """
    Delete all saved frames for a given video_id.

    Returns the number of files removed.
    """
    output_dir = Path(FRAMES_DIR) / video_id
    if not output_dir.exists():
        logger.debug("No frames directory found for '%s', nothing to clean up", video_id)
        return 0

    removed = 0
    for frame_file in output_dir.glob("*.jpg"):
        frame_file.unlink()
        removed += 1

    try:
        output_dir.rmdir()  # remove the (now-empty) folder too
    except OSError:
        pass  # not empty for some reason — leave it

    logger.info("Cleaned up %d frames for '%s'", removed, video_id)
    return removed
