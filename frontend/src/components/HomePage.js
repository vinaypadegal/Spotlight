import React, { useState } from 'react';

const SpotlightLogo = () => (
  <svg viewBox="0 0 48 48" width="64" height="64" xmlns="http://www.w3.org/2000/svg">
    <circle cx="24" cy="24" r="22" fill="#ff0000" />
    <polygon points="19,14 35,24 19,34" fill="white" />
    <circle cx="24" cy="24" r="6" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="1.5" />
  </svg>
);

const EXAMPLE_URLS = [
  'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  'https://youtu.be/JGwWNGJdvx8',
  'https://www.youtube.com/watch?v=CevxZvSJLk8',
];

// Fake home-feed thumbnails so the page doesn't look empty
const HOME_FEED = [
  { id: 'dQw4w9WgXcQ', title: 'Rick Astley – Never Gonna Give You Up (Official Video)', channel: 'Rick Astley', views: '1.4B', ago: '15 years ago', dur: '3:33' },
  { id: 'JGwWNGJdvx8', title: 'Ed Sheeran – Shape of You (Official)', channel: 'Ed Sheeran', views: '6.1B', ago: '7 years ago', dur: '4:24' },
  { id: 'kXYiU_JCYtU', title: 'Linkin Park – Numb (Official Video)', channel: 'Linkin Park', views: '782M', ago: '16 years ago', dur: '3:07' },
  { id: 'CevxZvSJLk8', title: 'Katy Perry – Roar (Official)', channel: 'Katy Perry', views: '3.8B', ago: '11 years ago', dur: '4:33' },
  { id: '09R8_2nJtjg', title: 'Maroon 5 – Sugar (Official)', channel: 'Maroon 5', views: '3.6B', ago: '9 years ago', dur: '3:55' },
  { id: 'OPf0YbXqDm0', title: 'Mark Ronson ft. Bruno Mars – Uptown Funk', channel: 'Mark Ronson', views: '4.9B', ago: '9 years ago', dur: '4:31' },
  { id: 'hT_nvWreIhg', title: 'OneRepublic – Counting Stars', channel: 'OneRepublic', views: '3.6B', ago: '11 years ago', dur: '4:17' },
  { id: 'RgKAFK5djSk', title: 'Wiz Khalifa – See You Again ft. Charlie Puth', channel: 'Wiz Khalifa', views: '5.9B', ago: '9 years ago', dur: '3:50' },
];

const CHIP_LABELS = ['All', 'Music', 'Gaming', 'Live', 'Mixes', 'Tech', 'Cooking', 'Sports', 'News', 'Fashion'];

export default function HomePage({ onWatch }) {
  const [inputValue, setInputValue] = useState('');
  const [activeChip, setActiveChip] = useState('All');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim()) onWatch(inputValue.trim());
  };

  const handleCardClick = (id) => {
    onWatch(`https://www.youtube.com/watch?v=${id}`);
  };

  return (
    <div className="home-page">
      {/* Hero input strip */}
      <div className="home-hero">
        <SpotlightLogo />
        <h2 className="home-hero__title">Watch any YouTube video with live product detection</h2>
        <p className="home-hero__sub">
          Paste a YouTube URL or video ID — Spotlight detects shoppable products as you watch.
        </p>
        <form className="home-hero__form" onSubmit={handleSubmit}>
          <input
            className="home-hero__input"
            type="text"
            placeholder="Paste YouTube URL or video ID…"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            autoFocus
          />
          <button className="home-hero__btn" type="submit" disabled={!inputValue.trim()}>
            Watch
          </button>
        </form>
        <div className="home-hero__examples">
          {EXAMPLE_URLS.map((url) => (
            <button
              key={url}
              className="home-hero__example-chip"
              onClick={() => onWatch(url)}
            >
              {url.replace('https://www.youtube.com/watch?v=', '').replace('https://youtu.be/', '')}
            </button>
          ))}
        </div>
      </div>

      {/* Filter chips */}
      <div className="home-chips">
        {CHIP_LABELS.map((c) => (
          <button
            key={c}
            className={`home-chip ${activeChip === c ? 'active' : ''}`}
            onClick={() => setActiveChip(c)}
          >
            {c}
          </button>
        ))}
      </div>

      {/* Feed grid */}
      <div className="home-feed">
        {HOME_FEED.map((v) => (
          <div
            className="feed-card"
            key={v.id}
            onClick={() => handleCardClick(v.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && handleCardClick(v.id)}
          >
            <div className="feed-card__thumb-wrap">
              <img
                className="feed-card__thumb"
                src={`https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`}
                alt={v.title}
                loading="lazy"
              />
              <span className="feed-card__dur">{v.dur}</span>
            </div>
            <div className="feed-card__info">
              <div className="feed-card__avatar">{v.channel[0]}</div>
              <div className="feed-card__text">
                <p className="feed-card__title">{v.title}</p>
                <p className="feed-card__channel">{v.channel}</p>
                <p className="feed-card__meta">{v.views} views · {v.ago}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
