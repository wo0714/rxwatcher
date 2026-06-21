"""
processor/api.py
RxWatcher FastAPI processor service.
Accepts iTero zip uploads via web UI or inbox folder,
auto-routes to clinic folders on NAS, processes scan packages,
stores results in SQLite, and serves rendered images and PLY files.

Includes a background inbox watcher: polls INBOX_DIR for new zips and
auto-processes them (unpack → rename with patient name → delete zip →
analyze) without any manual upload step. This is the "drop zip and walk
away" automation — no n8n required, runs inside this app.

Run:
    uvicorn processor.api:app --reload --port 8000

Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
"""

import asyncio
import io
import json
import os
import re
import shutil
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / 'data'
SCANS_DIR = DATA_DIR / 'scans'                      # temp extraction for web UI uploads
OUT_DIR   = DATA_DIR / 'output'                      # rendered PNGs + result.json

# IOS base path — clinic folders live here
# Dev:  data/ios_base (local)
# Prod: /volume1/YCLab_ALL/Data/IOS download (NAS)
IOS_BASE = Path(os.environ.get('IOS_BASE_PATH', str(DATA_DIR / 'ios_base')))

# Inbox — single drop folder. This is what the background watcher monitors.
# Dev:  data/inbox (local)
# Prod: /volume1/YCLab_ALL/Data/IOS download/_inbox (NAS)
INBOX_DIR = Path(os.environ.get('INBOX_PATH', str(DATA_DIR / 'inbox')))

# Inbox watcher config
INBOX_POLL_SECONDS   = int(os.environ.get('INBOX_POLL_SECONDS', '10'))
INBOX_STABLE_CHECKS  = 2      # consecutive polls with unchanged file size before processing
INBOX_WATCHER_ENABLED = os.environ.get('INBOX_WATCHER_ENABLED', 'true').lower() != 'false'

for d in (SCANS_DIR, OUT_DIR, IOS_BASE, INBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Import processor ──────────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
from render_scan import process_scan_folder

# ── DB ────────────────────────────────────────────────────────────────────────
from processor.db import (
    init_db, upsert_case, get_all_cases, get_case, delete_case,
    get_clinic_mapping, save_clinic_mapping, get_all_clinic_mappings,
    delete_clinic_mapping, normalize_address,
)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title='RxWatcher', version='1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
async def startup():
    init_db()
    if INBOX_WATCHER_ENABLED:
        asyncio.create_task(_inbox_watcher_loop())
    else:
        print('📂 Inbox watcher disabled (INBOX_WATCHER_ENABLED=false)')


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: parsing + extraction
# ─────────────────────────────────────────────────────────────────────────────

def _quick_parse_zip(zip_path: Path) -> dict:
    """
    Read the v50 XML from INSIDE a zip without extracting.
    Returns: {order_id, patient, doctor, address, license, scan_date_month,
              filename_stem, prep_teeth_fdi, practice_name}
    """
    ADA_TO_FDI = {
         1: 18,  2: 17,  3: 16,  4: 15,  5: 14,  6: 13,  7: 12,  8: 11,
         9: 21, 10: 22, 11: 23, 12: 24, 13: 25, 14: 26, 15: 27, 16: 28,
        17: 38, 18: 37, 19: 36, 20: 35, 21: 34, 22: 33, 23: 32, 24: 31,
        25: 41, 26: 42, 27: 43, 28: 44, 29: 45, 30: 46, 31: 47, 32: 48,
    }

    result = {
        'order_id': '', 'patient': '', 'doctor': '', 'address': '',
        'license': '', 'scan_date_month': '', 'filename_stem': zip_path.stem,
        'prep_teeth_fdi': [], 'practice_name': '',
    }

    with zipfile.ZipFile(zip_path) as zf:
        # Find the v50 XML inside the zip
        v50_files = [n for n in zf.namelist()
                     if n.endswith('_v50.xml') and not n.startswith('__MACOSX')]
        if not v50_files:
            return result

        with zf.open(v50_files[0]) as xf:
            tree = ET.parse(xf)

        root = tree.getroot()
        rx   = root.find('RxInfo')
        if rx is None:
            return result

        result['order_id'] = rx.findtext('OrderID', '').strip()
        result['patient']  = rx.findtext('Patient', '').strip()
        result['doctor']   = rx.findtext('Doctor', '').strip()
        result['address']  = rx.findtext('PracticeShipToAddress', '').strip()
        result['license']  = rx.findtext('DoctorLicense', '').strip()

        # Extract scan date → month folder (e.g. "06/16/2026" → "2026-06")
        export_time = rx.findtext('ExportTime', '').strip()
        if export_time:
            try:
                dt = datetime.strptime(export_time.split()[0], '%m/%d/%Y')
                result['scan_date_month'] = dt.strftime('%Y-%m')
            except Exception:
                result['scan_date_month'] = datetime.now().strftime('%Y-%m')
        else:
            result['scan_date_month'] = datetime.now().strftime('%Y-%m')

        # Prep teeth
        teeth_el = rx.find('Teeth')
        if teeth_el is not None:
            for tooth in teeth_el.findall('Tooth'):
                ada = int(tooth.get('AdaId', 0))
                rt  = tooth.get('RestorationType', '')
                if ada and rt != '21':
                    fdi = ADA_TO_FDI.get(ada)
                    if fdi:
                        result['prep_teeth_fdi'].append(fdi)

        # ── Practice name from PDF (not available in XML) ──────────────────────
        rx_pdfs = [n for n in zf.namelist()
                   if 'iTero_Rx_' in n and n.endswith('.pdf')
                   and not n.startswith('__MACOSX')]
        if rx_pdfs:
            try:
                import pdfplumber
                with zf.open(rx_pdfs[0]) as pf:
                    with pdfplumber.open(io.BytesIO(pf.read())) as pdf:
                        text = pdf.pages[0].extract_text() or ''
                # Practice name sits on the line AFTER "Practice:",
                # before the first date (MM/DD/YYYY) — pdfplumber puts the
                # field labels and values on separate lines.
                match = re.search(r'Practice:.*?\n(.+?)\s+\d{2}/\d{2}/\d{4}', text)
                if match:
                    result['practice_name'] = match.group(1).strip()
            except Exception:
                pass

    return result


def _format_patient_name(patient_raw: str) -> str:
    """Convert 'LastName, FirstName' → 'FirstName LastName' for folder naming."""
    if ',' in patient_raw:
        parts = [p.strip() for p in patient_raw.split(',', 1)]
        return f"{parts[1]} {parts[0]}" if len(parts) == 2 else patient_raw
    return patient_raw


def _extract_zip_to(zip_path: Path, target_dir: Path) -> Path:
    """
    Extract a zip to target_dir, stripping Mac junk.
    Returns the path to the actual scan folder (handling nested structure).
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist()
                   if not m.filename.startswith('__MACOSX')
                   and not m.filename.startswith('.')
                   and '/.DS_Store' not in m.filename]
        zf.extractall(target_dir, members=[m.filename for m in members])

    # Resolve: zip may contain a subfolder or be flat
    subdirs = [d for d in target_dir.iterdir()
               if d.is_dir() and not d.name.startswith(('.', '_'))]

    if len(subdirs) == 1:
        return subdirs[0]
    elif len(subdirs) == 0:
        return target_dir
    else:
        return next(
            (d for d in subdirs if any(d.glob('*_v50.xml'))),
            max(subdirs, key=lambda d: d.stat().st_mtime)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Core inbox processing logic (shared by HTTP endpoint + background watcher)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_and_process_zip(zip_path: Path, clinic_folder: str, info: dict,
                              practice_name: str = '') -> dict:
    """
    Given a zip, a resolved clinic folder name, and pre-parsed order info:
    extract to IOS_BASE/clinic/month/package_PatientName, delete the zip,
    run the scan processor, save to DB. Returns the result dict.

    Raises on failure (caller decides how to surface the error).
    """
    month_folder = info.get('scan_date_month') or datetime.now().strftime('%Y-%m')
    patient_name = _format_patient_name(info.get('patient', ''))

    dest_parent = IOS_BASE / clinic_folder / month_folder
    scan_folder_name = f"{info['filename_stem']}_{patient_name}" if patient_name else info['filename_stem']
    dest_folder = dest_parent / scan_folder_name

    scan_folder = _extract_zip_to(zip_path, dest_folder)

    # Delete the zip — it's now extracted on the NAS, no longer needed
    zip_path.unlink(missing_ok=True)

    if not any(scan_folder.glob('*.ply')) and not any(scan_folder.glob('*.xml')):
        shutil.rmtree(dest_folder, ignore_errors=True)
        raise ValueError('Not a valid iTero scan package (no .ply or .xml found)')

    result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    result['scan_folder']   = str(scan_folder)
    result['clinic_name']   = clinic_folder
    result['clinic_path']   = str(dest_parent)
    result['practice_name'] = practice_name
    upsert_case(result)

    return {
        'status':      'processed',
        'clinic':      clinic_folder,
        'month':       month_folder,
        'scan_folder': str(scan_folder),
        'result':      result,
    }


def _process_inbox_zip_core(zip_path: Path) -> dict:
    """
    Full inbox processing pipeline for a single zip, synchronous.
    Used by both the /inbox/process HTTP endpoint and the background watcher.

    Returns a dict with one of:
      {'status': 'processed', 'clinic', 'month', 'scan_folder', 'result'}
      {'status': 'needs_clinic_link', 'order_info', 'zip_path', 'address_key'}
      {'status': 'error', 'error', 'zip_path'}

    Never raises — errors are captured and returned so the background
    watcher loop can log them without crashing.
    """
    try:
        if not zip_path.exists() or zip_path.suffix != '.zip':
            return {'status': 'error', 'error': f'Zip not found: {zip_path}', 'zip_path': str(zip_path)}

        info = _quick_parse_zip(zip_path)
        if not info['order_id']:
            return {'status': 'error', 'error': 'Could not find order ID (no v50 XML?)',
                     'zip_path': str(zip_path)}

        mapping = get_clinic_mapping(info['address']) if info['address'] else None

        if not mapping:
            return {
                'status':      'needs_clinic_link',
                'order_info':  info,
                'zip_path':    str(zip_path),
                'address_key': normalize_address(info['address']) if info['address'] else '',
            }

        # Prefer the practice name freshly parsed from THIS zip's own PDF —
        # only fall back to whatever was stored at link-time if this one
        # didn't parse (e.g. the mapping was created before a practice name
        # was captured, or this particular PDF doesn't match the regex).
        practice_name = info.get('practice_name') or mapping.get('practice_name', '')
        return _extract_and_process_zip(
            zip_path, mapping['nas_folder'], info,
            practice_name=practice_name,
        )

    except Exception as e:
        return {'status': 'error', 'error': str(e), 'zip_path': str(zip_path)}


# ─────────────────────────────────────────────────────────────────────────────
# Background inbox watcher
# ─────────────────────────────────────────────────────────────────────────────
#
# Polls INBOX_DIR every INBOX_POLL_SECONDS. A file must report the same size
# across INBOX_STABLE_CHECKS consecutive polls before it's considered fully
# copied (avoids processing a zip that's still being written over SMB).
#
# Known clinics process automatically: unpack → rename with patient name →
# delete zip → analyze. Unrecognized clinics are left in the inbox untouched
# and logged once — link them via the web UI's clinic picker (drag the same
# zip onto the upload zone, or wait for a future "pending review" panel).

_inbox_seen_sizes: dict = {}
_inbox_reported_pending: set = set()


async def _inbox_watcher_loop():
    print(f'📂 Inbox watcher started — watching {INBOX_DIR} every {INBOX_POLL_SECONDS}s')

    while True:
        try:
            for zip_path in sorted(INBOX_DIR.glob('*.zip')):
                key = str(zip_path)
                try:
                    size = zip_path.stat().st_size
                except FileNotFoundError:
                    continue

                prev_size, stable_count = _inbox_seen_sizes.get(key, (None, 0))
                stable_count = stable_count + 1 if prev_size == size else 0
                _inbox_seen_sizes[key] = (size, stable_count)

                if stable_count < INBOX_STABLE_CHECKS:
                    continue   # still being copied — wait for size to settle

                # NOTE: must call directly, NOT via run_in_executor.
                # vedo/VTK's Cocoa backend on macOS requires window creation
                # on the main thread — running this in a worker thread crashes
                # the whole process (NSInternalInconsistencyException). This
                # blocks the event loop for the duration of rendering (30-60s),
                # same as the original /process endpoint already did.
                result = _process_inbox_zip_core(zip_path)
                status = result.get('status')

                if status == 'processed':
                    print(f"  ✅ Auto-processed {zip_path.name} → "
                          f"{result.get('clinic')}/{result.get('month')}")
                    _inbox_seen_sizes.pop(key, None)
                    _inbox_reported_pending.discard(key)

                elif status == 'needs_clinic_link':
                    if key not in _inbox_reported_pending:
                        info = result.get('order_info', {})
                        print(f"  ⚠️  Unrecognized clinic for {zip_path.name} — "
                              f"Practice: {info.get('practice_name') or '?'}, "
                              f"Address: {info.get('address') or '?'}. "
                              f"Link it via the web UI (drop the same zip there) to process.")
                        _inbox_reported_pending.add(key)
                    # leave the zip in place — will retry each poll but only log once

                else:
                    print(f"  ❌ Failed to process {zip_path.name}: {result.get('error')}")

        except Exception as loop_err:
            print(f'  ⚠️  Inbox watcher loop error: {loop_err}')

        await asyncio.sleep(INBOX_POLL_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Upload (web UI, ad-hoc zip not necessarily clinic-routed)
# ─────────────────────────────────────────────────────────────────────────────

@app.post('/process')
async def process(file: UploadFile = File(...)):
    """Accept an iTero zip via web UI, extract to temp dir, process."""
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, 'Only .zip files are accepted')

    zip_path = DATA_DIR / file.filename
    with open(zip_path, 'wb') as f:
        f.write(await file.read())

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    extract_dir = SCANS_DIR / f"{ts}_{Path(file.filename).stem}"

    try:
        scan_folder = _extract_zip_to(zip_path, extract_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(extract_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        raise HTTPException(400, 'Invalid zip file')
    finally:
        zip_path.unlink(missing_ok=True)

    if not any(scan_folder.glob('*.ply')) and not any(scan_folder.glob('*.xml')):
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise HTTPException(400, 'Not an iTero scan package')

    try:
        result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f'Processing failed: {e}')

    result['scan_folder'] = str(scan_folder)
    upsert_case(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Inbox (manual trigger — same logic the background watcher uses)
# ─────────────────────────────────────────────────────────────────────────────

@app.post('/inbox/process')
async def inbox_process(request: Request):
    """
    Process a zip from the inbox on demand (e.g. dropped on the web UI).
    The background watcher calls the same core function automatically —
    this endpoint exists for manual/immediate processing and for the
    clinic-picker flow when a new clinic is detected.

    Body: { "zip_path": "/path/to/inbox/iTero_Export_XXXXX.zip" }
    OR upload the file directly (multipart).
    """
    content_type = request.headers.get('content-type', '')

    if 'multipart/form-data' in content_type:
        form = await request.form()
        file = form.get('file')
        if not file:
            raise HTTPException(400, 'No file provided')
        zip_path = INBOX_DIR / file.filename
        with open(zip_path, 'wb') as f:
            f.write(await file.read())
    elif 'application/json' in content_type:
        body = await request.json()
        zip_path = Path(body.get('zip_path', ''))
    else:
        raise HTTPException(400, 'Send JSON with zip_path or multipart file upload')

    # Direct call — VTK/Cocoa rendering must run on the main thread (macOS).
    result = _process_inbox_zip_core(zip_path)

    if result['status'] == 'error':
        raise HTTPException(400, result['error'])

    return result


@app.post('/inbox/link-and-process')
async def inbox_link_and_process(request: Request):
    """
    Called after the user selects a clinic folder for an unrecognized clinic.
    Saves the mapping, then processes the zip via the same shared helper
    the background watcher uses.

    Body: {
        "zip_path": "/path/to/inbox/file.zip",
        "nas_folder": "Wittmeir Dental(82)",
        "address": "8104-82 Ave NW...",
        "practice_name": "Wittmeir Dental"
    }
    """
    body = await request.json()
    zip_path    = Path(body.get('zip_path', ''))
    nas_folder  = body.get('nas_folder', '')
    address     = body.get('address', '')
    practice    = body.get('practice_name', '')
    license_num = body.get('doctor_license', '')

    if not zip_path.exists():
        raise HTTPException(400, f'Zip not found: {zip_path}')
    if not nas_folder:
        raise HTTPException(400, 'nas_folder is required')
    if not address:
        raise HTTPException(400, 'address is required')

    save_clinic_mapping(address, nas_folder, practice, license_num)
    info = _quick_parse_zip(zip_path)

    # Direct call — VTK/Cocoa rendering must run on the main thread (macOS).
    try:
        result = _extract_and_process_zip(zip_path, nas_folder, info, practice)
    except Exception as e:
        raise HTTPException(500, f'Processing failed: {e}')

    result['mapping'] = {'address': address, 'nas_folder': nas_folder}
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Process existing folder (for external tools / n8n, if ever used)
# ─────────────────────────────────────────────────────────────────────────────

@app.post('/process-folder')
async def process_folder_endpoint(request: Request):
    """Process an already-extracted scan folder on disk."""
    body = await request.json()
    folder = body.get('folder', '')

    if not folder or not Path(folder).is_dir():
        raise HTTPException(400, f'Invalid or missing folder: {folder}')

    folder_path = Path(folder)
    if not any(folder_path.glob('*.ply')) and not any(folder_path.glob('*.xml')):
        raise HTTPException(400, 'Folder does not appear to be an iTero scan package')

    try:
        result = process_scan_folder(folder, output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f'Processing failed: {e}')

    result['scan_folder'] = folder

    try:
        rel = Path(folder).relative_to(IOS_BASE)
        parts = rel.parts
        if len(parts) >= 2:
            result['clinic_name'] = parts[0]
    except ValueError:
        pass

    upsert_case(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Clinic mappings + NAS folder listing
# ─────────────────────────────────────────────────────────────────────────────

@app.get('/clinics/folders')
def list_clinic_folders():
    """List all clinic folder names under IOS_BASE (for the picker UI)."""
    if not IOS_BASE.exists():
        return []
    folders = sorted([
        d.name for d in IOS_BASE.iterdir()
        if d.is_dir() and not d.name.startswith(('.', '_'))
    ])
    return folders


@app.get('/clinics/mappings')
def list_clinic_mappings():
    """Return all saved clinic mappings."""
    return get_all_clinic_mappings()


@app.post('/clinics/mappings')
async def create_clinic_mapping(request: Request):
    """Create or update a clinic mapping."""
    body = await request.json()
    result = save_clinic_mapping(
        address=body.get('address', ''),
        nas_folder=body.get('nas_folder', ''),
        practice_name=body.get('practice_name', ''),
        doctor_license=body.get('doctor_license', ''),
    )
    return result


@app.delete('/clinics/mappings/{mapping_id}')
def delete_mapping(mapping_id: int):
    """Delete a clinic mapping."""
    delete_clinic_mapping(mapping_id)
    return {'deleted': mapping_id}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Cases
# ─────────────────────────────────────────────────────────────────────────────

@app.get('/cases')
def list_cases():
    return get_all_cases()


@app.get('/cases/{order_id}')
def get_case_detail(order_id: str):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f'Case {order_id} not found')
    return case


@app.delete('/cases/{order_id}')
def delete_case_endpoint(order_id: str):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f'Case {order_id} not found')
    scan_dir = case.get('scan_folder', '')
    if scan_dir:
        scan_path = Path(scan_dir)
        parent    = scan_path.parent
        target = parent if parent != SCANS_DIR and parent.is_relative_to(SCANS_DIR) else scan_path
        shutil.rmtree(target, ignore_errors=True)
    out_path = OUT_DIR / order_id
    if out_path.exists():
        shutil.rmtree(out_path, ignore_errors=True)
    delete_case(order_id)
    return {'deleted': order_id}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: File serving
# ─────────────────────────────────────────────────────────────────────────────

@app.get('/images/{order_id}/{filename}')
def serve_image(order_id: str, filename: str):
    path = OUT_DIR / order_id / filename
    if not path.exists() or path.suffix != '.png':
        raise HTTPException(404, 'Image not found')
    return FileResponse(str(path), media_type='image/png')


@app.api_route('/ply/{order_id}', methods=['GET', 'HEAD'])
def serve_ply(order_id: str, filename: str, request: Request):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, 'Case not found')
    scan_dir = case.get('scan_folder', '')
    if not scan_dir:
        raise HTTPException(409, 'PLY files unavailable — re-upload the zip to enable 3D view.')
    path = Path(scan_dir) / filename
    if not path.exists() or path.suffix.lower() != '.ply':
        raise HTTPException(404, f'PLY file not found: {filename}')
    if request.method == 'HEAD':
        return Response(headers={'Content-Type': 'application/octet-stream',
                                 'Content-Length': str(path.stat().st_size)})
    return FileResponse(str(path), media_type='application/octet-stream',
                        headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/inbox/status')
def inbox_status():
    """Diagnostics: see what the watcher currently sees in the inbox."""
    pending = sorted(INBOX_DIR.glob('*.zip'))
    return {
        'inbox_dir':       str(INBOX_DIR),
        'watcher_enabled': INBOX_WATCHER_ENABLED,
        'poll_seconds':    INBOX_POLL_SECONDS,
        'files_in_inbox':  [p.name for p in pending],
        'needs_clinic_link': [
            Path(k).name for k in _inbox_reported_pending if Path(k).exists()
        ],
    }


@app.get('/health')
def health():
    return {'status': 'ok', 'ios_base': str(IOS_BASE), 'inbox': str(INBOX_DIR)}