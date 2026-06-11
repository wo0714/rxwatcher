"""
processor/api.py
RxWatcher FastAPI processor service.
Accepts iTero zip uploads, extracts and processes scan packages,
stores results in SQLite, and serves rendered images and PLY files
to the Next.js frontend.

Run:
    uvicorn processor.api:app --reload --port 8000

Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
"""

import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / 'data'
SCANS_DIR = DATA_DIR / 'scans'
OUT_DIR   = DATA_DIR / 'output'

for d in (SCANS_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Import processor ──────────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
from render_scan import process_scan_folder

# ── DB ────────────────────────────────────────────────────────────────────────
from processor.db import init_db, upsert_case, get_all_cases, get_case, delete_case

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title='RxWatcher', version='1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3010'],
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.on_event('startup')
def startup():
    init_db()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post('/process')
async def process(file: UploadFile = File(...)):
    """Accept an iTero zip, extract, process, save to DB and return result."""
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, 'Only .zip files are accepted')

    zip_path = DATA_DIR / file.filename
    with open(zip_path, 'wb') as f:
        f.write(await file.read())

    extract_dir = SCANS_DIR / f"{int(time.time())}_{Path(file.filename).stem}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.infolist()
                       if not m.filename.startswith('__MACOSX')
                       and not m.filename.startswith('.')
                       and '/.DS_Store' not in m.filename]
            zf.extractall(extract_dir, members=[m.filename for m in members])
    except zipfile.BadZipFile:
        shutil.rmtree(extract_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        raise HTTPException(400, 'Invalid zip file')
    finally:
        zip_path.unlink(missing_ok=True)

    subdirs = [d for d in extract_dir.iterdir()
               if d.is_dir() and not d.name.startswith(('.', '_'))]

    if len(subdirs) == 1:
        scan_folder = subdirs[0]
    elif len(subdirs) == 0:
        scan_folder = extract_dir
    else:
        scan_folder = next(
            (d for d in subdirs if any(d.glob('*_v50.xml'))),
            max(subdirs, key=lambda d: d.stat().st_mtime)
        )

    if not any(scan_folder.glob('*.ply')) and not any(scan_folder.glob('*.xml')):
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise HTTPException(400, 'Zip does not appear to be an iTero scan package')

    try:
        result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f'Processing failed: {e}')

    result['scan_folder'] = str(scan_folder)
    upsert_case(result)
    return result


@app.get('/cases')
def list_cases():
    """Return all processed cases, newest first."""
    return get_all_cases()


@app.get('/cases/{order_id}')
def get_case_detail(order_id: str):
    """Return full result for a single case."""
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f'Case {order_id} not found')
    return case


@app.delete('/cases/{order_id}')
def delete_case_endpoint(order_id: str):
    """Delete a case from DB and remove its scan and output folders."""
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f'Case {order_id} not found')

    # Remove scan folder (extracted PLY/XML files)
    scan_dir = case.get('scan_folder', '')
    if scan_dir:
        # Walk up one level — scan_folder points to the inner package dir,
        # the parent is the timestamped extract dir we created on upload
        scan_path  = Path(scan_dir)
        parent     = scan_path.parent
        # Remove the extract dir if it lives inside SCANS_DIR
        target = parent if parent != SCANS_DIR and parent.is_relative_to(SCANS_DIR) else scan_path
        shutil.rmtree(target, ignore_errors=True)

    # Remove output folder (rendered PNGs + result.json)
    out_path = OUT_DIR / order_id
    if out_path.exists():
        shutil.rmtree(out_path, ignore_errors=True)

    delete_case(order_id)
    return {'deleted': order_id}


@app.get('/images/{order_id}/{filename}')
def serve_image(order_id: str, filename: str):
    """Serve a rendered PNG from the output directory."""
    path = OUT_DIR / order_id / filename
    if not path.exists() or path.suffix != '.png':
        raise HTTPException(404, 'Image not found')
    return FileResponse(str(path), media_type='image/png')


@app.api_route('/ply/{order_id}', methods=['GET', 'HEAD'])
def serve_ply(order_id: str, filename: str, request: Request):
    """Serve an original PLY file. filename passed as query param to avoid # URL issues."""
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


@app.get('/health')
def health():
    return {'status': 'ok'}