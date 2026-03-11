import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [healthStatus, setHealthStatus] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [videoData, setVideoData] = useState(null);
  const [transcriptData, setTranscriptData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    // Check backend health
    axios.get('/api/health')
      .then(response => {
        setHealthStatus(response.data.status);
      })
      .catch(error => {
        console.error('Error connecting to backend:', error);
        setHealthStatus('disconnected');
      });
  }, []);

  const fetchVideoInfo = async () => {
    if (!videoUrl.trim()) {
      setError('Please enter a YouTube URL or video ID');
      return;
    }

    setLoading(true);
    setError('');
    setVideoData(null);
    setTranscriptData(null);

    try {
      const response = await axios.post('/api/youtube/video', { url: videoUrl });
      setVideoData(response.data.data);
    } catch (err) {
      setError(err.response?.data?.error || 'Error fetching video information');
    } finally {
      setLoading(false);
    }
  };

  const fetchTranscript = async () => {
    if (!videoUrl.trim()) {
      setError('Please enter a YouTube URL or video ID');
      return;
    }

    setLoading(true);
    setError('');
    setTranscriptData(null);

    try {
      const response = await axios.post('/api/youtube/transcript', { url: videoUrl });
      setTranscriptData(response.data.data);
    } catch (err) {
      setError(err.response?.data?.error || 'Error fetching transcript');
    } finally {
      setLoading(false);
    }
  };

  const fetchVideoWithTranscript = async () => {
    if (!videoUrl.trim()) {
      setError('Please enter a YouTube URL or video ID');
      return;
    }

    setLoading(true);
    setError('');
    setVideoData(null);
    setTranscriptData(null);

    try {
      const response = await axios.post('/api/youtube/video-with-transcript', { url: videoUrl });
      setVideoData(response.data.data);
      if (response.data.data.transcript) {
        setTranscriptData(response.data.data.transcript);
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Error fetching video and transcript');
    } finally {
      setLoading(false);
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatNumber = (num) => {
    if (!num) return 'N/A';
    return num.toLocaleString();
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Spotlight - YouTube Video & Transcript Fetcher</h1>
        <div className="status">
          <p>Backend Status: <span className={healthStatus}>{healthStatus}</span></p>
        </div>

        <div className="input-section">
          <input
            type="text"
            placeholder="Enter YouTube URL or Video ID"
            value={videoUrl}
            onChange={(e) => setVideoUrl(e.target.value)}
            className="url-input"
            onKeyPress={(e) => e.key === 'Enter' && fetchVideoWithTranscript()}
          />
          <div className="button-group">
            <button 
              onClick={fetchVideoInfo} 
              className="btn-primary"
              disabled={loading}
            >
              Get Video Info
            </button>
            <button 
              onClick={fetchTranscript} 
              className="btn-primary"
              disabled={loading}
            >
              Get Transcript
            </button>
            <button 
              onClick={fetchVideoWithTranscript} 
              className="btn-primary btn-fetch-all"
              disabled={loading}
            >
              Get Both
            </button>
          </div>
        </div>

        {loading && (
          <div className="loading">Loading...</div>
        )}

        {error && (
          <div className="error-message">
            <p>{error}</p>
          </div>
        )}

        {videoData && (
          <div className="video-info">
            <h2>Video Information</h2>
            {videoData.thumbnail && (
              <img src={videoData.thumbnail} alt="Video thumbnail" className="thumbnail" />
            )}
            <div className="info-grid">
              <div><strong>Title:</strong> {videoData.title}</div>
              <div><strong>Channel:</strong> {videoData.uploader}</div>
              <div><strong>Duration:</strong> {formatDuration(videoData.duration)}</div>
              <div><strong>Views:</strong> {formatNumber(videoData.view_count)}</div>
              <div><strong>Likes:</strong> {formatNumber(videoData.like_count)}</div>
              <div><strong>Upload Date:</strong> {videoData.upload_date || 'N/A'}</div>
              <div><strong>Video ID:</strong> {videoData.video_id}</div>
            </div>
            {videoData.description && (
              <div className="description">
                <strong>Description:</strong>
                <p>{videoData.description.substring(0, 300)}{videoData.description.length > 300 ? '...' : ''}</p>
              </div>
            )}
          </div>
        )}

        {transcriptData && (
          <div className="transcript-info">
            <h2>Transcript</h2>
            <div className="transcript-meta">
              <p><strong>Language:</strong> {transcriptData.language}</p>
              <p><strong>Word Count:</strong> {transcriptData.word_count}</p>
              {transcriptData.available_languages && transcriptData.available_languages.length > 0 && (
                <div>
                  <strong>Available Languages:</strong>
                  <ul className="language-list">
                    {transcriptData.available_languages.map((lang, idx) => (
                      <li key={idx}>
                        {lang.language} ({lang.language_code})
                        {lang.is_generated && ' [Auto-generated]'}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="transcript-text">
              <h3>Transcript Text:</h3>
              <p>{transcriptData.text}</p>
            </div>
            {transcriptData.transcript && (
              <div className="transcript-timestamps">
                <h3>Transcript with Timestamps:</h3>
                <div className="transcript-items">
                  {transcriptData.transcript.map((item, idx) => (
                    <div key={idx} className="transcript-item">
                      <span className="timestamp">
                        [{Math.floor(item.start)}s - {Math.floor(item.start + item.duration)}s]
                      </span>
                      <span className="text">{item.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </header>
    </div>
  );
}

export default App;
