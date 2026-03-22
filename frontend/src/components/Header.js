import React from 'react';

// ---------------------------------------------------------------------------
// SVG Icons
// ---------------------------------------------------------------------------
const HamburgerIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#f1f1f1">
    <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" />
  </svg>
);

// Spotlight logo: red badge with a white shopping bag and a red play triangle.
// Uses a spacious 40×28 viewBox so the bag handles have a graceful arc and
// nothing feels cramped.
const SpotlightLogo = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
    {/*
      viewBox 40×32 — gives the handles a full 10-unit arc above the bag,
      and the bag body 17 units of height for a proper equilateral play triangle.
    */}
    <svg viewBox="0 0 40 32" height="30" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      {/* ── Red badge ── */}
      <rect x="0" y="0" width="40" height="32" rx="6" fill="#FF0000" />

      {/* ── White bag body — lower 55% of the badge ── */}
      <rect x="5" y="13" width="30" height="17" rx="2.5" fill="white" />

      {/* ── Bag handles — 10-unit arcs, elegant and airy ── */}
      <path d="M 11 13 C 11 3 17 3 17 13"
            fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M 23 13 C 23 3 29 3 29 13"
            fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" />

      {/* ── Play triangle — proper equilateral proportions (12 wide × 12 tall) ──
           Left edge runs from y=15.5 to y=27.5 (12 units).
           Tip at x=26, midpoint y=21.5 — centred in the bag body.
           12×12 gives the same near-equilateral feel as YouTube's own play icon. */}
      <path d="M 14 15.5 L 14 27.5 L 26 21.5 Z" fill="#FF0000" />
    </svg>

    {/* Wordmark — rendered as HTML so Roboto 900 always loads correctly */}
    <span style={{
      fontFamily: "'Roboto', Arial, sans-serif",
      fontWeight: 900,
      fontSize: '18px',
      color: '#f1f1f1',
      letterSpacing: '-0.5px',
      lineHeight: 1,
    }}>
      Spotlight
    </span>
  </div>
);

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#f1f1f1">
    <path d="M20.87 20.17l-5.59-5.59C16.35 13.35 17 11.75 17 10c0-3.87-3.13-7-7-7s-7 3.13-7 7 3.13 7 7 7c1.75 0 3.35-.65 4.58-1.71l5.59 5.59.7-.71zM10 16c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6z" />
  </svg>
);

const MicIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#f1f1f1">
    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
  </svg>
);

const VideoIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#f1f1f1">
    <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4zM14 13h-3v3H9v-3H6v-2h3V8h2v3h3v2z" />
  </svg>
);

const NotificationIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#f1f1f1">
    <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
  </svg>
);

// ---------------------------------------------------------------------------
// Header component
// ---------------------------------------------------------------------------
export default function Header({ onMenuClick, onSearch, searchValue, onSearchChange }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && onSearch) onSearch(searchValue);
  };

  return (
    <header className="yt-header">
      {/* Left */}
      <div className="yt-header__left">
        <button className="yt-icon-btn" onClick={onMenuClick} title="Menu">
          <HamburgerIcon />
        </button>
        <a href="/" className="yt-logo" onClick={(e) => { e.preventDefault(); window.location.reload(); }}>
          <SpotlightLogo />
        </a>
      </div>

      {/* Centre — search */}
      <div className="yt-header__centre">
        <div className="yt-searchbar">
          <input
            type="text"
            className="yt-searchbar__input"
            placeholder="Search or paste a YouTube URL"
            value={searchValue}
            onChange={(e) => onSearchChange && onSearchChange(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            className="yt-searchbar__btn"
            onClick={() => onSearch && onSearch(searchValue)}
            title="Search"
          >
            <SearchIcon />
          </button>
        </div>
        <button className="yt-icon-btn yt-mic-btn" title="Search with your voice">
          <MicIcon />
        </button>
      </div>

      {/* Right */}
      <div className="yt-header__right">
        <button className="yt-icon-btn" title="Create">
          <VideoIcon />
        </button>
        <button className="yt-icon-btn" title="Notifications">
          <NotificationIcon />
        </button>
        <div className="yt-avatar" title="Account">S</div>
      </div>
    </header>
  );
}
