# Spotlight

> **Turn any YouTube video into a shoppable experience — automatically.**

Spotlight watches a video the way a viewer does, identifies every brand and product on screen, cross-references them with what's said in the transcript, and overlays precise, time-synced shopping cards directly inside the player. No manual tagging. No sponsorship deals. Just computer vision, an LLM, and a clean YouTube-clone UI.

![screenshot](screenshots/ss1.png)
![screenshot](screenshots/ss2.png)

---

## How it works

```
YouTube URL
    │
    ├─ 1. Download (yt-dlp, 1080p H.264)
    │
    ├─ 2. Transcript (youtube-transcript-api, English)
    │
    ├─ 3. Frame extraction (OpenCV, configurable interval)
    │
    ├─ 4. Vision analysis (Gemini 2.5 Flash, batched)
    │       ├── Detects concrete, buyable products per frame
    │       ├── Requires both product name AND brand to keep a detection
    │       └── Post-processing refinement pass removes vague/duplicate entries
    │
    ├─ 5. Transcript-vision merge (Gemini-powered NLP)
    │       ├── Extracts brand/product mentions with timestamps from transcript
    │       ├── Resolves missing brands from spoken context
    │       └── Collapses overlapping detections into time-windowed intervals
    │
    └─ detections/<video_id>.json
            └── Served to the frontend for real-time overlay
```

The pipeline is **idempotent**: re-running skips the download and transcript fetch if the files are already on disk, making iteration fast.

---

## Features

| Feature | Detail |
|---|---|
| **Real-time product overlay** | Shopping cards appear and disappear in sync with the video timestamp |
| **Single-run pipeline** | One API call downloads, analyses and merges everything |
| **Gemini Vision (batched)** | Frames are sent in parallel batches; a refinement pass consolidates near-duplicate names across batches |
| **Transcript-aware** | Spoken brand mentions resolve ambiguous or off-screen detections |
| **Retry + fallback model** | Transient Gemini 503/429 errors trigger exponential back-off and automatic fallback to a secondary model |
| **YouTube clone UI** | Dark-mode React UI that mirrors YouTube's layout; the cart button lives inside the player and works in fullscreen |
| **Arrow-key seeking** | Left/Right arrows skip ±5 s, matching YouTube's native behaviour |
| **Caching** | Videos and transcripts are saved to disk; the pipeline skips completed stages on re-run |

---

## Project structure

```
Spotlight/
├── backend/
│   ├── app.py          # FastAPI — all endpoints + pipeline orchestration
│   ├── ingest.py       # yt-dlp download + youtube-transcript-api fetch
│   ├── frames.py       # OpenCV frame extraction
│   ├── vision.py       # Gemini Vision batched analysis + refinement
│   └── merge.py        # Transcript-vision merge + detection flattening
├── frontend/
│   └── src/
│       ├── App.js              # Root state, routing, pipeline trigger
│       └── components/
│           ├── Header.js
│           ├── Sidebar.js
│           ├── VideoPlayer.js  # YouTube IFrame API wrapper
│           ├── WatchPage.js    # Watch layout + fullscreen logic
│           ├── ShoppingPanel.js# Sliding product panel
│           └── HomePage.js
├── data/
│   ├── videos/          # Downloaded MP4 files (gitignored)
│   ├── transcripts/     # Cached transcript JSON files
│   ├── frames/          # Extracted JPEG frames per video
│   └── detections/      # Final merged detection JSON (served to frontend)
├── start.sh             # One-command launcher for both services
├── requirements.txt
└── .env
```

---

## Quick start

### Prerequisites

- Python 3.10+
- Node.js 20+
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`) — required for 1080p muxing
- A [Google AI Studio](https://aistudio.google.com/) API key for Gemini

### 1. Clone and configure

```bash
git clone https://github.com/yourname/spotlight.git
cd spotlight
cp .env.example .env
# Fill in GEMINI_API_KEY in .env
```

### 2. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cd frontend && npm install && cd ..
```

### 3. Start everything

```bash
./start.sh
```

This launches both the FastAPI backend (`http://localhost:8080`) and the React frontend (`http://localhost:3000`), streaming logs to `logs/backend.log` and `logs/frontend.log`.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google AI / Gemini API key |
| `GEMINI_MODEL` | No | Primary model (default: `gemini-2.5-flash`) |
| `GEMINI_FALLBACK_MODEL` | No | Fallback on 503/429 (default: `gemini-2.0-flash`) |
| `DEBUG` | No | Set to `true` for verbose per-stage output logs |

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/youtube/pipeline` | **Run the full pipeline** for a video URL |
| `GET` | `/api/youtube/detections/{video_id}` | Serve cached detections (used by frontend on load) |
| `GET/POST` | `/api/youtube/video` | Fetch video metadata only |
| `GET/POST` | `/api/youtube/transcript` | Fetch English transcript only |
| `GET/POST` | `/api/youtube/frames` | Download + extract frames only |
| `GET/POST` | `/api/youtube/vision` | Run Gemini Vision on a video |
| `GET` | `/api/health` | Health check |

Interactive docs available at `http://localhost:8080/docs` (Swagger UI).

---

## Detection output format

```json
{
  "video_id": "abc123",
  "title": "My Tech Setup 2024",
  "duration": 487.0,
  "status": "complete",
  "detections": [
    {
      "id": "det_a1b2",
      "name": "MacBook Pro 14-inch",
      "brand": "Apple",
      "category": "electronics",
      "show_at": 11.4,
      "hide_at": 21.4,
      "confidence": 0.97,
      "source": "both",
      "shopping_url": "https://www.google.com/search?tbm=shop&q=Apple+MacBook+Pro+14-inch"
    }
  ],
  "summary": {
    "total_products": 8,
    "total_detections": 23,
    "brand_resolved_count": 3
  }
}
```

`source` is `"vision"` (seen on screen), `"transcript"` (mentioned in speech), or `"both"`.

---

## Stack

**Backend** — Python 3.10+, FastAPI, yt-dlp, youtube-transcript-api, OpenCV, Google Gemini (`google-genai`)

**Frontend** — React 18, YouTube IFrame API, Axios

**Infrastructure** — ffmpeg (video muxing), uvicorn (ASGI server)
