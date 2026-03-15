import React from 'react';

const navItems = [
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
      </svg>
    ),
    label: 'Home',
    active: true,
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z" />
      </svg>
    ),
    label: 'Shorts',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M20 3H4v10c0 2.21 1.79 4 4 4h6c2.21 0 4-1.79 4-4v-3h2c1.11 0 2-.89 2-2V5c0-1.11-.89-2-2-2zm0 5h-2V5h2v3zM4 19h16v2H4z" />
      </svg>
    ),
    label: 'Subscriptions',
  },
];

const secondaryItems = [
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z" />
      </svg>
    ),
    label: 'You',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z" />
      </svg>
    ),
    label: 'History',
  },
];

const exploreItems = [
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z" />
      </svg>
    ),
    label: 'Trending',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
      </svg>
    ),
    label: 'Music',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M21 3L3 10.53v.98l6.84 2.65L12.48 21h.98L21 3z" />
      </svg>
    ),
    label: 'Gaming',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8 12.5v-9l6 4.5-6 4.5z" />
      </svg>
    ),
    label: 'News',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
        <path d="M17 12h-5v5h5v-5zM16 1v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-1V1h-2zm3 18H5V8h14v11z" />
      </svg>
    ),
    label: 'Sports',
  },
];

function NavItem({ icon, label, active, isOpen }) {
  return (
    <button className={`yt-nav-item ${active ? 'active' : ''} ${isOpen ? 'expanded' : 'collapsed'}`}>
      <span className="yt-nav-item__icon">{icon}</span>
      {isOpen && <span className="yt-nav-item__label">{label}</span>}
    </button>
  );
}

export default function Sidebar({ isOpen }) {
  return (
    <aside className={`yt-sidebar ${isOpen ? 'expanded' : 'collapsed'}`}>
      <div className="yt-sidebar__section">
        {navItems.map((item) => (
          <NavItem key={item.label} {...item} isOpen={isOpen} />
        ))}
      </div>

      {isOpen && <div className="yt-sidebar__divider" />}

      {isOpen && (
        <div className="yt-sidebar__section">
          <p className="yt-sidebar__section-title">You</p>
          {secondaryItems.map((item) => (
            <NavItem key={item.label} {...item} isOpen={isOpen} />
          ))}
        </div>
      )}

      {isOpen && <div className="yt-sidebar__divider" />}

      {isOpen && (
        <div className="yt-sidebar__section">
          <p className="yt-sidebar__section-title">Explore</p>
          {exploreItems.map((item) => (
            <NavItem key={item.label} {...item} isOpen={isOpen} />
          ))}
        </div>
      )}

      {!isOpen &&
        secondaryItems.concat(exploreItems).map((item) => (
          <NavItem key={item.label} {...item} isOpen={false} />
        ))}
    </aside>
  );
}
