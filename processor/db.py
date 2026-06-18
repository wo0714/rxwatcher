"""
processor/db.py
RxWatcher SQLite database layer.
Handles case storage, clinic mappings, and retrieval.
No ORM — intentionally lightweight for a local-first application.

Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'rxwatcher.db'


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.execute('''
            CREATE TABLE IF NOT EXISTS cases (
                order_id        TEXT PRIMARY KEY,
                patient         TEXT,
                doctor          TEXT,
                clinic_address  TEXT,
                clinic_name     TEXT,
                procedure       TEXT,
                prep_teeth_fdi  TEXT,
                bridge_region   TEXT,
                prep_jaw        TEXT,
                due_date        TEXT,
                export_time     TEXT,
                notes           TEXT,
                quality_status  TEXT,
                quality_flags   TEXT,
                output_folder   TEXT,
                scan_folder     TEXT,
                all_views_img   TEXT,
                processed_at    TEXT,
                raw_result      TEXT
            )
        ''')

        con.execute('''
            CREATE TABLE IF NOT EXISTS clinic_mappings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                address_key     TEXT UNIQUE NOT NULL,
                nas_folder      TEXT NOT NULL,
                practice_name   TEXT,
                doctor_license  TEXT,
                created_at      TEXT
            )
        ''')

        # ── Migrations: add columns that may be missing from older DBs ────────
        existing = {row[1] for row in con.execute('PRAGMA table_info(cases)')}
        for col, typedef in [
            ('scan_folder', 'TEXT'),
            ('prep_jaw',    'TEXT'),
            ('clinic_name', 'TEXT'),
        ]:
            if col not in existing:
                con.execute(f'ALTER TABLE cases ADD COLUMN {col} {typedef}')
                print(f'  DB migration: added column "{col}"')

        con.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Cases
# ─────────────────────────────────────────────────────────────────────────────

def upsert_case(result: dict):
    o  = result.get('order', {})
    p  = result.get('prescription', {})
    q  = result.get('quality', {})
    op = result.get('output', {})

    with _conn() as con:
        con.execute('''
            INSERT INTO cases VALUES (
                :order_id, :patient, :doctor, :clinic_address, :clinic_name,
                :procedure, :prep_teeth_fdi, :bridge_region, :prep_jaw,
                :due_date, :export_time, :notes,
                :quality_status, :quality_flags,
                :output_folder, :scan_folder, :all_views_img, :processed_at, :raw_result
            )
            ON CONFLICT(order_id) DO UPDATE SET
                patient        = excluded.patient,
                clinic_name    = excluded.clinic_name,
                quality_status = excluded.quality_status,
                quality_flags  = excluded.quality_flags,
                scan_folder    = excluded.scan_folder,
                all_views_img  = excluded.all_views_img,
                processed_at   = excluded.processed_at,
                raw_result     = excluded.raw_result
        ''', {
            'order_id':       o.get('id', ''),
            'patient':        o.get('patient', ''),
            'doctor':         o.get('doctor', ''),
            'clinic_address': o.get('clinic_address', ''),
            'clinic_name':    result.get('clinic_name', ''),
            'procedure':      o.get('procedure', ''),
            'prep_teeth_fdi': json.dumps(p.get('prep_teeth_fdi', [])),
            'bridge_region':  json.dumps(p.get('bridge_region_fdi', [])),
            'prep_jaw':       result.get('prep_jaw', ''),
            'due_date':       o.get('due_date', ''),
            'export_time':    o.get('export_time', ''),
            'notes':          o.get('notes', ''),
            'quality_status': q.get('status', ''),
            'quality_flags':  json.dumps(q.get('flags', [])),
            'output_folder':  op.get('folder', ''),
            'scan_folder':    result.get('scan_folder', ''),
            'all_views_img':  op.get('all_views', ''),
            'processed_at':   result.get('processed_at', ''),
            'raw_result':     json.dumps(result),
        })
        con.commit()


def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ('prep_teeth_fdi', 'bridge_region', 'quality_flags'):
        try:
            d[field] = json.loads(d[field] or '[]')
        except Exception:
            d[field] = []
    try:
        d['raw_result'] = json.loads(d['raw_result'] or '{}')
    except Exception:
        d['raw_result'] = {}
    return d


def get_all_cases() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            'SELECT * FROM cases ORDER BY processed_at DESC'
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_case(order_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            'SELECT * FROM cases WHERE order_id = ?', (order_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_case(order_id: str):
    with _conn() as con:
        con.execute('DELETE FROM cases WHERE order_id = ?', (order_id,))
        con.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Clinic Mappings
# ─────────────────────────────────────────────────────────────────────────────

def normalize_address(address: str) -> str:
    """
    Normalize a ship-to address for consistent lookup.
    Strips whitespace, lowercases, removes punctuation and common suffixes.
    """
    addr = address.lower().strip()
    addr = re.sub(r'[,.\-#]', ' ', addr)    # remove punctuation
    addr = re.sub(r'\s+', ' ', addr)         # collapse whitespace
    # Remove common suffixes that vary between entries
    for noise in ['canada', 'alberta', 'ab']:
        addr = addr.replace(noise, '')
    return addr.strip()


def get_clinic_mapping(address: str) -> dict | None:
    """Look up a clinic NAS folder by ship-to address."""
    key = normalize_address(address)
    with _conn() as con:
        row = con.execute(
            'SELECT * FROM clinic_mappings WHERE address_key = ?', (key,)
        ).fetchone()
    return dict(row) if row else None


def save_clinic_mapping(address: str, nas_folder: str, practice_name: str = '',
                        doctor_license: str = '') -> dict:
    """Create or update a clinic mapping."""
    key = normalize_address(address)
    with _conn() as con:
        con.execute('''
            INSERT INTO clinic_mappings (address_key, nas_folder, practice_name,
                                         doctor_license, created_at)
            VALUES (:key, :folder, :practice, :license, :ts)
            ON CONFLICT(address_key) DO UPDATE SET
                nas_folder     = excluded.nas_folder,
                practice_name  = excluded.practice_name,
                doctor_license = excluded.doctor_license
        ''', {
            'key':      key,
            'folder':   nas_folder,
            'practice': practice_name,
            'license':  doctor_license,
            'ts':       datetime.utcnow().isoformat() + 'Z',
        })
        con.commit()
    return {'address_key': key, 'nas_folder': nas_folder, 'practice_name': practice_name}


def get_all_clinic_mappings() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            'SELECT * FROM clinic_mappings ORDER BY nas_folder'
        ).fetchall()
    return [dict(r) for r in rows]


def delete_clinic_mapping(mapping_id: int):
    with _conn() as con:
        con.execute('DELETE FROM clinic_mappings WHERE id = ?', (mapping_id,))
        con.commit()