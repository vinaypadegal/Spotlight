import React, { useState, useRef, useEffect, useCallback } from 'react';
import VideoPlayer from './VideoPlayer';
import ShoppingPanel from './ShoppingPanel';

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------
const ThumbUpIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
    <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" />
  </svg>
);

const ThumbDownIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
    <path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z" />
  </svg>
);

const ShareIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
    <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z" />
  </svg>
);

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
    <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" />
  </svg>
);

const FullscreenIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
    <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z" />
  </svg>
);

const ExitFullscreenIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
    <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z" />
  </svg>
);

const CartIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
    <path d="M7 18c-1.1 0-1.99.9-1.99 2S5.9 22 7 22s2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 7.59-1.35 2.45c-.16.28-.25.61-.25.96C5 16.1 6.9 18 9 18h12v-2H9.42c-.14 0-.25-.11-.25-.25l.03-.12.9-1.63H19c.75 0 1.41-.41 1.75-1.03l3.58-6.49A1 1 0 0 0 23.46 5H5.21l-.94-2H1zm16 16c-1.1 0-1.99.9-1.99 2s.89 2 1.99 2 2-.9 2-2-.9-2-2-2z" />
  </svg>
);

const SpinnerIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" className="spin-icon">
    <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z" />
  </svg>
);

const AnalyseIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
    <path d="M9.5 3A6.5 6.5 0 0 1 16 9.5c0 1.61-.59 3.09-1.56 4.23l.27.27h.79l5 5-1.5 1.5-5-5v-.79l-.27-.27A6.516 6.516 0 0 1 9.5 16 6.5 6.5 0 0 1 3 9.5 6.5 6.5 0 0 1 9.5 3m0 2C7 5 5 7 5 9.5S7 14 9.5 14 14 12 14 9.5 12 5 9.5 5z" />
  </svg>
);

// ---------------------------------------------------------------------------
// Fake recommendations
// ---------------------------------------------------------------------------
const RECS = [
  { id: 'dQw4w9WgXcQ', title: 'Rick Astley – Never Gonna Give You Up', channel: 'Rick Astley', views: '1.4B views', ago: '15 years ago', thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' },
  { id: 'JGwWNGJdvx8', title: 'Ed Sheeran – Shape of You', channel: 'Ed Sheeran', views: '6.1B views', ago: '7 years ago', thumb: 'https://i.ytimg.com/vi/JGwWNGJdvx8/mqdefault.jpg' },
  { id: 'kXYiU_JCYtU', title: 'Linkin Park – Numb', channel: 'Linkin Park', views: '782M views', ago: '16 years ago', thumb: 'https://i.ytimg.com/vi/kXYiU_JCYtU/mqdefault.jpg' },
  { id: 'CevxZvSJLk8', title: 'Katy Perry – Roar', channel: 'Katy Perry', views: '3.8B views', ago: '11 years ago', thumb: 'https://i.ytimg.com/vi/CevxZvSJLk8/mqdefault.jpg' },
  { id: '09R8_2nJtjg', title: 'Maroon 5 – Sugar', channel: 'Maroon 5', views: '3.6B views', ago: '9 years ago', thumb: 'https://i.ytimg.com/vi/09R8_2nJtjg/mqdefault.jpg' },
  { id: 'OPf0YbXqDm0', title: 'Mark Ronson – Uptown Funk ft. Bruno Mars', channel: 'Mark Ronson', views: '4.9B views', ago: '9 years ago', thumb: 'https://i.ytimg.com/vi/OPf0YbXqDm0/mqdefault.jpg' },
];

function formatCount(n) {
  if (!n) return '';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
  return String(n);
}

// ---------------------------------------------------------------------------
// WatchPage
// ---------------------------------------------------------------------------
export default function WatchPage({
  videoId,
  videoInfo,
  onTimeUpdate,
  currentTime,
  pipelineStatus,
  onRunPipeline,
  // Shopping panel
  activeProducts,
  panelOpen,
  onCartToggle,
  onPanelClose,
}) {
  const [descExpanded, setDescExpanded] = useState(false);
  const [isFullscreen, setIsFullscreen]  = useState(false);
  const playerBoxRef = useRef(null);

  const cartCount = activeProducts?.length ?? 0;

  // Track fullscreen state changes (handles both Esc key and our button)
  useEffect(() => {
    const onFsChange = () => {
      const fsEl =
        document.fullscreenElement ||
        document.webkitFullscreenElement ||
        document.mozFullScreenElement;
      setIsFullscreen(!!fsEl);
    };
    document.addEventListener('fullscreenchange',       onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange);
    document.addEventListener('mozfullscreenchange',    onFsChange);
    return () => {
      document.removeEventListener('fullscreenchange',       onFsChange);
      document.removeEventListener('webkitfullscreenchange', onFsChange);
      document.removeEventListener('mozfullscreenchange',    onFsChange);
    };
  }, []);

  const toggleFullscreen = useCallback(() => {
    const el = playerBoxRef.current;
    if (!el) return;
    if (!isFullscreen) {
      (el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen).call(el);
    } else {
      (document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen).call(document);
    }
  }, [isFullscreen]);

  const statusLabel = {
    idle:    'Analyse Video',
    loading: 'Analysing…',
    done:    'Re-analyse',
    error:   'Retry Analysis',
  }[pipelineStatus] || 'Analyse Video';

  return (
    <div className="watch-layout">
      {/* ── Left column ── */}
      <div className="watch-main">
        {/*
          The player box is the fullscreen element.
          ShoppingPanel lives INSIDE here so it is visible when fullscreen is active.
          Because ShoppingPanel uses position:fixed it renders correctly in both
          normal mode (fixed to viewport) and fullscreen mode (fixed inside the
          fullscreen layer, which IS the viewport when fullscreen).
        */}
        <div
          className={`watch-player-box ${isFullscreen ? 'is-fullscreen' : ''}`}
          ref={playerBoxRef}
        >
          <VideoPlayer videoId={videoId} onTimeUpdate={onTimeUpdate} />

          {/* ── Player overlay ── always mounted so it works inside fullscreen ── */}
          <div className="player-overlay">
            <div className="player-overlay__controls">
              {/* Single cart button — works in normal + fullscreen */}
              <button
                className={`player-cart-btn ${panelOpen ? 'active' : ''} ${cartCount > 0 ? 'has-products' : ''}`}
                onClick={onCartToggle}
                title="View detected products"
              >
                <CartIcon />
                {cartCount > 0 && (
                  <span className="player-cart-btn__badge">{cartCount}</span>
                )}
              </button>

              {/* Fullscreen toggle */}
              <button
                className="player-fs-btn"
                onClick={toggleFullscreen}
                title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
              >
                {isFullscreen ? <ExitFullscreenIcon /> : <FullscreenIcon />}
              </button>
            </div>
          </div>

          {/*
            ShoppingPanel is rendered here, inside the player box.
            - Normal mode: position:fixed → anchors to viewport right edge ✓
            - Fullscreen mode: position:fixed inside fullscreen layer → anchors
              to fullscreen viewport right edge ✓
          */}
          <ShoppingPanel
            isOpen={panelOpen}
            onClose={onPanelClose}
            activeProducts={activeProducts}
            currentTime={currentTime}
            pipelineStatus={pipelineStatus}
            isFullscreen={isFullscreen}
          />
        </div>

        {/* Title + actions */}
        <div className="watch-info">
          <h1 className="watch-title">
            {videoInfo?.title || 'Loading…'}
          </h1>

          <div className="watch-meta-row">
            <div className="watch-channel">
              <div className="watch-channel__avatar">
                {(videoInfo?.uploader || 'C')[0].toUpperCase()}
              </div>
              <div className="watch-channel__info">
                <span className="watch-channel__name">
                  {videoInfo?.uploader || 'Loading…'}
                </span>
                <span className="watch-channel__subs">Subscribe</span>
              </div>
              <button className="watch-subscribe-btn">Subscribe</button>
            </div>

            <div className="watch-actions">
              <button className="watch-action-btn">
                <ThumbUpIcon />
                <span>{formatCount(videoInfo?.like_count) || 'Like'}</span>
              </button>
              <button className="watch-action-btn">
                <ThumbDownIcon />
              </button>
              <button className="watch-action-btn">
                <ShareIcon />
                <span>Share</span>
              </button>

              {/* Re-analyse button (auto-runs on first load; this is for manual re-runs) */}
              <button
                className={`watch-action-btn analyse-btn ${pipelineStatus === 'loading' ? 'loading' : ''} ${pipelineStatus === 'done' ? 'done' : ''}`}
                onClick={onRunPipeline}
                disabled={pipelineStatus === 'loading'}
                title="Re-run Spotlight product detection pipeline"
              >
                {pipelineStatus === 'loading' ? <SpinnerIcon /> : <AnalyseIcon />}
                <span>{statusLabel}</span>
              </button>

              <button className="watch-action-btn">
                <MoreIcon />
              </button>
            </div>
          </div>

          {/* Description box */}
          <div
            className={`watch-description ${descExpanded ? 'expanded' : ''}`}
            onClick={() => setDescExpanded(!descExpanded)}
          >
            <div className="watch-description__meta">
              <span>{formatCount(videoInfo?.view_count)} views</span>
              <span>{videoInfo?.upload_date || ''}</span>
            </div>
            <p className="watch-description__text">
              {videoInfo?.description
                ? descExpanded
                  ? videoInfo.description
                  : videoInfo.description.substring(0, 150) + (videoInfo.description.length > 150 ? '…' : '')
                : 'No description available.'}
            </p>
            {!descExpanded && videoInfo?.description?.length > 150 && (
              <span className="watch-description__more">Show more</span>
            )}
          </div>
        </div>
      </div>

      {/* ── Right column — recommendations ── */}
      <div className="watch-recommendations">
        <h3 className="rec-header">Up next</h3>
        {RECS.map((v) => (
          <div className="rec-item" key={v.id}>
            <img
              className="rec-item__thumb"
              src={v.thumb}
              alt={v.title}
              loading="lazy"
            />
            <div className="rec-item__info">
              <p className="rec-item__title">{v.title}</p>
              <p className="rec-item__channel">{v.channel}</p>
              <p className="rec-item__meta">{v.views} · {v.ago}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
