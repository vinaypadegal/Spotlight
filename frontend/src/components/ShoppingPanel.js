import React, { useState } from 'react';

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------
const CloseIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
  </svg>
);

const ShoppingBagIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
    <path d="M18 6h-2c0-2.21-1.79-4-4-4S8 3.79 8 6H6c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6-2c1.1 0 2 .9 2 2h-4c0-1.1.9-2 2-2zm0 10c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z" />
  </svg>
);

const ExternalLinkIcon = () => (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
    <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" />
  </svg>
);

const ImagePlaceholderIcon = () => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor" style={{ opacity: 0.3 }}>
    <path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z" />
  </svg>
);

// ---------------------------------------------------------------------------
// Category colour map (subtle badges)
// ---------------------------------------------------------------------------
const CATEGORY_COLOURS = {
  electronics:      { bg: '#1a237e22', border: '#3ea6ff', text: '#3ea6ff' },
  clothing:         { bg: '#4a148c22', border: '#ce93d8', text: '#ce93d8' },
  food:             { bg: '#1b5e2022', border: '#81c784', text: '#81c784' },
  beverage:         { bg: '#0d47a122', border: '#64b5f6', text: '#64b5f6' },
  vehicle:          { bg: '#bf360c22', border: '#ff8a65', text: '#ff8a65' },
  accessory:        { bg: '#e6510022', border: '#ffb74d', text: '#ffb74d' },
  appliance:        { bg: '#00606422', border: '#4dd0e1', text: '#4dd0e1' },
  'sporting goods': { bg: '#33691e22', border: '#aed581', text: '#aed581' },
  furniture:        { bg: '#4e342e22', border: '#a1887f', text: '#a1887f' },
  other:            { bg: '#37474f22', border: '#90a4ae', text: '#90a4ae' },
};

function categoryStyle(cat = 'other') {
  return CATEGORY_COLOURS[cat.toLowerCase()] || CATEGORY_COLOURS.other;
}

// ---------------------------------------------------------------------------
// ProductCard — rich card with thumbnail, price, snippet, delivery
// ---------------------------------------------------------------------------
function ProductCard({ product }) {
  const cat = categoryStyle(product.category);
  const [thumbError, setThumbError] = useState(false);

  const confidence = product.confidence != null
    ? `${Math.round(product.confidence * 100)}%`
    : null;

  const hasThumbnail = product.thumbnail_url && !thumbError;
  const hasPrice     = Boolean(product.price);
  const hasSnippet   = Boolean(product.snippet);
  const hasSource    = Boolean(product.source);

  return (
    <div className="sp-card">
      {/* ── Hero row: thumbnail + main info ── */}
      <div className="sp-card__hero">

        {/* Thumbnail */}
        <div className="sp-card__thumb-wrap">
          {hasThumbnail ? (
            <img
              src={product.thumbnail_url}
              alt={product.name}
              className="sp-card__thumb"
              onError={() => setThumbError(true)}
            />
          ) : (
            <div className="sp-card__thumb sp-card__thumb--placeholder">
              <ImagePlaceholderIcon />
            </div>
          )}
        </div>

        {/* Text info */}
        <div className="sp-card__info">
          <div className="sp-card__brand-row">
            {product.brand && (
              <span className="sp-card__brand">{product.brand}</span>
            )}
            {confidence && (
              <span className="sp-card__confidence">{confidence}</span>
            )}
          </div>

          <p className="sp-card__name">{product.name}</p>

          {/* Price + source */}
          <div className="sp-card__meta-row">
            {hasPrice && (
              <span className="sp-card__price">{product.price}</span>
            )}
            {hasSource && (
              <span className="sp-card__source">{product.source}</span>
            )}
          </div>
        </div>
      </div>

      {/* ── Snippet ── */}
      {hasSnippet && (
        <p className="sp-card__snippet">{product.snippet}</p>
      )}

      {/* ── Footer: category + delivery + shop button ── */}
      <div className="sp-card__footer">
        <div className="sp-card__footer-left">
          <span
            className="sp-card__category"
            style={{
              background:   cat.bg,
              borderColor:  cat.border,
              color:        cat.text,
            }}
          >
            {product.category || 'other'}
          </span>
        </div>

        {product.shopping_url && (
          <a
            href={product.shopping_url}
            target="_blank"
            rel="noopener noreferrer"
            className="sp-card__shop-btn"
          >
            Shop&nbsp;<ExternalLinkIcon />
          </a>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ShoppingPanel
// ---------------------------------------------------------------------------
export default function ShoppingPanel({
  isOpen,
  onClose,
  activeProducts,
  currentTime,
  pipelineStatus,
  isFullscreen = false,
}) {
  const fmt = (s) => {
    if (s == null) return '0:00';
    const m   = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const renderBody = () => {
    if (pipelineStatus === 'loading') {
      return (
        <div className="sp-empty">
          <div className="sp-spinner" />
          <p>Analysing video…</p>
          <p className="sp-empty__sub">Products will appear here as the video plays.</p>
        </div>
      );
    }

    if (pipelineStatus === 'idle' || pipelineStatus === 'error') {
      return (
        <div className="sp-empty">
          <ShoppingBagIcon />
          <p>{pipelineStatus === 'error' ? 'Analysis failed.' : 'Not analysed yet.'}</p>
          <p className="sp-empty__sub">
            Use the <strong>Analyse Video</strong> button below the player to detect products.
          </p>
        </div>
      );
    }

    if (!activeProducts || activeProducts.length === 0) {
      return (
        <div className="sp-empty">
          <ShoppingBagIcon />
          <p>No products right now</p>
          <p className="sp-empty__sub">
            Products will appear here when detected in the current frame.
          </p>
        </div>
      );
    }

    return (
      <div className="sp-product-list">
        {activeProducts.map((p) => (
          <ProductCard key={p.id} product={p} />
        ))}
      </div>
    );
  };

  return (
    <>
      {/* Backdrop (mobile) */}
      {isOpen && <div className="sp-backdrop" onClick={onClose} />}

      <aside className={`sp-panel ${isOpen ? 'open' : ''} ${isFullscreen ? 'sp-panel--fullscreen' : ''}`}>
        <div className="sp-panel__header">
          <div className="sp-panel__title-row">
            <ShoppingBagIcon />
            <h2 className="sp-panel__title">Products</h2>
            {activeProducts?.length > 0 && (
              <span className="sp-panel__count">{activeProducts.length}</span>
            )}
          </div>
          <div className="sp-panel__time">@ {fmt(currentTime)}</div>
          <button className="yt-icon-btn sp-panel__close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="sp-panel__body">{renderBody()}</div>
      </aside>
    </>
  );
}
