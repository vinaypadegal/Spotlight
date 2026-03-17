import React, { useEffect, useRef, useCallback } from 'react';

// ---------------------------------------------------------------------------
// YouTube IFrame API — loaded once globally
// ---------------------------------------------------------------------------
let _ytApiReady = false;
const _ytReadyCallbacks = [];

function loadYTApi(callback) {
  if (_ytApiReady && window.YT && window.YT.Player) {
    callback();
    return;
  }

  _ytReadyCallbacks.push(callback);

  // If the script is already in the DOM, wait for the global callback
  if (document.querySelector('script[src*="youtube.com/iframe_api"]')) return;

  const tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(tag);

  const prev = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = () => {
    _ytApiReady = true;
    if (prev) prev();
    _ytReadyCallbacks.forEach((cb) => cb());
    _ytReadyCallbacks.length = 0;
  };
}

// ---------------------------------------------------------------------------
// VideoPlayer component
// ---------------------------------------------------------------------------
export default function VideoPlayer({ videoId, onTimeUpdate }) {
  const containerRef = useRef(null);
  const playerRef = useRef(null);
  const intervalRef = useRef(null);
  const mountedRef = useRef(true);

  // Arrow-key seek: ← / → skip ±5 seconds (matches YouTube behaviour)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Don't intercept while the user is typing in an input / textarea
      const tag = document.activeElement?.tagName?.toUpperCase();
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const player = playerRef.current;
      if (!player?.getCurrentTime) return;

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const t = player.getCurrentTime();
        player.seekTo(Math.max(0, t - 5), /* allowSeekAhead */ true);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        const t = player.getCurrentTime();
        player.seekTo(t + 5, /* allowSeekAhead */ true);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []); // refs are stable — no dep needed

  const startPolling = useCallback(() => {
    clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) return;
      try {
        const time = playerRef.current?.getCurrentTime?.();
        if (typeof time === 'number') onTimeUpdate(time);
      } catch (_) {
        // player may not be fully initialised yet
      }
    }, 500);
  }, [onTimeUpdate]);

  useEffect(() => {
    mountedRef.current = true;

    const playerId = `yt-player-${videoId}`;

    const createPlayer = () => {
      if (!mountedRef.current || !document.getElementById(playerId)) return;

      // Destroy any existing player before creating a new one
      if (playerRef.current) {
        try { playerRef.current.destroy(); } catch (_) {}
        playerRef.current = null;
      }

      playerRef.current = new window.YT.Player(playerId, {
        videoId,
        playerVars: {
          autoplay: 1,
          modestbranding: 1,
          rel: 0,
          enablejsapi: 1,
          origin: window.location.origin,
          fs: 0,          // disable YouTube's native fullscreen button —
                          // we implement our own so the cart overlay is included
        },
        events: {
          onReady: startPolling,
        },
      });
    };

    loadYTApi(createPlayer);

    return () => {
      mountedRef.current = false;
      clearInterval(intervalRef.current);
      try { playerRef.current?.destroy(); } catch (_) {}
      playerRef.current = null;
    };
  }, [videoId, startPolling]);

  return (
    <div className="yt-player-wrapper" ref={containerRef}>
      {/* Gemini will replace this div with an iframe */}
      <div id={`yt-player-${videoId}`} className="yt-player-embed" />
    </div>
  );
}
