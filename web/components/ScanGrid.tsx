'use client'

/**
 * web/components/ScanGrid.tsx
 * 4×2 scan image grid with lightbox overlay.
 * Row 1: textured renders. Row 2: untextured renders.
 * Clicking any thumbnail opens it full-screen; Esc or outside-click closes.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { useState, useEffect, useCallback } from 'react'

// Grid order: row 1 = textured, row 2 = untextured — left to right matches the all_views.png layout
const GRID_ITEMS = [
  { key: 'buccal_tex',        label: 'Right Buccal',     mode: 'TEXTURED'   },
  { key: 'anterior_tex',      label: 'Anterior',          mode: 'TEXTURED'   },
  { key: 'pal_ling_tex',      label: 'Palatal / Lingual', mode: 'TEXTURED'   },
  { key: 'prep_occlusal_tex', label: 'Prep Occlusal',     mode: 'TEXTURED'   },
  { key: 'buccal_grey',       label: 'Right Buccal',      mode: 'UNTEXTURED' },
  { key: 'anterior_grey',     label: 'Anterior',          mode: 'UNTEXTURED' },
  { key: 'pal_ling_grey',     label: 'Palatal / Lingual', mode: 'UNTEXTURED' },
  { key: 'prep_occlusal_grey',label: 'Prep Occlusal',     mode: 'UNTEXTURED' },
]

type Props = {
  individual: Record<string, string>   // key → filename
  orderId: string
  apiBase: string
}

export default function ScanGrid({ individual, orderId, apiBase }: Props) {
  const [lightbox, setLightbox] = useState<{ src: string; title: string } | null>(null)

  // Close on Escape
  const onKey = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') setLightbox(null)
  }, [])

  useEffect(() => {
    if (lightbox) {
      document.addEventListener('keydown', onKey)
      document.body.style.overflow = 'hidden'
    } else {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [lightbox, onKey])

  const items = GRID_ITEMS.filter(item => individual[item.key])

  if (items.length === 0) return (
    <div className="empty-state">No individual renders available.</div>
  )

  return (
    <>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: '10px',
      }}>
        {items.map(item => {
          const filename = individual[item.key]
          const src = `${apiBase}/images/${orderId}/${filename}`
          const isTextured = item.mode === 'TEXTURED'

          return (
            <div
              key={item.key}
              onClick={() => setLightbox({ src, title: `${item.label} — ${item.mode}` })}
              style={{
                cursor: 'pointer',
                borderRadius: '6px',
                overflow: 'hidden',
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                transition: 'border-color 0.15s, transform 0.15s',
                position: 'relative',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--accent)'
                ;(e.currentTarget as HTMLDivElement).style.transform = 'scale(1.015)'
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'
                ;(e.currentTarget as HTMLDivElement).style.transform = 'scale(1)'
              }}
            >
              {/* Image */}
              <img
                src={src}
                alt={`${item.label} ${item.mode}`}
                style={{ width: '100%', display: 'block', aspectRatio: '14/9', objectFit: 'cover' }}
                loading="lazy"
              />

              {/* Caption bar */}
              <div style={{
                padding: '6px 10px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: 'var(--surface)',
                borderTop: '1px solid var(--border)',
              }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>
                  {item.label}
                </span>
                <span style={{
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: '0.05em',
                  color: isTextured ? '#f59e0b' : '#94a3b8',
                }}>
                  {item.mode}
                </span>
              </div>

              {/* Expand hint */}
              <div style={{
                position: 'absolute',
                top: 6,
                right: 6,
                background: 'rgba(0,0,0,0.55)',
                borderRadius: 4,
                padding: '2px 6px',
                fontSize: 11,
                color: '#cbd5e1',
                opacity: 0,
                transition: 'opacity 0.15s',
                pointerEvents: 'none',
              }}
                className="expand-hint"
              >
                ⛶ expand
              </div>
            </div>
          )
        })}
      </div>

      {/* ── Lightbox ── */}
      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,0.88)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            cursor: 'zoom-out',
          }}
        >
          {/* Title */}
          <div style={{
            color: '#e2e8f0',
            fontSize: 13,
            fontWeight: 600,
            marginBottom: 12,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
          }}>
            {lightbox.title}
          </div>

          {/* Image */}
          <img
            src={lightbox.src}
            alt={lightbox.title}
            onClick={e => e.stopPropagation()}
            style={{
              maxWidth: '100%',
              maxHeight: 'calc(100vh - 120px)',
              objectFit: 'contain',
              borderRadius: '8px',
              boxShadow: '0 25px 80px rgba(0,0,0,0.8)',
              cursor: 'default',
            }}
          />

          {/* Close hint */}
          <div style={{ color: '#475569', fontSize: 12, marginTop: 16 }}>
            Click outside or press Esc to close
          </div>
        </div>
      )}

      <style>{`
        div:hover .expand-hint { opacity: 1 !important; }
      `}</style>
    </>
  )
}