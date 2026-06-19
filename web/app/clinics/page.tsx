'use client'

/**
 * web/app/clinics/page.tsx
 * Clinic mappings management page.
 * View, edit, and delete saved address → NAS folder mappings.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'

const API =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined'
    ? `http://${window.location.hostname}:8000`
    : 'http://localhost:8000')

type Mapping = {
  id: number
  address_key: string
  nas_folder: string
  practice_name: string
  doctor_license: string
  created_at: string
}

// ── Edit Modal ────────────────────────────────────────────────────────────────
function EditModal({
  mapping, folders, onSave, onCancel,
}: {
  mapping: Mapping
  folders: string[]
  onSave: (updated: Partial<Mapping>) => void
  onCancel: () => void
}) {
  const [nasFolder,    setNasFolder]    = useState(mapping.nas_folder)
  const [practiceName, setPracticeName] = useState(mapping.practice_name || '')
  const [search,       setSearch]       = useState('')

  const filtered = folders.filter(f =>
    f.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1500,
      background: 'rgba(0,0,0,0.8)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
    }}>
      <div className="card" style={{ maxWidth: 500, width: '100%', padding: 28 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 20 }}>
          ✏️ Edit Mapping
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            Address Key (not editable)
          </div>
          <div style={{
            background: 'var(--surface2)', borderRadius: 5,
            padding: '8px 12px', fontSize: 12, color: 'var(--muted)',
            fontFamily: 'monospace',
          }}>
            {mapping.address_key}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            Practice Name
          </div>
          <input
            value={practiceName}
            onChange={e => setPracticeName(e.target.value)}
            placeholder="e.g. Wittmeir Dental"
            style={{
              width: '100%', background: 'var(--surface)',
              border: '1px solid var(--border)', borderRadius: 5,
              padding: '8px 12px', fontSize: 13, color: 'var(--text)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            NAS Folder — current: <span style={{ color: 'var(--accent)' }}>{mapping.nas_folder}</span>
          </div>
          <input
            className="search-input"
            style={{ width: '100%', marginBottom: 6 }}
            placeholder="Search folders…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <div style={{
            maxHeight: 180, overflow: 'auto',
            border: '1px solid var(--border)', borderRadius: 6,
            background: '#0f172a',
          }}>
            {filtered.map(f => (
              <div
                key={f}
                onClick={() => setNasFolder(f)}
                style={{
                  padding: '7px 12px', fontSize: 13, cursor: 'pointer',
                  background: nasFolder === f ? 'var(--surface2)' : 'transparent',
                  color:      nasFolder === f ? 'var(--accent)'   : 'var(--text)',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                {nasFolder === f && '✓ '}{f}
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{
            background: 'transparent', border: '1px solid var(--border)',
            color: 'var(--muted)', borderRadius: 6, padding: '8px 18px',
            fontSize: 13, cursor: 'pointer',
          }}>Cancel</button>
          <button
            onClick={() => onSave({ nas_folder: nasFolder, practice_name: practiceName })}
            style={{
              background: 'var(--accent)', color: '#0f172a',
              border: 'none', borderRadius: 6, padding: '8px 22px',
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >Save</button>
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function ClinicsPage() {
  const [mappings, setMappings] = useState<Mapping[]>([])
  const [folders,  setFolders]  = useState<string[]>([])
  const [loading,  setLoading]  = useState(true)
  const [editing,  setEditing]  = useState<Mapping | null>(null)
  const [query,    setQuery]    = useState('')

  useEffect(() => {
    Promise.all([
      fetch(`${API}/clinics/mappings`).then(r => r.json()),
      fetch(`${API}/clinics/folders`).then(r => r.json()),
    ]).then(([maps, dirs]) => {
      setMappings(maps)
      setFolders(dirs)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const handleDelete = async (id: number, folder: string) => {
    if (!confirm(`Delete mapping for "${folder}"?\nFuture uploads from this clinic will show the picker again.`)) return
    const res = await fetch(`${API}/clinics/mappings/${id}`, { method: 'DELETE' })
    if (res.ok) setMappings(prev => prev.filter(m => m.id !== id))
  }

  const handleSave = async (updated: Partial<Mapping>) => {
    if (!editing) return
    const res = await fetch(`${API}/clinics/mappings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        address:        editing.address_key,
        nas_folder:     updated.nas_folder,
        practice_name:  updated.practice_name,
        doctor_license: editing.doctor_license,
      }),
    })
    if (res.ok) {
      setMappings(prev => prev.map(m =>
        m.id === editing.id ? { ...m, ...updated } : m
      ))
    }
    setEditing(null)
  }

  const filtered = mappings.filter(m => {
    const q = query.toLowerCase()
    return !q
      || m.nas_folder.toLowerCase().includes(q)
      || m.practice_name?.toLowerCase().includes(q)
      || m.address_key.toLowerCase().includes(q)
  })

  return (
    <>
      {editing && (
        <EditModal
          mapping={editing}
          folders={folders}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Link href="/" className="back-link" style={{ margin: 0 }}>← Back</Link>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>Clinic Mappings</div>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>
            Links ship-to addresses to NAS clinic folders for automatic routing.
          </div>
        </div>
        <div style={{
          background: 'var(--surface2)', borderRadius: 8,
          padding: '8px 18px', fontSize: 13, color: 'var(--muted)',
        }}>
          {mappings.length} mapped
        </div>
      </div>

      <div className="card" style={{ padding: '20px 0 0' }}>
        <div style={{ padding: '0 20px 16px' }}>
          <input
            className="search-input"
            placeholder="Search by clinic name, folder, or address…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{ width: '100%', marginBottom: 16 }}
          />

          {loading ? (
            <div className="empty-state">
              <div className="spinner" style={{ marginBottom: 8 }} />Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              {mappings.length === 0
                ? 'No mappings yet — upload a zip to create the first one.'
                : 'No mappings match your search.'}
            </div>
          ) : (
            <table className="cases-table">
              <thead>
                <tr>
                  <th>Practice Name</th>
                  <th>NAS Folder</th>
                  <th>Address Key</th>
                  <th>Linked</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(m => (
                  <tr key={m.id} style={{ cursor: 'default' }}>
                    <td style={{ fontWeight: 600 }}>
                      {m.practice_name ||
                        <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>—</span>}
                    </td>
                    <td>
                      <span style={{
                        background: 'var(--surface2)', borderRadius: 4,
                        padding: '2px 8px', fontSize: 12, fontFamily: 'monospace',
                      }}>
                        📁 {m.nas_folder}
                      </span>
                    </td>
                    <td style={{ maxWidth: 260 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'monospace' }}>
                        {m.address_key.length > 45
                          ? m.address_key.slice(0, 45) + '…'
                          : m.address_key}
                      </span>
                    </td>
                    <td className="muted-text" style={{ fontSize: 12 }}>
                      {m.created_at?.slice(0, 10) || '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          onClick={() => setEditing(m)}
                          title="Edit mapping"
                          style={{
                            background: 'transparent',
                            border: '1px solid var(--border)',
                            color: 'var(--muted)', borderRadius: 5,
                            padding: '3px 8px', fontSize: 12, cursor: 'pointer',
                          }}
                        >✏️</button>
                        <button
                          onClick={() => handleDelete(m.id, m.nas_folder)}
                          title="Delete mapping"
                          style={{
                            background: 'transparent',
                            border: '1px solid #450a0a',
                            color: 'var(--flag)', borderRadius: 5,
                            padding: '3px 8px', fontSize: 13, cursor: 'pointer',
                          }}
                        >🗑</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  )
}