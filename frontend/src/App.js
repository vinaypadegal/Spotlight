import React, { useState, useCallback } from 'react';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import HomePage from './components/HomePage';
import WatchPage from './components/WatchPage';
import './App.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function extractVideoId(url) {
  if (!url) return null;
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /^([a-zA-Z0-9_-]{11})$/,
  ];
  for (const p of patterns) {
    const m = url.match(p);
    if (m) return m[1];
  }
  return null;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const [sidebarOpen, setSidebarOpen]       = useState(true);
  const [view, setView]                     = useState('home');       // 'home' | 'watch'
  const [videoId, setVideoId]               = useState(null);
  const [videoInfo, setVideoInfo]           = useState(null);
  const [currentTime, setCurrentTime]       = useState(0);
  const [detections, setDetections]         = useState([]);
  const [panelOpen, setPanelOpen]           = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState('idle');
  const [searchValue, setSearchValue]       = useState('');

  // Products visible at the current playback time, newest appearance first
  const activeProducts = detections
    .filter((d) => currentTime >= d.show_at && currentTime <= d.hide_at)
    .sort((a, b) => b.show_at - a.show_at);

  // ── Load a video (by URL or ID) ──────────────────────────────────────────
  const loadVideo = useCallback(async (urlOrId) => {
    const vid = extractVideoId(urlOrId);
    if (!vid) return;

    setVideoId(vid);
    setView('watch');
    setCurrentTime(0);
    setDetections([]);
    setPanelOpen(false);
    setVideoInfo(null);
    setPipelineStatus('loading');

    // Kick off video-info fetch in the background (non-blocking)
    fetch('/api/youtube/video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: urlOrId }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data?.data) setVideoInfo(data.data); })
      .catch(() => {});

    // 1️⃣  Try cached detections first — instant load
    try {
      const res = await fetch(`/api/youtube/detections/${vid}`);
      if (res.ok) {
        const data = await res.json();
        setDetections(data.data?.detections || []);
        setPipelineStatus('done');
        return;
      }
    } catch (_) {}

    // 2️⃣  No cache — auto-run the full pipeline
    try {
      const res = await fetch('/api/youtube/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: vid }),
      });
      if (!res.ok) throw new Error('Pipeline request failed');
      const data = await res.json();
      setDetections(data.data?.detections || []);
      // Back-fill videoInfo from pipeline response if video-info fetch lost the race
      if (data.data?.title) {
        setVideoInfo((prev) => prev || { title: data.data.title, duration: data.data.duration });
      }
      setPipelineStatus('done');
    } catch (err) {
      console.error('Pipeline error:', err);
      setPipelineStatus('error');
    }
  }, []);

  // ── Search bar "Watch" action ────────────────────────────────────────────
  const handleSearch = useCallback((value) => {
    if (!value?.trim()) return;
    loadVideo(value.trim());
    setSearchValue('');
  }, [loadVideo]);

  // ── Re-run pipeline (manual "Re-analyse" button) ─────────────────────────
  const runPipeline = useCallback(async () => {
    if (!videoId || pipelineStatus === 'loading') return;
    setPipelineStatus('loading');
    setDetections([]);
    try {
      const res = await fetch('/api/youtube/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: videoId }),
      });
      if (!res.ok) throw new Error('Pipeline request failed');
      const data = await res.json();
      setDetections(data.data?.detections || []);
      if (!videoInfo && data.data?.title) {
        setVideoInfo({ title: data.data.title, duration: data.data.duration });
      }
      setPipelineStatus('done');
    } catch (err) {
      console.error('Pipeline error:', err);
      setPipelineStatus('error');
    }
  }, [videoId, pipelineStatus, videoInfo]);

  // ── Time update from VideoPlayer ─────────────────────────────────────────
  const handleTimeUpdate = useCallback((t) => setCurrentTime(t), []);

  return (
    <div className="yt-app">
      {/* Fixed top header */}
      <Header
        onMenuClick={() => setSidebarOpen((o) => !o)}
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        onSearch={handleSearch}
      />

      {/* Body: sidebar + main */}
      <div className="yt-body">
        <Sidebar isOpen={sidebarOpen} />

        <main
          className={`yt-main ${sidebarOpen ? 'sidebar-open' : 'sidebar-collapsed'} ${panelOpen ? 'panel-open' : ''}`}
        >
          {view === 'home' ? (
            <HomePage onWatch={loadVideo} />
          ) : (
            <WatchPage
              videoId={videoId}
              videoInfo={videoInfo}
              onTimeUpdate={handleTimeUpdate}
              currentTime={currentTime}
              pipelineStatus={pipelineStatus}
              onRunPipeline={runPipeline}
              activeProducts={activeProducts}
              panelOpen={panelOpen}
              onCartToggle={() => setPanelOpen((o) => !o)}
              onPanelClose={() => setPanelOpen(false)}
            />
          )}
        </main>
      </div>
    </div>
  );
}
