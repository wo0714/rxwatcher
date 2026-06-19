'use client'

/**
 * web/components/PLYViewer.tsx
 * Interactive 3D viewer for iTero PLY scan files.
 *
 * Controls (OrbitControls):
 *   Left-drag   — rotate (0°–180° polar range)
 *   Right-drag  — pan (screen-space, X and Y work correctly)
 *   Scroll      — zoom
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { useEffect, useMemo, useRef, useState, Suspense } from 'react'
import { Canvas, useLoader, useThree, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import * as THREE from 'three'

// ── Jaw mesh ───────────────────────────────────────────────────────────────────
function ScanMesh({ url, textured, visible }: {
  url: string; textured: boolean; visible: boolean
}) {
  const geometry = useLoader(PLYLoader, url)

  useEffect(() => {
    geometry.computeVertexNormals()
  }, [geometry])

  const material = useMemo(
    () => new THREE.MeshStandardMaterial({
      vertexColors: textured,
      color:     textured ? undefined : new THREE.Color(0.55, 0.52, 0.48),
      roughness: textured ? 0.82 : 0.55,
      metalness: 0.0,
      side:      THREE.DoubleSide,
    }),
    [textured]
  )

  if (!visible) return null
  return <mesh geometry={geometry} material={material} />
}

// ── Headlight — follows the camera ────────────────────────────────────────────
function HeadLight({ intensity }: { intensity: number }) {
  const ref = useRef<THREE.PointLight>(null)
  const get = useThree(s => s.get)
  useFrame(() => {
    if (!ref.current) return
    ref.current.position.copy(get().camera.position)
    ref.current.intensity = intensity
  })
  return <pointLight ref={ref} intensity={intensity} decay={0} />
}

// ── Camera auto-fit ───────────────────────────────────────────────────────────
function CameraSetup({ controlsRef }: { controlsRef: React.RefObject<any> }) {
  const get    = useThree(s => s.get)
  const fitted = useRef(false)

  useFrame(() => {
    if (fitted.current) return
    const { camera, scene } = get()
    const box = new THREE.Box3().setFromObject(scene)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3()).length()
    if (size < 1) return
    const center = box.getCenter(new THREE.Vector3())
    const cam    = camera as THREE.PerspectiveCamera
    cam.near = size / 100
    cam.far  = size * 10
    // Narrow FOV (telephoto) + greater distance avoids fisheye/wide-angle distortion
    cam.position.set(center.x, center.y - size * 1.7, center.z + size * 0.08)
    cam.lookAt(center)
    cam.updateProjectionMatrix()
    if (controlsRef.current) {
      controlsRef.current.target.copy(center)
      controlsRef.current.update()
    }
    fitted.current = true
  })
  return null
}

// ── Toolbar helpers ───────────────────────────────────────────────────────────
function TBtn({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button onClick={onClick} style={{
      background:   active ? 'var(--accent)' : 'var(--surface2)',
      color:        active ? '#0f172a'        : 'var(--text)',
      border:       `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
      borderRadius: 6, padding: '6px 14px', fontSize: 12,
      fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
    }}>
      {children}
    </button>
  )
}

function Sep() {
  return <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 6px' }} />
}

// ── Error screen ──────────────────────────────────────────────────────────────
function PLYError({ onClose }: { onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 2000, background: '#080f1e',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 16,
    }}>
      <div style={{ fontSize: 36 }}>⚠️</div>
      <div style={{ color: 'var(--text)', fontWeight: 600 }}>3D files unavailable</div>
      <div style={{ color: 'var(--muted)', fontSize: 13, textAlign: 'center', maxWidth: 380 }}>
        This case was processed before 3D viewing was added.<br />
        Re-upload the zip package to enable the 3D viewer.
      </div>
      <button onClick={onClose} style={{
        marginTop: 8, background: 'var(--surface)',
        border: '1px solid var(--border)', borderRadius: 7,
        color: 'var(--text)', padding: '8px 20px',
        fontSize: 13, fontWeight: 600, cursor: 'pointer',
      }}>Close</button>
    </div>
  )
}

// ── Main viewer ───────────────────────────────────────────────────────────────
export type PLYViewerProps = {
  upperUrl:           string | null
  lowerUrl:           string | null
  upperPretreatUrl?:  string | null   // pre-treatment upper (if available)
  lowerPretreatUrl?:  string | null   // pre-treatment lower (if available)
  onClose:    () => void
  orderId?:   string
  prepTeeth?: number[]
  prepJaw?:   string
}

export default function PLYViewer({
  upperUrl, lowerUrl,
  upperPretreatUrl = null, lowerPretreatUrl = null,
  onClose, orderId, prepTeeth = [], prepJaw,
}: PLYViewerProps) {
  const [showUpper,      setShowUpper]      = useState(true)
  const [showLower,      setShowLower]      = useState(true)
  const [textured,       setTextured]       = useState(true)
  const [lightIntensity, setLightIntensity] = useState(1.9)
  const [loadError,      setLoadError]      = useState(false)
  const [scanVersion,    setScanVersion]    = useState<'prepped' | 'pretx'>('prepped')
  const controlsRef = useRef<any>(null)

  const hasPretreat = !!(upperPretreatUrl || lowerPretreatUrl)
  // Switch between working (prepped) and pretreatment scans
  const activeUpperUrl = (scanVersion === 'pretx' && upperPretreatUrl) ? upperPretreatUrl : upperUrl
  const activeLowerUrl = (scanVersion === 'pretx' && lowerPretreatUrl) ? lowerPretreatUrl : lowerUrl

  useEffect(() => {
    const url = upperUrl ?? lowerUrl
    if (!url) return
    fetch(url, { method: 'HEAD' })
      .then(r => { if (!r.ok) setLoadError(true) })
      .catch(() => setLoadError(true))
  }, [upperUrl, lowerUrl])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handler)
      document.body.style.overflow = ''
    }
  }, [onClose])

  if (loadError) return <PLYError onClose={onClose} />

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 2000,
      background: '#080f1e', display: 'flex', flexDirection: 'column',
    }}>
      {/* ── Toolbar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 16px', background: '#0a1120',
        borderBottom: '1px solid var(--border)', flexWrap: 'wrap',
      }}>
        <span style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 13 }}>🦷 3D View</span>

        {orderId && (
          <span style={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 5, padding: '3px 10px', fontSize: 12,
            color: 'var(--muted)', fontFamily: 'monospace',
          }}>#{orderId}</span>
        )}
        {prepTeeth.length > 0 && (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>FDI</span>
            {prepTeeth.map(t => (
              <span key={t} style={{
                background: '#1e3a5f', color: '#93c5fd',
                border: '1px solid #2563eb44',
                borderRadius: 4, padding: '2px 7px',
                fontSize: 12, fontWeight: 700,
              }}>{t}</span>
            ))}
          </div>
        )}
        {prepJaw && (
          <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'capitalize' }}>
            · {prepJaw} jaw
          </span>
        )}

        <Sep />

        <span style={{ color: 'var(--muted)', fontSize: 11 }}>JAWS</span>
        {upperUrl && <TBtn active={showUpper} onClick={() => setShowUpper(v => !v)}>{showUpper ? '✓' : '✗'} Upper</TBtn>}
        {lowerUrl && <TBtn active={showLower} onClick={() => setShowLower(v => !v)}>{showLower ? '✓' : '✗'} Lower</TBtn>}

        <Sep />

        <span style={{ color: 'var(--muted)', fontSize: 11 }}>TEXTURE</span>
        <TBtn active={textured}  onClick={() => setTextured(true)}>On</TBtn>
        <TBtn active={!textured} onClick={() => setTextured(false)}>Off</TBtn>

        {hasPretreat && <>
          <Sep />
          <span style={{ color: 'var(--muted)', fontSize: 11 }}>SCAN</span>
          <TBtn active={scanVersion === 'prepped'} onClick={() => setScanVersion('prepped')}>Prepped</TBtn>
          <TBtn active={scanVersion === 'pretx'}   onClick={() => setScanVersion('pretx')}>Pre-Tx</TBtn>
        </>}

        <Sep />

        <span style={{ color: 'var(--muted)', fontSize: 11 }}>LIGHT</span>
        <span style={{ fontSize: 11 }}>🌑</span>
        <input
          type="range" min={0.3} max={3.5} step={0.1}
          value={lightIntensity}
          onChange={e => setLightIntensity(parseFloat(e.target.value))}
          style={{ width: 90, accentColor: 'var(--accent)', cursor: 'pointer' }}
        />
        <span style={{ fontSize: 11 }}>☀️</span>

        <div style={{ flex: 1 }} />

        <span style={{ color: 'var(--muted)', fontSize: 11 }}>
          left-drag: rotate · right-drag: pan · scroll: zoom · Esc: close
        </span>

        <button onClick={onClose} style={{
          background: 'transparent', border: '1px solid var(--border)',
          color: 'var(--muted)', borderRadius: 6, padding: '6px 12px',
          cursor: 'pointer', fontSize: 13, marginLeft: 8,
        }}>✕ Close</button>
      </div>

      {/* ── Canvas ── */}
      <div style={{ flex: 1 }}>
        <Canvas
          camera={{ fov: 28, near: 0.1, far: 2000 }}
          style={{ background: '#080f1e' }}
          gl={{ antialias: true }}
        >
          <ambientLight intensity={lightIntensity * 0.15} />
          <HeadLight intensity={lightIntensity} />
          <directionalLight position={[40,  60,  20]} intensity={lightIntensity * 0.4} />
          <directionalLight position={[-40,-20, -20]} intensity={lightIntensity * 0.08} />

          {upperUrl && <Suspense fallback={null}><ScanMesh url={activeUpperUrl!} textured={textured} visible={showUpper} /></Suspense>}
          {lowerUrl && <Suspense fallback={null}><ScanMesh url={activeLowerUrl!} textured={textured} visible={showLower} /></Suspense>}

          <CameraSetup controlsRef={controlsRef} />

          <OrbitControls
            ref={controlsRef}
            enableDamping
            dampingFactor={0.08}
            rotateSpeed={0.6}
            zoomSpeed={0.8}
            panSpeed={0.6}
            screenSpacePanning
          />
        </Canvas>
      </div>
    </div>
  )
}