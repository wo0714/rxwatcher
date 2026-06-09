'use client'

/**
 * web/app/page.tsx
 * RxWatcher home page.
 * Upload zone for iTero zip packages, latest result display,
 * and searchable table of all previously processed cases.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { StatusBadge, ToothPills, QualityFlags } from '@/components/CaseDetail'
import ScanGrid from '@/components/ScanGrid'

const PLYViewer = dynamic(() => import('@/components/PLYViewer'), { ssr: false })

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type Case = {
  order_id: string
  patient: string
  doctor: string
  clinic_address: string
  prep_teeth_fdi: number[]
  prep_jaw: string
  due_date: string
  processed_at: string
  quality_status: string
  quality_flags: { code: string; severity: string; description: string }[]
  all_views_img: string
}

// ── Upload Zone ───────────────────────────────────────────────────────────────
function UploadZone({ onResult }: { onResult: (r: Case) => void }) {
  const [dragging, setDragging] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = useCallback(async (file: File) => {
    if (!file.name.endsWith('.zip')) {
      setError('Only .zip files are accepted.')
      return
    }
    setProcessing(true)
    setError('')
    const body = new FormData()
    body.append('file', file)
    try {
      const res = await fetch(`${API}/process`, { method: 'POST', body })
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(msg.detail ?? res.statusText)
      }
      const result = await res.json()
      onResult(result)
    } catch (e: any) {
      setError(e.message ?? 'Processing failed')
    } finally {
      setProcessing(false)
    }
  }, [onResult])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) upload(file)
  }, [upload])

  return (
    <div
      className={`upload-zone${dragging ? ' drag-over' : ''}`}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => !processing && inputRef.current?.click()}
    >
      <input ref={inputRef} type="file" accept=".zip"
        onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />

      {processing ? (
        <>
          <div className="spinner" />
          <div className="upload-title">Processing scan package…</div>
          <div className="upload-hint">This takes 30–60 seconds. Please wait.</div>
        </>
      ) : (
        <>
          <div className="upload-icon">📦</div>
          <div className="upload-title">Drop iTero zip here</div>
          <div className="upload-hint">or click to browse — .zip packages only</div>
        </>
      )}
      {error && <div style={{ color: 'var(--flag)', marginTop: 12, fontSize: 13 }}>⚠ {error}</div>}
    </div>
  )
}

// ── Latest result card ────────────────────────────────────────────────────────
function LatestResult({ result }: { result: Case }) {
  const o = (result as any).order ?? result
  const p = (result as any).prescription ?? {}
  const q = (result as any).quality ?? { status: result.quality_status, flags: result.quality_flags }
  const [viewer3D, setViewer3D] = useState(false)
  const orderId = result.order_id ?? o.id
  const sf = (result as any).scan_files ?? {}

  return (
    <div style={{ marginTop: 32 }}>
      <div className="section-title">Latest Result</div>
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Order</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>
              #{o.id ?? result.order_id}
            </div>
          </div>
          <StatusBadge status={q.status ?? result.quality_status} />
        </div>

        <div className="meta-grid">
          <div className="meta-item">
            <div className="meta-label">Patient</div>
            <div className="meta-value">{o.patient ?? result.patient}</div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Doctor</div>
            <div className="meta-value">{o.doctor ?? result.doctor}</div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Clinic</div>
            <div className="meta-value" style={{ fontSize: 12 }}>{o.clinic_address ?? result.clinic_address}</div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Due Date</div>
            <div className="meta-value">{o.due_date ?? result.due_date}</div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Prep Teeth (FDI)</div>
            <ToothPills teeth={p.prep_teeth_fdi ?? result.prep_teeth_fdi ?? []} />
          </div>
          <div className="meta-item">
            <div className="meta-label">Jaw</div>
            <div className="meta-value" style={{ textTransform: 'capitalize' }}>
              {(result as any).prep_jaw ?? '—'}
            </div>
          </div>
        </div>

        {(q.flags ?? result.quality_flags ?? []).length > 0 && (
          <div style={{ marginTop: 20 }}>
            <QualityFlags flags={q.flags ?? result.quality_flags} />
          </div>
        )}
      </div>

      {/* Scan image grid */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="section-title" style={{ margin: 0 }}>Scan Views</div>
        <button
          onClick={() => setViewer3D(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: 7,
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 7, color: 'var(--text)', padding: '7px 16px',
            fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}
        >
          <span style={{ fontSize: 16 }}>🔲</span> View in 3D
        </button>
      </div>

      <ScanGrid
        individual={(result as any).output?.individual ?? {}}
        orderId={orderId}
        apiBase={API}
      />

      {viewer3D && (
        <PLYViewer
          upperUrl={sf.upper_ply ? `${API}/ply/${orderId}?filename=${encodeURIComponent(sf.upper_ply)}` : null}
          lowerUrl={sf.lower_ply ? `${API}/ply/${orderId}?filename=${encodeURIComponent(sf.lower_ply)}` : null}
          onClose={() => setViewer3D(false)}
          orderId={orderId}
          prepTeeth={(result as any).prescription?.prep_teeth_fdi ?? result.prep_teeth_fdi ?? []}
          prepJaw={(result as any).prep_jaw ?? ''}
        />
      )}
    </div>
  )
}

// ── Case table ────────────────────────────────────────────────────────────────
function CaseTable({ cases }: { cases: Case[] }) {
  const [query, setQuery] = useState('')

  const filtered = cases.filter(c => {
    const q = query.toLowerCase()
    return !q
      || c.order_id?.includes(q)
      || c.patient?.toLowerCase().includes(q)
      || c.doctor?.toLowerCase().includes(q)
      || c.clinic_address?.toLowerCase().includes(q)
  })

  return (
    <>
      <div className="search-wrap">
        <input
          className="search-input"
          placeholder="Search by order #, patient, doctor, clinic…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">No cases found.</div>
      ) : (
        <table className="cases-table">
          <thead>
            <tr>
              <th>Order #</th>
              <th>Patient</th>
              <th>Doctor</th>
              <th>Prep Teeth</th>
              <th>Status</th>
              <th>Due</th>
              <th>Processed</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(c => (
              <tr key={c.order_id} onClick={() => window.location.href = `/cases/${c.order_id}`}>
                <td><span className="order-id">#{c.order_id}</span></td>
                <td><span className="patient-name">{c.patient}</span></td>
                <td className="muted-text">{c.doctor}</td>
                <td><ToothPills teeth={c.prep_teeth_fdi ?? []} /></td>
                <td><StatusBadge status={c.quality_status} /></td>
                <td className="muted-text">{c.due_date}</td>
                <td className="muted-text">{c.processed_at?.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [latestResult, setLatestResult] = useState<Case | null>(null)
  const [cases, setCases] = useState<Case[]>([])

  useEffect(() => {
    fetch(`${API}/cases`)
      .then(r => r.json())
      .then(setCases)
      .catch(() => {})
  }, [latestResult])

  const onResult = (r: Case) => {
    setLatestResult(r)
  }

  return (
    <>
      <UploadZone onResult={onResult} />

      {latestResult && <LatestResult result={latestResult} />}

      <div className="gap-section">
        <div className="section-title">
          Previous Cases ({cases.length})
        </div>
        <div className="card" style={{ padding: '20px 0 0' }}>
          <div style={{ padding: '0 20px 16px' }}>
            {cases.length === 0
              ? <div className="empty-state">No cases yet — upload a scan package above.</div>
              : <CaseTable cases={cases} />
            }
          </div>
        </div>
      </div>
    </>
  )
}