"""
processor/api.py
RxWatcher FastAPI processor service.
Accepts iTero zip uploads via web UI or inbox folder,
auto-routes to clinic folders on NAS, processes scan packages,
stores results in SQLite, and serves rendered images and PLY files.

Run:
    uvicorn processor.api:app --reload --port 8000

Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
"""

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
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SCANS_DIR = DATA_DIR / "scans"  # temp extraction for web UI uploads
OUT_DIR = DATA_DIR / "output"  # rendered PNGs + result.json

# IOS base path — clinic folders live here
# Dev:  data/ios_base (local)
# Prod: /volume1/YCLab_ALL/Data/IOS download (NAS)
IOS_BASE = Path(os.environ.get("IOS_BASE_PATH", str(DATA_DIR / "ios_base")))

# Inbox — single drop folder
# Dev:  data/inbox (local)
# Prod: /volume1/YCLab_ALL/Data/IOS download/_inbox (NAS)
INBOX_DIR = Path(os.environ.get("INBOX_PATH", str(DATA_DIR / "inbox")))

for d in (SCANS_DIR, OUT_DIR, IOS_BASE, INBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Import processor ──────────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
from render_scan import process_scan_folder

# ── DB ────────────────────────────────────────────────────────────────────────
from processor.db import (
    init_db,
    upsert_case,
    get_all_cases,
    get_case,
    delete_case,
    get_clinic_mapping,
    save_clinic_mapping,
    get_all_clinic_mappings,
    delete_clinic_mapping,
    normalize_address,
)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="RxWatcher", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _quick_parse_zip(zip_path: Path) -> dict:
    """
    Read the v50 XML from INSIDE a zip without extracting.
    Returns: {order_id, patient, doctor, address, license, scan_date_month, filename_stem}
    """
    ADA_TO_FDI = {
        1: 18,
        2: 17,
        3: 16,
        4: 15,
        5: 14,
        6: 13,
        7: 12,
        8: 11,
        9: 21,
        10: 22,
        11: 23,
        12: 24,
        13: 25,
        14: 26,
        15: 27,
        16: 28,
        17: 38,
        18: 37,
        19: 36,
        20: 35,
        21: 34,
        22: 33,
        23: 32,
        24: 31,
        25: 41,
        26: 42,
        27: 43,
        28: 44,
        29: 45,
        30: 46,
        31: 47,
        32: 48,
    }

    result = {
        "order_id": "",
        "patient": "",
        "doctor": "",
        "address": "",
        "license": "",
        "scan_date_month": "",
        "filename_stem": zip_path.stem,
        "prep_teeth_fdi": [],
    }

    with zipfile.ZipFile(zip_path) as zf:
        # Find the v50 XML inside the zip
        v50_files = [
            n
            for n in zf.namelist()
            if n.endswith("_v50.xml") and not n.startswith("__MACOSX")
        ]
        if not v50_files:
            return result

        with zf.open(v50_files[0]) as xf:
            tree = ET.parse(xf)

        root = tree.getroot()
        rx = root.find("RxInfo")
        if rx is None:
            return result

        result["order_id"] = rx.findtext("OrderID", "").strip()
        result["patient"] = rx.findtext("Patient", "").strip()
        result["doctor"] = rx.findtext("Doctor", "").strip()
        result["address"] = rx.findtext("PracticeShipToAddress", "").strip()
        result["license"] = rx.findtext("DoctorLicense", "").strip()

        # Extract scan date → month folder (e.g. "06/16/2026" → "2026-06")
        export_time = rx.findtext("ExportTime", "").strip()
        if export_time:
            try:
                dt = datetime.strptime(export_time.split()[0], "%m/%d/%Y")
                result["scan_date_month"] = dt.strftime("%Y-%m")
            except Exception:
                result["scan_date_month"] = datetime.now().strftime("%Y-%m")
        else:
            result["scan_date_month"] = datetime.now().strftime("%Y-%m")

        # Prep teeth
        teeth_el = rx.find("Teeth")
        if teeth_el is not None:
            for tooth in teeth_el.findall("Tooth"):
                ada = int(tooth.get("AdaId", 0))
                rt = tooth.get("RestorationType", "")
                if ada and rt != "21":
                    fdi = ADA_TO_FDI.get(ada)
                    if fdi:
                        result["prep_teeth_fdi"].append(fdi)

        # ── Extract practice name from PDF (not available in XML) ─────────
        rx_pdfs = [
            n
            for n in zf.namelist()
            if "iTero_Rx_" in n and n.endswith(".pdf") and not n.startswith("__MACOSX")
        ]
        if rx_pdfs:
            try:
                import pdfplumber

                with zf.open(rx_pdfs[0]) as pf:
                    with pdfplumber.open(io.BytesIO(pf.read())) as pdf:
                        text = pdf.pages[0].extract_text() or ""
                # Practice name is on the line AFTER "Practice:", before the first date (MM/DD/YYYY)
                match = re.search(r"Practice:.*?\n(.+?)\s+\d{2}/\d{2}/\d{4}", text)
                if match:
                    result["practice_name"] = match.group(1).strip()
            except Exception:
                pass

    return result


def _format_patient_name(patient_raw: str) -> str:
    """
    Convert 'LastName, FirstName' → 'FirstName LastName' for folder naming.
    """
    if "," in patient_raw:
        parts = [p.strip() for p in patient_raw.split(",", 1)]
        return f"{parts[1]} {parts[0]}" if len(parts) == 2 else patient_raw
    return patient_raw


def _extract_zip_to(zip_path: Path, target_dir: Path) -> Path:
    """
    Extract a zip to target_dir, stripping Mac junk.
    Returns the path to the actual scan folder (handling nested structure).
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = [
            m
            for m in zf.infolist()
            if not m.filename.startswith("__MACOSX")
            and not m.filename.startswith(".")
            and "/.DS_Store" not in m.filename
        ]
        zf.extractall(target_dir, members=[m.filename for m in members])

    # Resolve: zip may contain a subfolder or be flat
    subdirs = [
        d
        for d in target_dir.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_"))
    ]

    if len(subdirs) == 1:
        return subdirs[0]
    elif len(subdirs) == 0:
        return target_dir
    else:
        return next(
            (d for d in subdirs if any(d.glob("*_v50.xml"))),
            max(subdirs, key=lambda d: d.stat().st_mtime),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Upload (web UI)
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/process")
async def process(file: UploadFile = File(...)):
    """Accept an iTero zip via web UI, extract to temp dir, process."""
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip files are accepted")

    zip_path = DATA_DIR / file.filename
    with open(zip_path, "wb") as f:
        f.write(await file.read())

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    extract_dir = SCANS_DIR / f"{ts}_{Path(file.filename).stem}"

    try:
        scan_folder = _extract_zip_to(zip_path, extract_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(extract_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        raise HTTPException(400, "Invalid zip file")
    finally:
        zip_path.unlink(missing_ok=True)

    if not any(scan_folder.glob("*.ply")) and not any(scan_folder.glob("*.xml")):
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise HTTPException(400, "Not an iTero scan package")

    try:
        result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    result["scan_folder"] = str(scan_folder)
    upsert_case(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Inbox (drop folder → auto-route to NAS clinic folder)
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/inbox/process")
async def inbox_process(request: Request):
    """
    Process a zip from the inbox.
    1. Quick-parse the zip to get order info + clinic address
    2. Look up clinic mapping by address
    3. If found: extract to NAS clinic folder, process, return result
    4. If not found: return needs_clinic_link response with parsed info

    Body: { "zip_path": "/path/to/inbox/iTero_Export_XXXXX.zip" }
    OR upload the file directly.
    """
    content_type = request.headers.get("content-type", "")

    # Accept either a JSON body with zip_path or a file upload
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(400, "No file provided")
        zip_path = INBOX_DIR / file.filename
        with open(zip_path, "wb") as f:
            f.write(await file.read())
    elif "application/json" in content_type:
        body = await request.json()
        zip_path = Path(body.get("zip_path", ""))
    else:
        raise HTTPException(400, "Send JSON with zip_path or multipart file upload")

    if not zip_path.exists() or not zip_path.suffix == ".zip":
        raise HTTPException(400, f"Zip not found: {zip_path}")

    # ── Quick parse ───────────────────────────────────────────────────────────
    try:
        info = _quick_parse_zip(zip_path)
    except Exception as e:
        raise HTTPException(400, f"Failed to read zip: {e}")

    if not info["order_id"]:
        raise HTTPException(400, "Could not find order ID in zip (no v50 XML?)")

    # ── Look up clinic ────────────────────────────────────────────────────────
    mapping = get_clinic_mapping(info["address"]) if info["address"] else None

    if not mapping:
        # Return parsed info so the UI can show the clinic picker
        return {
            "status": "needs_clinic_link",
            "order_info": info,
            "zip_path": str(zip_path),
            "address_key": normalize_address(info["address"])
            if info["address"]
            else "",
        }

    # ── Route to NAS folder ───────────────────────────────────────────────────
    clinic_folder = mapping["nas_folder"]
    month_folder = info["scan_date_month"] or datetime.now().strftime("%Y-%m")
    patient_name = _format_patient_name(info["patient"])

    # Build destination: IOS_BASE / Clinic / 2026-06 / iTero_Export_XXXXX_Patient Name
    dest_parent = IOS_BASE / clinic_folder / month_folder
    scan_folder_name = (
        f"{info['filename_stem']}_{patient_name}"
        if patient_name
        else info["filename_stem"]
    )
    dest_folder = dest_parent / scan_folder_name

    # Extract
    try:
        scan_folder = _extract_zip_to(zip_path, dest_folder)
    except Exception as e:
        raise HTTPException(500, f"Extraction failed: {e}")

    # Delete the zip from inbox
    zip_path.unlink(missing_ok=True)

    # Sanity check
    if not any(scan_folder.glob("*.ply")) and not any(scan_folder.glob("*.xml")):
        shutil.rmtree(dest_folder, ignore_errors=True)
        raise HTTPException(400, "Not a valid iTero scan package")

    # ── Process ───────────────────────────────────────────────────────────────
    try:
        result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    result['scan_folder']   = str(scan_folder)
    result['clinic_name']   = clinic_folder
    result['practice_name'] = mapping.get('practice_name', '')
    upsert_case(result)

    return {
        "status": "processed",
        "clinic": clinic_folder,
        "month": month_folder,
        "scan_folder": str(scan_folder),
        "result": result,
    }


@app.post("/inbox/link-and-process")
async def inbox_link_and_process(request: Request):
    """
    Called after user selects a clinic folder for an unrecognized clinic.
    Saves the mapping, then processes the zip.

    Body: {
        "zip_path": "/path/to/inbox/file.zip",
        "nas_folder": "Wittmeir Dental(82)",
        "address": "8104-82 Ave NW...",
        "practice_name": "Wittmeir Dental"
    }
    """
    body = await request.json()
    zip_path = Path(body.get("zip_path", ""))
    nas_folder = body.get("nas_folder", "")
    address = body.get("address", "")
    practice = body.get("practice_name", "")
    license_num = body.get("doctor_license", "")

    if not zip_path.exists():
        raise HTTPException(400, f"Zip not found: {zip_path}")
    if not nas_folder:
        raise HTTPException(400, "nas_folder is required")
    if not address:
        raise HTTPException(400, "address is required")

    # Save the mapping for future auto-routing
    save_clinic_mapping(address, nas_folder, practice, license_num)

    # Now process via the inbox flow (mapping will be found this time)
    info = _quick_parse_zip(zip_path)
    mapping = get_clinic_mapping(address)

    clinic_folder = mapping["nas_folder"]
    month_folder = info.get("scan_date_month") or datetime.now().strftime("%Y-%m")
    patient_name = _format_patient_name(info.get("patient", ""))

    dest_parent = IOS_BASE / clinic_folder / month_folder
    scan_folder_name = (
        f"{info['filename_stem']}_{patient_name}"
        if patient_name
        else info["filename_stem"]
    )
    dest_folder = dest_parent / scan_folder_name

    try:
        scan_folder = _extract_zip_to(zip_path, dest_folder)
    except Exception as e:
        raise HTTPException(500, f"Extraction failed: {e}")

    zip_path.unlink(missing_ok=True)

    if not any(scan_folder.glob("*.ply")) and not any(scan_folder.glob("*.xml")):
        shutil.rmtree(dest_folder, ignore_errors=True)
        raise HTTPException(400, "Not a valid iTero scan package")

    try:
        result = process_scan_folder(str(scan_folder), output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    result['scan_folder']   = str(scan_folder)
    result['clinic_name']   = clinic_folder
    result['practice_name'] = body.get('practice_name', '')
    upsert_case(result)

    return {
        "status": "processed",
        "clinic": clinic_folder,
        "month": month_folder,
        "scan_folder": str(scan_folder),
        "mapping": {"address": address, "nas_folder": nas_folder},
        "result": result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Process existing folder (for n8n)
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/process-folder")
async def process_folder_endpoint(request: Request):
    """Process an already-extracted scan folder on disk."""
    body = await request.json()
    folder = body.get("folder", "")

    if not folder or not Path(folder).is_dir():
        raise HTTPException(400, f"Invalid or missing folder: {folder}")

    folder_path = Path(folder)
    if not any(folder_path.glob("*.ply")) and not any(folder_path.glob("*.xml")):
        raise HTTPException(400, "Folder does not appear to be an iTero scan package")

    try:
        result = process_scan_folder(folder, output_base=str(OUT_DIR))
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    result["scan_folder"] = folder

    # Extract clinic name from path if it's under IOS_BASE
    try:
        rel = Path(folder).relative_to(IOS_BASE)
        parts = rel.parts
        if len(parts) >= 2:
            result["clinic_name"] = parts[0]
    except ValueError:
        pass

    upsert_case(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Clinic mappings + NAS folder listing
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/clinics/folders")
def list_clinic_folders():
    """List all clinic folder names under IOS_BASE (for the picker UI)."""
    if not IOS_BASE.exists():
        return []
    folders = sorted(
        [
            d.name
            for d in IOS_BASE.iterdir()
            if d.is_dir() and not d.name.startswith((".", "_"))
        ]
    )
    return folders


@app.get("/clinics/mappings")
def list_clinic_mappings():
    """Return all saved clinic mappings."""
    return get_all_clinic_mappings()


@app.post("/clinics/mappings")
async def create_clinic_mapping(request: Request):
    """Create or update a clinic mapping."""
    body = await request.json()
    result = save_clinic_mapping(
        address=body.get("address", ""),
        nas_folder=body.get("nas_folder", ""),
        practice_name=body.get("practice_name", ""),
        doctor_license=body.get("doctor_license", ""),
    )
    return result


@app.delete("/clinics/mappings/{mapping_id}")
def delete_mapping(mapping_id: int):
    """Delete a clinic mapping."""
    delete_clinic_mapping(mapping_id)
    return {"deleted": mapping_id}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: Cases
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/cases")
def list_cases():
    return get_all_cases()


@app.get("/cases/{order_id}")
def get_case_detail(order_id: str):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f"Case {order_id} not found")
    return case


@app.delete("/cases/{order_id}")
def delete_case_endpoint(order_id: str):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, f"Case {order_id} not found")
    scan_dir = case.get("scan_folder", "")
    if scan_dir:
        scan_path = Path(scan_dir)
        parent = scan_path.parent
        target = (
            parent
            if parent != SCANS_DIR and parent.is_relative_to(SCANS_DIR)
            else scan_path
        )
        shutil.rmtree(target, ignore_errors=True)
    out_path = OUT_DIR / order_id
    if out_path.exists():
        shutil.rmtree(out_path, ignore_errors=True)
    delete_case(order_id)
    return {"deleted": order_id}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints: File serving
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/images/{order_id}/{filename}")
def serve_image(order_id: str, filename: str):
    path = OUT_DIR / order_id / filename
    if not path.exists() or path.suffix != ".png":
        raise HTTPException(404, "Image not found")
    return FileResponse(str(path), media_type="image/png")


@app.api_route("/ply/{order_id}", methods=["GET", "HEAD"])
def serve_ply(order_id: str, filename: str, request: Request):
    case = get_case(order_id)
    if not case:
        raise HTTPException(404, "Case not found")
    scan_dir = case.get("scan_folder", "")
    if not scan_dir:
        raise HTTPException(
            409, "PLY files unavailable — re-upload the zip to enable 3D view."
        )
    path = Path(scan_dir) / filename
    if not path.exists() or path.suffix.lower() != ".ply":
        raise HTTPException(404, f"PLY file not found: {filename}")
    if request.method == "HEAD":
        return Response(
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(path.stat().st_size),
            }
        )
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "ios_base": str(IOS_BASE), "inbox": str(INBOX_DIR)}
