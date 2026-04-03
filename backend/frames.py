import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import cv2

logger = logging.getLogger(__name__)

# Anchor to project root so the path is consistent regardless of launch directory
_PROJECT_ROOT = Path(__file__).parent.parent
FRAMES_DIR = str(_PROJECT_ROOT / "data" / "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)


def extract_frames(
    video_id: str,
    interval_seconds: float = 2.0,
    video_path: Optional[str] = None,
) -> Dict:
    """
    Extract one frame every ``interval_seconds`` from a video file.

    Stateless — ``video_path`` defaults to ``data/videos/<video_id>.mp4`` so
    callers only need to supply the ``video_id``.

    Idempotent — if ``data/frames/<video_id>/frames.json`` already exists and
    was produced at the same interval, the cached metadata is returned
    immediately without re-reading the video (``cached=True`` in the result).

    Frames are saved as JPEGs under ``data/frames/<video_id>/`` and a metadata
    file ``frames.json`` is written to the same directory.  ``frame_b64`` is
    NOT included in the return value; callers that need raw pixels (e.g.
    ``vision.analyze_frames``) load images directly from the paths in
    ``frame_path``.

    Args:
        video_id:          Used to name the output folder and derive the
                           default video path.
        interval_seconds:  Gap between extracted frames in seconds (default 2.0).
        video_path:        Override the default video file path.

    Returns:
        {
          "video_id":         str,
          "interval_seconds": float,
          "frame_count":      int,
          "frames":           [{"timestamp": float, "frame_path": str}, ...],
          "cached":           bool,
        }
    """
    # Derive the video path if not supplied
    if video_path is None:
        video_path = str(_PROJECT_ROOT / "data" / "videos" / f"{video_id}.mp4")

    output_dir = Path(FRAMES_DIR) / video_id
    frames_json_path = output_dir / "frames.json"

    # ------------------------------------------------------------------
    # Idempotency check — return cached result if the interval matches
    # ------------------------------------------------------------------
    if frames_json_path.exists():
        try:
            cached_meta = json.loads(frames_json_path.read_text(encoding="utf-8"))
            if abs(cached_meta.get("interval_seconds", -1) - interval_seconds) < 1e-6:
                logger.info(
                    "Frames already extracted at %.1fs intervals, "
                    "loading from cache → %s  (%d frames)",
                    interval_seconds, frames_json_path, cached_meta.get("frame_count", 0),
                )
                return {**cached_meta, "cached": True}
            else:
                logger.info(
                    "Cached frames were at %.1fs intervals but %.1fs requested — re-extracting",
                    cached_meta.get("interval_seconds"), interval_seconds,
                )
        except Exception as cache_err:
            logger.warning("Could not read cached frames.json (%s), re-extracting...", cache_err)

    # ------------------------------------------------------------------
    # Fresh extraction
    # ------------------------------------------------------------------
    video_path_str = str(video_path)
    cap = cv2.VideoCapture(video_path_str)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: '{video_path_str}'")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        cap.release()
        raise ValueError(f"Could not read FPS from video: '{video_path_str}'")

    duration_seconds = total_frames / fps
    expected_count = int(duration_seconds / interval_seconds) + 1

    logger.info(
        "Extracting frames from '%s': duration=%.1fs, fps=%.2f, "
        "interval=%.1fs, expected ~%d frames",
        video_id, duration_seconds, fps, interval_seconds, expected_count,
    )

    # Wipe the output directory so stale frames from a previous interval
    # don't accumulate alongside the new ones.
    if output_dir.exists():
        shutil.rmtree(output_dir)
        logger.debug("Removed existing frames directory for '%s' (overwrite)", video_id)
    output_dir.mkdir(parents=True)

    frames_meta: List[Dict] = []
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

        frames_meta.append({
            "timestamp": round(timestamp, 3),
            "frame_path": str(frame_path),
        })

        logger.debug("Saved frame at %.3fs → %s", timestamp, frame_path.name)
        timestamp += interval_seconds

    cap.release()
    logger.info("Done — extracted %d frames for '%s'", len(frames_meta), video_id)

    # Write metadata to frames.json
    result = {
        "video_id":         video_id,
        "interval_seconds": interval_seconds,
        "frame_count":      len(frames_meta),
        "frames":           frames_meta,
    }
    with open(frames_json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    logger.info("Frame metadata written to '%s'", frames_json_path)

    return {**result, "cached": False}


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
