'use client'

/**
 * web/components/CaseDetail.tsx
 * Shared UI primitives for case display: StatusBadge, ToothPills, QualityFlags.
 * Used on both the home page (latest result) and the case detail page.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

// Shared UI components for case display

export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pass: '✓ Pass',
    needs_review: '⚠ Review',
    flagged: '✕ Flagged',
  }
  return (
    <span className={`badge badge-${status}`}>
      {labels[status] ?? status}
    </span>
  )
}

export function ToothPills({ teeth }: { teeth: number[] }) {
  if (!teeth || teeth.length === 0) return <span className="muted-text">—</span>
  return (
    <div className="tooth-pills">
      {teeth.map(t => <span key={t} className="tooth-pill">#{t}</span>)}
    </div>
  )
}

export function QualityFlags({ flags }: { flags: { code: string; severity: string; description: string }[] }) {
  if (!flags || flags.length === 0) return null
  return (
    <div className="flag-list">
      {flags.map((f, i) => (
        <div key={i} className={`flag-item flag-${f.severity}`}>
          <span className="flag-icon">{f.severity === 'critical' ? '🚨' : '⚠️'}</span>
          <div>
            <div className="flag-code">{f.code.replace(/_/g, ' ')}</div>
            <div>{f.description}</div>
          </div>
        </div>
      ))}
    </div>
  )
}