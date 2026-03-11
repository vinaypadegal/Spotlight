# Spotlight

A full-stack application with Python (FastAPI) backend and React frontend.

## Project Structure

```
Spotlight/
├── backend/
│   ├── __init__.py
│   ├── app.py          # FastAPI application
│   └── youtube_service.py  # YouTube service module
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── index.js
│   │   └── index.css
│   └── package.json
├── requirements.txt     # Python dependencies
├── .env.example        # Environment variables template
└── README.md
```

## Setup Instructions

### Backend Setup (Python)

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   ```

2. Activate the virtual environment:
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
   
   **Important:** You need a YouTube Data API key for transcript fetching:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the YouTube Data API v3
   - Create credentials (API Key)
   - Add your API key to the `.env` file as `YOUTUBE_API_KEY=your_key_here`

5. Run the FastAPI backend:
   ```bash
   cd backend
   python app.py
   ```
   Or using uvicorn directly:
   ```bash
   uvicorn backend.app:app --reload --host 0.0.0.0 --port 8080
   ```
   The backend will run on `http://localhost:8080`
   
   FastAPI also provides automatic API documentation:
   - Swagger UI: `http://localhost:8080/docs`
   - ReDoc: `http://localhost:8080/redoc`

### Frontend Setup (React)

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install Node dependencies:
   ```bash
   npm install
   ```

3. Start the React development server:
   ```bash
   npm start
   ```
   The frontend will run on `http://localhost:3000`

## Development

- Backend API runs on port 8080
- Frontend runs on port 3000
- The React app is configured to proxy API requests to the backend

## API Endpoints

- `GET /api/health` - Health check endpoint
- `GET /api/hello` - Sample hello endpoint
- `GET/POST /api/youtube/video` - Fetch YouTube video information
- `GET/POST /api/youtube/transcript` - Fetch YouTube video transcript
- `GET/POST /api/youtube/video-with-transcript` - Fetch both video info and transcript

All endpoints support both GET (query parameters) and POST (JSON body) methods.

## Technologies

- **Backend**: FastAPI, Uvicorn, python-dotenv, yt-dlp, youtube-transcript-api
- **Frontend**: React, Axios
- **Python Version**: 3.8+

## API Documentation

FastAPI automatically generates interactive API documentation:
- **Swagger UI**: Visit `http://localhost:8080/docs` when the server is running
- **ReDoc**: Visit `http://localhost:8080/redoc` when the server is running
