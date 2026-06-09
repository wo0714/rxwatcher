'use client'

/**
 * web/app/cases/[id]/page.tsx
 * RxWatcher case detail page.
 * Shows order metadata, prescription, quality flags, doctor notes,
 * 4×2 scan image grid with lightbox, and interactive 3D PLY viewer.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { use, useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { StatusBadge, ToothPills, QualityFlags } from '@/components/CaseDetail'
import ScanGrid from '@/components/ScanGrid'

// Loaded dynamically — Three.js must not run on the server
const PLYViewer = dynamic(() => import('@/components/PLYViewer'), { ssr: false })

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export default function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [viewer3D, setViewer3D] = useState(false)

  useEffect(() => {
    fetch(`${API}/cases/${id}`)
      .then(r => { if (!r.ok) throw new Error('Not found'); return r.json() })
      .then(setData)
      .catch(() => setError('Case not found.'))
  }, [id])

  if (error) return (
    <div>
      <Link href="/" className="back-link">← Back</Link>
      <div className="empty-state">{error}</div>
    </div>
  )

  if (!data) return (
    <div>
      <Link href="/" className="back-link">← Back</Link>
      <div className="empty-state"><div className="spinner" style={{ marginBottom: 8 }} />Loading…</div>
    </div>
  )

  const o = data.raw_result?.order  ?? data
  const p = data.raw_result?.prescription ?? {}
  const q = data.raw_result?.quality ?? { status: data.quality_status, flags: data.quality_flags }
  const orderId = data.order_id

  return (
    <>
      <Link href="/" className="back-link">← Back to cases</Link>

      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Order</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>#{orderId}</div>
        </div>
        <StatusBadge status={q.status} />
      </div>

      {/* Two-column: metadata + quality */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>

        {/* Metadata */}
        <div className="card">
          <div className="section-title" style={{ marginBottom: 16 }}>Case Details</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="meta-item">
              <div className="meta-label">Patient</div>
              <div className="meta-value" style={{ fontSize: 16, fontWeight: 600 }}>{o.patient ?? data.patient}</div>
            </div>
            <div className="meta-item">
              <div className="meta-label">Doctor</div>
              <div className="meta-value">{o.doctor ?? data.doctor}</div>
            </div>
            <div className="meta-item">
              <div className="meta-label">Clinic</div>
              <div className="meta-value" style={{ fontSize: 12, color: 'var(--muted)' }}>
                {o.clinic_address ?? data.clinic_address}
              </div>
            </div>
            <div className="meta-item">
              <div className="meta-label">Procedure</div>
              <div className="meta-value">{o.procedure ?? '—'}</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="meta-item">
                <div className="meta-label">Due Date</div>
                <div className="meta-value">{o.due_date ?? data.due_date}</div>
              </div>
              <div className="meta-item">
                <div className="meta-label">Processed</div>
                <div className="meta-value">{data.processed_at?.slice(0, 10)}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Prescription + quality */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <div className="section-title" style={{ marginBottom: 12 }}>Prescription</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="meta-item">
                <div className="meta-label">Prep Teeth (FDI)</div>
                <ToothPills teeth={p.prep_teeth_fdi ?? data.prep_teeth_fdi ?? []} />
              </div>
              {(p.bridge_region_fdi ?? data.bridge_region ?? []).length > 0 && (
                <div className="meta-item">
                  <div className="meta-label">Bridge Region</div>
                  <ToothPills teeth={p.bridge_region_fdi ?? data.bridge_region} />
                </div>
              )}
              <div className="meta-item">
                <div className="meta-label">Jaw</div>
                <div className="meta-value" style={{ textTransform: 'capitalize' }}>
                  {data.prep_jaw ?? '—'}
                </div>
              </div>
              {/* Restorations */}
              {(p.restorations ?? []).map((r: any, i: number) => (
                <div key={i} style={{
                  background: 'var(--surface2)', borderRadius: 6, padding: '8px 12px',
                  fontSize: 12, display: 'flex', gap: 10, alignItems: 'center'
                }}>
                  <span className="tooth-pill">#{r.tooth_fdi}</span>
                  <span>{r.in_bridge ?? r.type}</span>
                  <span style={{ color: 'var(--muted)' }}>{r.material}</span>
                  {r.shade?.middle && <span style={{ color: 'var(--accent)' }}>{r.shade.middle}</span>}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="section-title" style={{ marginBottom: 12 }}>Quality</div>
            {(q.flags ?? []).length === 0
              ? <div style={{ color: 'var(--pass)', fontSize: 13 }}>✓ No issues detected</div>
              : <QualityFlags flags={q.flags} />
            }
          </div>
        </div>
      </div>

      {/* Doctor notes */}
      {(o.notes ?? data.notes)?.trim() && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="section-title" style={{ marginBottom: 10 }}>Doctor Notes</div>
          <pre className="notes-box">{o.notes ?? data.notes}</pre>
        </div>
      )}

      {/* Scan image grid */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div className="section-title" style={{ margin: 0 }}>Scan Views</div>
        <button
          onClick={() => setViewer3D(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: 7,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 7,
            color: 'var(--text)',
            padding: '7px 16px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'border-color 0.15s, background 0.15s',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--accent)'
            ;(e.currentTarget as HTMLButtonElement).style.background = 'var(--surface2)'
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)'
            ;(e.currentTarget as HTMLButtonElement).style.background = 'var(--surface)'
          }}
        >
          <span style={{ fontSize: 16 }}>🔲</span> View in 3D
        </button>
      </div>

      <ScanGrid
        individual={data.raw_result?.output?.individual ?? {}}
        orderId={orderId}
        apiBase={API}
      />

      {/* 3D viewer modal */}
      {viewer3D && (() => {
        const sf = data.raw_result?.scan_files ?? {}
        const upperPly = sf.upper_ply ? `${API}/ply/${orderId}?filename=${encodeURIComponent(sf.upper_ply)}` : null
        const lowerPly = sf.lower_ply ? `${API}/ply/${orderId}?filename=${encodeURIComponent(sf.lower_ply)}` : null
        return (
          <PLYViewer
            upperUrl={upperPly}
            lowerUrl={lowerPly}
            onClose={() => setViewer3D(false)}
            orderId={orderId}
            prepTeeth={p.prep_teeth_fdi ?? []}
            prepJaw={data.prep_jaw ?? data.raw_result?.prep_jaw}
          />
        )
      })()}
    </>
  )
}