"use client";

/**
 * web/app/page.tsx
 * RxWatcher home page.
 * Inbox upload with auto-routing to clinic NAS folders,
 * clinic picker for new clinics, case table with search + delete.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { StatusBadge, ToothPills, QualityFlags } from "@/components/CaseDetail";
import ScanGrid from "@/components/ScanGrid";

const PLYViewer = dynamic(() => import("@/components/PLYViewer"), {
  ssr: false,
});

const API =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000");

type Case = {
  order_id: string;
  patient: string;
  doctor: string;
  clinic_address: string;
  clinic_name: string;
  prep_teeth_fdi: number[];
  prep_jaw: string;
  due_date: string;
  processed_at: string;
  quality_status: string;
  quality_flags: { code: string; severity: string; description: string }[];
  all_views_img: string;
};

// ── Clinic Picker Modal ─────────────────────────────────────────────────────
function ClinicPicker({
  orderInfo,
  zipPath,
  onDone,
  onCancel,
}: {
  orderInfo: any;
  zipPath: string;
  onDone: (result: any) => void;
  onCancel: () => void;
}) {
  const [folders, setFolders] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState("");
  const [practiceName, setPracticeName] = useState(
    orderInfo.practice_name || "",
  );

  useEffect(() => {
    fetch(`${API}/clinics/folders`)
      .then((r) => r.json())
      .then(setFolders)
      .catch(() => {});
  }, []);

  const filtered = folders.filter((f) =>
    f.toLowerCase().includes(search.toLowerCase()),
  );

  const submit = async () => {
    if (!selected) return;
    setProcessing(true);
    setError("");
    try {
      const res = await fetch(`${API}/inbox/link-and-process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zip_path: zipPath,
          nas_folder: selected,
          address: orderInfo.address,
          practice_name: practiceName,
          doctor_license: orderInfo.license || "",
        }),
      });
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: "Failed" }));
        throw new Error(msg.detail ?? "Processing failed");
      }
      const data = await res.json();
      onDone(data.result ?? data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1500,
        background: "rgba(0,0,0,0.8)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        className="card"
        style={{ maxWidth: 520, width: "100%", padding: 28 }}
      >
        <div
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: "var(--accent)",
            marginBottom: 20,
          }}
        >
          🏥 New Clinic Detected
        </div>

        <div style={{ marginBottom: 20, fontSize: 13 }}>
          <div style={{ color: "var(--muted)", marginBottom: 8 }}>
            This clinic hasn't been linked to a NAS folder yet:
          </div>
          <div
            style={{
              background: "var(--surface2)",
              borderRadius: 6,
              padding: "10px 14px",
            }}
          >
            <div>
              <strong>Order:</strong> #{orderInfo.order_id}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginTop: 4,
              }}
            >
              <strong style={{ whiteSpace: "nowrap" }}>Practice:</strong>
              <input
                value={practiceName}
                onChange={(e) => setPracticeName(e.target.value)}
                placeholder="Practice name"
                style={{
                  flex: 1,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 5,
                  padding: "4px 8px",
                  fontSize: 13,
                  color: "var(--text)",
                }}
              />
            </div>
            <div>
              <strong>Patient:</strong> {orderInfo.patient}
            </div>
            <div>
              <strong>Doctor:</strong> {orderInfo.doctor}
            </div>
            <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
              📍 {orderInfo.address}
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--muted)",
              textTransform: "uppercase",
              marginBottom: 6,
            }}
          >
            Select NAS Clinic Folder
          </div>
          <input
            className="search-input"
            style={{ width: "100%", marginBottom: 8 }}
            placeholder="Search clinic folders…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div
            style={{
              maxHeight: 200,
              overflow: "auto",
              border: "1px solid var(--border)",
              borderRadius: 6,
              background: "#0f172a",
            }}
          >
            {filtered.length === 0 ? (
              <div
                style={{
                  padding: 16,
                  textAlign: "center",
                  color: "var(--muted)",
                  fontSize: 13,
                }}
              >
                No folders found
              </div>
            ) : (
              filtered.map((f) => (
                <div
                  key={f}
                  onClick={() => setSelected(f)}
                  style={{
                    padding: "8px 14px",
                    fontSize: 13,
                    cursor: "pointer",
                    background:
                      selected === f ? "var(--surface2)" : "transparent",
                    color: selected === f ? "var(--accent)" : "var(--text)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {selected === f && "✓ "}
                  {f}
                </div>
              ))
            )}
          </div>
        </div>

        {error && (
          <div style={{ color: "var(--flag)", fontSize: 13, marginBottom: 8 }}>
            ⚠ {error}
          </div>
        )}

        <div
          style={{
            display: "flex",
            gap: 10,
            justifyContent: "flex-end",
            marginTop: 16,
          }}
        >
          <button
            onClick={onCancel}
            style={{
              background: "transparent",
              border: "1px solid var(--border)",
              color: "var(--muted)",
              borderRadius: 6,
              padding: "8px 18px",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!selected || processing}
            style={{
              background: selected ? "var(--accent)" : "var(--surface2)",
              color: selected ? "#0f172a" : "var(--muted)",
              border: "none",
              borderRadius: 6,
              padding: "8px 22px",
              fontSize: 13,
              fontWeight: 600,
              cursor: selected ? "pointer" : "default",
              opacity: processing ? 0.6 : 1,
            }}
          >
            {processing ? "Processing…" : "Link & Process"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Upload Zone ────────────────────────────────────────────────────────────────
function UploadZone({ onResult }: { onResult: (r: any) => void }) {
  const [dragging, setDragging] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState("");
  const [clinicPicker, setClinicPicker] = useState<{
    orderInfo: any;
    zipPath: string;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (file: File) => {
      if (!file.name.endsWith(".zip")) {
        setError("Only .zip files are accepted.");
        return;
      }
      setProcessing(true);
      setError("");

      const body = new FormData();
      body.append("file", file);

      try {
        // Try inbox processing first (with clinic routing)
        const res = await fetch(`${API}/inbox/process`, {
          method: "POST",
          body,
        });
        if (!res.ok) {
          const msg = await res
            .json()
            .catch(() => ({ detail: "Unknown error" }));
          throw new Error(msg.detail ?? res.statusText);
        }
        const data = await res.json();

        if (data.status === "needs_clinic_link") {
          // Show clinic picker
          setProcessing(false);
          setClinicPicker({
            orderInfo: data.order_info,
            zipPath: data.zip_path,
          });
        } else {
          // Auto-routed and processed
          onResult(data.result ?? data);
          setProcessing(false);
        }
      } catch (e: any) {
        setError(e.message ?? "Processing failed");
        setProcessing(false);
      }
    },
    [onResult],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) upload(file);
    },
    [upload],
  );

  return (
    <>
      <div
        className={`upload-zone${dragging ? " drag-over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !processing && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
        {processing ? (
          <>
            <div className="spinner" />
            <div className="upload-title">Processing scan package…</div>
            <div className="upload-hint">
              Routing to clinic folder + generating screenshots. 30–90 seconds.
            </div>
          </>
        ) : (
          <>
            <div className="upload-icon">📦</div>
            <div className="upload-title">Drop iTero zip here</div>
            <div className="upload-hint">
              Auto-routes to clinic folder on NAS, renames, extracts, and
              processes
            </div>
          </>
        )}
        {error && (
          <div style={{ color: "var(--flag)", marginTop: 12, fontSize: 13 }}>
            ⚠ {error}
          </div>
        )}
      </div>

      {clinicPicker && (
        <ClinicPicker
          orderInfo={clinicPicker.orderInfo}
          zipPath={clinicPicker.zipPath}
          onDone={(result) => {
            setClinicPicker(null);
            onResult(result);
          }}
          onCancel={() => setClinicPicker(null)}
        />
      )}
    </>
  );
}

// ── Latest result ─────────────────────────────────────────────────────────────
function LatestResult({ result }: { result: any }) {
  const o = result.order ?? result;
  const p = result.prescription ?? {};
  const q = result.quality ?? {
    status: result.quality_status,
    flags: result.quality_flags,
  };
  const sf = result.scan_files ?? {};
  const [viewer3D, setViewer3D] = useState(false);
  const orderId = result.order_id ?? o.id;
  const plyUrl = (name: string | null) =>
    name ? `${API}/ply/${orderId}?filename=${encodeURIComponent(name)}` : null;

  return (
    <div style={{ marginTop: 32 }}>
      <div className="section-title">Latest Result</div>
      <div className="card" style={{ marginBottom: 20 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 11,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.07em",
              }}
            >
              Order
            </div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: "var(--accent)",
                fontFamily: "monospace",
              }}
            >
              #{o.id ?? orderId}
            </div>
            {result.clinic_name && (
              <div
                style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}
              >
                📁 {result.clinic_name}
              </div>
            )}
          </div>
          <StatusBadge status={q.status ?? result.quality_status} />
        </div>
        <div className="meta-grid">
          <div className="meta-item">
            <div className="meta-label">Practice Name</div>
            <div className="meta-value">
              {result.practice_name || o.clinic_name || "—"}
            </div>
          </div>
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
            <div className="meta-value" style={{ fontSize: 12 }}>
              {o.clinic_address ?? result.clinic_address}
            </div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Due Date</div>
            <div className="meta-value">{o.due_date ?? result.due_date}</div>
          </div>
          <div className="meta-item">
            <div className="meta-label">Prep Teeth (FDI)</div>
            <ToothPills
              teeth={p.prep_teeth_fdi ?? result.prep_teeth_fdi ?? []}
            />
          </div>
          <div className="meta-item">
            <div className="meta-label">Jaw</div>
            <div className="meta-value" style={{ textTransform: "capitalize" }}>
              {result.prep_jaw ?? "—"}
            </div>
          </div>
        </div>
        {(q.flags ?? result.quality_flags ?? []).length > 0 && (
          <div style={{ marginTop: 20 }}>
            <QualityFlags flags={q.flags ?? result.quality_flags} />
          </div>
        )}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div className="section-title" style={{ margin: 0 }}>
          Scan Views
        </div>
        <button
          onClick={() => setViewer3D(true)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 7,
            color: "var(--text)",
            padding: "7px 16px",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          <span style={{ fontSize: 16 }}>🔲</span> View in 3D
        </button>
      </div>

      <ScanGrid
        individual={result.output?.individual ?? {}}
        orderId={orderId}
        apiBase={API}
      />

      {viewer3D && (
        <PLYViewer
          upperUrl={plyUrl(sf.upper_ply)}
          lowerUrl={plyUrl(sf.lower_ply)}
          upperPretreatUrl={plyUrl(sf.upper_pretreat_ply ?? null)}
          lowerPretreatUrl={plyUrl(sf.lower_pretreat_ply ?? null)}
          onClose={() => setViewer3D(false)}
          orderId={orderId}
          prepTeeth={p.prep_teeth_fdi ?? result.prep_teeth_fdi ?? []}
          prepJaw={result.prep_jaw ?? ""}
        />
      )}
    </div>
  );
}

// ── Case table ────────────────────────────────────────────────────────────────
function CaseTable({
  cases,
  onDelete,
}: {
  cases: Case[];
  onDelete: (id: string) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = cases.filter((c) => {
    const q = query.toLowerCase();
    return (
      !q ||
      c.order_id?.includes(q) ||
      c.patient?.toLowerCase().includes(q) ||
      c.doctor?.toLowerCase().includes(q) ||
      c.clinic_address?.toLowerCase().includes(q) ||
      c.clinic_name?.toLowerCase().includes(q)
    );
  });

  const handleDelete = async (e: React.MouseEvent, orderId: string) => {
    e.stopPropagation();
    if (
      !confirm(`Delete case #${orderId} and all files?\nThis cannot be undone.`)
    )
      return;
    try {
      const res = await fetch(`${API}/cases/${orderId}`, { method: "DELETE" });
      if (res.ok) onDelete(orderId);
    } catch {
      /* ignore */
    }
  };

  return (
    <>
      <div className="search-wrap">
        <input
          className="search-input"
          placeholder="Search by order #, patient, doctor, clinic…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
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
              <th>Clinic</th>
              <th>Prep Teeth</th>
              <th>Status</th>
              <th>Due</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr
                key={c.order_id}
                onClick={() => (window.location.href = `/cases/${c.order_id}`)}
              >
                <td>
                  <span className="order-id">#{c.order_id}</span>
                </td>
                <td>
                  <span className="patient-name">{c.patient}</span>
                </td>
                <td className="muted-text">{c.clinic_name || c.doctor}</td>
                <td>
                  <ToothPills teeth={c.prep_teeth_fdi ?? []} />
                </td>
                <td>
                  <StatusBadge status={c.quality_status} />
                </td>
                <td className="muted-text">{c.due_date}</td>
                <td>
                  <button
                    onClick={(e) => handleDelete(e, c.order_id)}
                    title="Delete case"
                    style={{
                      background: "transparent",
                      border: "1px solid #450a0a",
                      color: "var(--flag)",
                      borderRadius: 5,
                      padding: "3px 8px",
                      fontSize: 13,
                      cursor: "pointer",
                      lineHeight: 1,
                    }}
                  >
                    🗑
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [latestResult, setLatestResult] = useState<any>(null);
  const [cases, setCases] = useState<Case[]>([]);

  useEffect(() => {
    fetch(`${API}/cases`)
      .then((r) => r.json())
      .then(setCases)
      .catch(() => {});
  }, [latestResult]);

  return (
    <>
      <UploadZone onResult={(r) => setLatestResult(r)} />
      {latestResult && <LatestResult result={latestResult} />}
      <div className="gap-section">
        <div className="section-title">Previous Cases ({cases.length})</div>
        <div className="card" style={{ padding: "20px 0 0" }}>
          <div style={{ padding: "0 20px 16px" }}>
            {cases.length === 0 ? (
              <div className="empty-state">
                No cases yet — upload a scan package above.
              </div>
            ) : (
              <CaseTable
                cases={cases}
                onDelete={(id) =>
                  setCases((prev) => prev.filter((c) => c.order_id !== id))
                }
              />
            )}
          </div>
        </div>
      </div>
    </>
  );
}
