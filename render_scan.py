#!/usr/bin/env python3
#!/usr/bin/env python3
"""
render_scan.py
iTero PLY scan processor for dental lab QC review.
Parses RX data from iTero XML, loads PLY meshes with texture,
renders standardised multi-angle screenshots, runs quality analysis,
and writes PNGs + result.json to the output folder.

Usage:
    python render_scan.py <scan_folder>

Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
"""
"""
render_scan.py — iTero scan processor for dental lab QC review
Phase 1: Fully automatic, no user input required.

Usage:
    python render_scan.py <scan_folder>

Output (written to ./output/):
    {order_id}_all_views.png          — combined 4×2 image grid
    {order_id}_grid_textured.png      — textured views only
    {order_id}_grid_untextured.png    — untextured views only
    {order_id}_{view}_{mode}.png      — individual renders
    {order_id}_result.json            — full structured result

Dependencies:
    pip install trimesh vedo Pillow numpy
"""

import sys
import os
import json
import glob
import datetime
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image as PILImage, ImageDraw
import trimesh
import vedo

vedo.settings.default_backend = 'vtk'

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ADA_TO_FDI = {
     1: 18,  2: 17,  3: 16,  4: 15,  5: 14,  6: 13,  7: 12,  8: 11,
     9: 21, 10: 22, 11: 23, 12: 24, 13: 25, 14: 26, 15: 27, 16: 28,
    17: 38, 18: 37, 19: 36, 20: 35, 21: 34, 22: 33, 23: 32, 24: 31,
    25: 41, 26: 42, 27: 43, 28: 44, 29: 45, 30: 46, 31: 47, 32: 48,
}

# Keywords in doctor notes that suggest scan quality concerns
NOTE_CONCERN_KEYWORDS = [
    'difficult', 'hard scan', 'poor', 'unclear', 'worn', 'worn down',
    'blood', 'saliva', 'tissue', 'rescan', 're-scan', 'retake',
    'missing margin', 'open margin', 'artifact',
]

RENDER_W, RENDER_H = 1400, 900
HI_RES_W, HI_RES_H = RENDER_W * 4, RENDER_H * 4   # 5600 × 3600 for detail views
BG_COLOR = np.array([28, 28, 50])   # background colour used in renders


# ─────────────────────────────────────────────────────────────────────────────
# XML parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_rx_xml(folder):
    """
    Find and parse the v50 XML in the folder.
    Returns a comprehensive dict of order info, prescription, and file paths.
    Returns None if no XML found.
    """
    candidates = glob.glob(os.path.join(folder, '*_v50.xml'))
    if not candidates:
        return None

    tree = ET.parse(candidates[0])
    root = tree.getroot()
    rx   = root.find('RxInfo')
    if rx is None:
        return None

    # ── Parse RxDefines lookup tables embedded in XML ─────────────────────────
    # These let us resolve type codes → human-readable names without hardcoding.
    lookup = {}
    defines = root.find('RxDefines')
    if defines is not None:
        for section in defines:
            lookup[section.tag] = {}
            for type_el in section.findall('Type'):
                id_  = type_el.get('Id', '')
                name = type_el.get('Name', '')
                if id_:
                    lookup[section.tag][id_] = name

    def lkp(table, key, fallback='Unknown'):
        return lookup.get(table, {}).get(str(key), fallback)

    # ── Order info ────────────────────────────────────────────────────────────
    result = {
        'order': {
            'id':              rx.findtext('OrderID', '').strip(),
            'patient':         rx.findtext('Patient', '').strip(),
            'doctor':          rx.findtext('Doctor', '').strip(),
            'doctor_license':  rx.findtext('DoctorLicense', '').strip(),
            'lab':             rx.findtext('LabName', '').strip(),
            'clinic_address':  rx.findtext('PracticeShipToAddress', '').strip(),
            'due_date':        rx.findtext('DueDate', '').strip(),
            'export_time':     rx.findtext('ExportTime', '').strip(),
            'procedure':       lkp('Procedure', rx.findtext('Procedure', '')),
            'notes':           rx.findtext('Notes', '').strip(),
        },

        # ── Prescription ──────────────────────────────────────────────────────
        'prescription': {
            'restorations':      [],
            'bridges':           [],
            'prep_teeth_fdi':    [],
            'bridge_region_fdi': [],
        },

        # ── File paths (resolved from ExportedObjects) ────────────────────────
        'scan_files': {
            'upper_working':      {'ply': None, 'texture': None},
            'upper_pretreatment': {'ply': None, 'texture': None},
            'lower_working':      {'ply': None, 'texture': None},
            'lower_pretreatment': {'ply': None, 'texture': None},
        },
    }

    # ── Restorations ──────────────────────────────────────────────────────────
    missing_type_id = '21'   # RestorationType 21 = Missing / Pontic position

    teeth_el = rx.find('Teeth')
    if teeth_el is not None:
        for tooth in teeth_el.findall('Tooth'):
            ada_id = int(tooth.get('AdaId', 0))
            if not ada_id:
                continue

            fdi          = ADA_TO_FDI.get(ada_id)
            resto_id     = tooth.get('RestorationType', '')
            material_id  = tooth.get('ToothMaterial', '')
            spec_id      = tooth.get('Specification', '')
            in_bridge_id = tooth.get('TypeInBridge', '')

            resto = {
                'tooth_fdi':     fdi,
                'tooth_ada':     ada_id,
                'type':          lkp('RestorationTypes', resto_id),
                'in_bridge':     lkp('ToothInBridgeTypes', in_bridge_id) if in_bridge_id != '-1' else None,
                'material':      lkp('Materials', material_id),
                'specification': lkp('Specification', spec_id),
                'shade': {
                    'incisal':   tooth.get('IncisalShade') or None,
                    'middle':    tooth.get('MiddleShade') or None,
                    'gingival':  tooth.get('GingivalShade') or None,
                },
                'bridge_id':     tooth.get('BridgeID', None),
            }
            result['prescription']['restorations'].append(resto)

            # Prep teeth = actual preparations (not missing/pontic)
            if fdi and resto_id != missing_type_id:
                result['prescription']['prep_teeth_fdi'].append(fdi)

    # ── Bridges ───────────────────────────────────────────────────────────────
    bridges_el = rx.find('Bridges')
    if bridges_el is not None:
        for bridge in bridges_el.findall('Bridge'):
            from_ada = int(bridge.get('FromAdaId', 0))
            to_ada   = int(bridge.get('ToAdaId', 0))
            bridge_type = lkp('BridgeTypes', bridge.get('Type', ''))

            teeth_fdi = [
                ADA_TO_FDI[a]
                for a in range(min(from_ada, to_ada), max(from_ada, to_ada) + 1)
                if a in ADA_TO_FDI
            ]
            result['prescription']['bridges'].append({
                'id':        bridge.get('Id'),
                'type':      bridge_type,
                'from_fdi':  ADA_TO_FDI.get(from_ada),
                'to_fdi':    ADA_TO_FDI.get(to_ada),
                'teeth_fdi': teeth_fdi,
            })
            result['prescription']['bridge_region_fdi'].extend(teeth_fdi)

    result['prescription']['bridge_region_fdi'] = sorted(
        set(result['prescription']['bridge_region_fdi'])
    )

    # ── ExportedObjects → file paths ──────────────────────────────────────────
    exported_el = root.find('ExportedObjects')
    if exported_el is not None:
        for obj in exported_el.findall('Object'):
            obj_type = obj.get('ObjectType', '')   # Surface | Texture
            sub_type = obj.get('SubType', '')       # Jaw | PreTreatment_Jaw
            jaw_id   = obj.get('JawId', '').lower() # upper | lower
            filename = obj.get('FileName', '')

            full_path = os.path.join(folder, filename)

            if jaw_id == 'upper' and sub_type == 'Jaw':
                key = 'upper_working'
            elif jaw_id == 'upper' and sub_type == 'PreTreatment_Jaw':
                key = 'upper_pretreatment'
            elif jaw_id == 'lower' and sub_type == 'Jaw':
                key = 'lower_working'
            elif jaw_id == 'lower' and sub_type == 'PreTreatment_Jaw':
                key = 'lower_pretreatment'
            else:
                continue

            if obj_type == 'Surface':
                result['scan_files'][key]['ply'] = full_path if os.path.exists(full_path) else None
            elif obj_type == 'Texture':
                result['scan_files'][key]['texture'] = full_path if os.path.exists(full_path) else None

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Mesh loading
# ─────────────────────────────────────────────────────────────────────────────

def load_mesh(ply_path, tex_path):
    """
    Load a PLY and sample texture colours at UV coordinates.
    Returns (vertices ndarray, faces ndarray, colors uint8 ndarray).
    """
    print(f"    Loading {os.path.basename(ply_path)} ...", end=' ', flush=True)
    tm     = trimesh.load(ply_path, process=False)
    verts  = np.array(tm.vertices)
    faces  = np.array(tm.faces)

    # Case 1: External texture JPG with UV mapping (standard iTero colour export)
    if (tex_path and os.path.exists(tex_path)
            and hasattr(tm.visual, 'uv')
            and tm.visual.uv is not None):
        uv      = np.array(tm.visual.uv)
        tex_arr = np.array(PILImage.open(tex_path).convert('RGB'))
        H, W    = tex_arr.shape[:2]
        u  = np.clip(uv[:, 0], 0, 1)
        v  = np.clip(1.0 - uv[:, 1], 0, 1)      # flip V: PIL vs OpenGL
        px = np.clip((u * (W - 1)).astype(int), 0, W - 1)
        py = np.clip((v * (H - 1)).astype(int), 0, H - 1)
        colors = tex_arr[py, px].astype(np.uint8)
        print(f"✓  ({len(verts):,} verts, external texture applied)")

    # Case 2: Per-vertex colours already embedded in PLY (no texture file)
    elif getattr(tm.visual, 'kind', None) == 'vertex':
        colors = np.array(tm.visual.vertex_colors[:, :3], dtype=np.uint8)
        print(f"✓  ({len(verts):,} verts, per-vertex colours)")

    # Case 3: Texture visuals but no external file — convert to vertex colours
    elif hasattr(tm.visual, 'to_color'):
        vc        = tm.copy()
        vc.visual = tm.visual.to_color()
        colors    = np.array(vc.visual.vertex_colors[:, :3], dtype=np.uint8)
        print(f"⚠  ({len(verts):,} verts, texture converted — no external texture file)")

    # Case 4: No colour data at all — use neutral bone colour
    else:
        colors = np.full((len(verts), 3), [200, 190, 175], dtype=np.uint8)
        print(f"⚠  ({len(verts):,} verts, no colour data — using neutral)")

    return verts, faces, colors


# ─────────────────────────────────────────────────────────────────────────────
# Quality analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_quality(up_verts, up_faces, up_colors, rx_data, rendered_arrays):
    """
    Analyse scan quality from mesh data, colour statistics, and rendered views.
    Returns (flags list, status string).

    Flags have: code, severity ('warning'|'critical'), description, value.
    Status: 'pass' | 'needs_review' | 'flagged'
    """
    flags = []

    # ── 1. Saliva / reflection artifact (near-white vertex clusters) ──────────
    if up_colors is not None and len(up_colors) > 0:
        white_mask  = (up_colors[:, 0] > 230) & (up_colors[:, 1] > 230) & (up_colors[:, 2] > 230)
        white_ratio = float(white_mask.sum() / len(up_colors))
        if white_ratio > 0.02:
            flags.append({
                'code':        'saliva_artifact',
                'severity':    'critical' if white_ratio > 0.05 else 'warning',
                'description': f'Possible saliva/reflection artifact — {white_ratio:.1%} of scan surface is near-white',
                'value':       round(white_ratio, 4),
            })

    # ── 2. Blood contamination (highly saturated red clusters) ────────────────
    if up_colors is not None and len(up_colors) > 0:
        red_mask  = (up_colors[:, 0] > 160) & (up_colors[:, 1] < 90) & (up_colors[:, 2] < 90)
        red_ratio = float(red_mask.sum() / len(up_colors))
        if red_ratio > 0.005:
            flags.append({
                'code':        'blood_contamination',
                'severity':    'critical' if red_ratio > 0.02 else 'warning',
                'description': f'Possible blood contamination — {red_ratio:.1%} of scan surface shows saturated red',
                'value':       round(red_ratio, 4),
            })

    # ── 3. Scan fragmentation (disconnected mesh components) ──────────────────
    try:
        mesh   = trimesh.Trimesh(vertices=up_verts, faces=up_faces, process=False)
        pieces = mesh.split(only_watertight=False)
        n_comp = len(pieces)
        if n_comp > 4:
            flags.append({
                'code':        'scan_fragmentation',
                'severity':    'critical' if n_comp > 10 else 'warning',
                'description': f'Scan has {n_comp} disconnected segments — possible incomplete coverage',
                'value':       n_comp,
            })
    except Exception:
        pass

    # ── 4. Poor scan coverage (excess background in rendered buccal view) ─────
    buccal_arr = rendered_arrays.get('right_buccal_grey')
    if buccal_arr is not None:
        is_bg    = np.all(np.abs(buccal_arr.astype(int) - BG_COLOR) < 25, axis=2)
        bg_ratio = float(is_bg.sum() / is_bg.size)
        if bg_ratio > 0.70:
            flags.append({
                'code':        'poor_scan_coverage',
                'severity':    'critical' if bg_ratio > 0.85 else 'warning',
                'description': f'Large areas of missing scan data — {bg_ratio:.1%} of buccal view is empty',
                'value':       round(bg_ratio, 4),
            })

    # ── 5. Missing texture file ───────────────────────────────────────────────
    upper_files = rx_data.get('scan_files', {}).get('upper_working', {})
    if not upper_files.get('texture'):
        flags.append({
            'code':        'missing_texture',
            'severity':    'warning',
            'description': 'No texture file found for upper jaw — colour analysis unavailable',
            'value':       None,
        })

    # ── 6. Doctor notes mention scan difficulty ───────────────────────────────
    notes = rx_data.get('order', {}).get('notes', '').lower()
    matched = [kw for kw in NOTE_CONCERN_KEYWORDS if kw in notes]
    if matched:
        flags.append({
            'code':        'notes_concern',
            'severity':    'warning',
            'description': f'Doctor notes mention potential scan concerns: {", ".join(matched)}',
            'value':       matched,
        })

    # ── Determine overall status ──────────────────────────────────────────────
    severities = {f['severity'] for f in flags}
    if 'critical' in severities:
        status = 'flagged'
    elif 'warning' in severities:
        status = 'needs_review'
    else:
        status = 'pass'

    return flags, status


# ─────────────────────────────────────────────────────────────────────────────
# Prep region detection
# ─────────────────────────────────────────────────────────────────────────────

def get_prep_region(verts, fdi_teeth, prep_jaw='upper'):
    """
    Estimate the centroid of the prep region from FDI tooth numbers.

    Strategy:
      1. Filter vertices to the correct X side (patient left/right).
      2. Use the tooth unit digit (1–8) to estimate Y position along the arch.
         No broad anterior/posterior split — instead interpolate within the
         actual Y range of the filtered vertices.
      3. Take a narrow Y band around the estimated position and compute centroid.
      4. Z is set to the occlusal surface using the 85th/15th percentile.

    This handles single crowns, bridges, and multi-quadrant cases.
    """
    if not fdi_teeth:
        return verts.mean(axis=0)

    quadrants  = {t // 10 for t in fdi_teeth}
    right_side = bool(quadrants & {1, 4})   # patient right = negative X
    left_side  = bool(quadrants & {2, 3})   # patient left  = positive X

    # ── Step 1: X filter ──────────────────────────────────────────────────────
    mask = np.ones(len(verts), dtype=bool)
    if right_side and not left_side:
        mask &= verts[:, 0] < 0
    elif left_side and not right_side:
        mask &= verts[:, 0] > 0
    # Both sides (e.g., #12 + #22) → no X filter, centroid near midline

    region = verts[mask]
    if len(region) < 100:
        return verts.mean(axis=0)

    # ── Step 2: estimate Y target from tooth unit digits ──────────────────────
    # Tooth unit digit maps to approximate position along the arch:
    #   1 (central incisor) → most anterior (low Y percentile)
    #   8 (3rd molar)       → most posterior (high Y percentile)
    # We interpolate within the actual Y range of the filtered vertices.
    TOOTH_Y_PCT = {
        1: 0.05,   # central incisor — most anterior
        2: 0.12,   # lateral incisor
        3: 0.25,   # canine
        4: 0.40,   # 1st premolar
        5: 0.55,   # 2nd premolar
        6: 0.70,   # 1st molar
        7: 0.85,   # 2nd molar
        8: 0.95,   # 3rd molar — most posterior
    }

    unit_digits = [t % 10 for t in fdi_teeth]
    avg_pct = np.mean([TOOTH_Y_PCT.get(u, 0.5) for u in unit_digits])

    y_min, y_max = region[:, 1].min(), region[:, 1].max()
    target_y = y_min + (y_max - y_min) * avg_pct

    # ── Step 3: narrow Y band around target ───────────────────────────────────
    # Band width scales with arch depth; ~15% of Y range gives a 2–3 tooth window.
    band_half = (y_max - y_min) * 0.12
    y_mask = (region[:, 1] > target_y - band_half) & (region[:, 1] < target_y + band_half)
    narrow = region[y_mask]

    if len(narrow) < 50:
        # Fallback: use broader region
        narrow = region

    cx, cy = narrow[:, :2].mean(axis=0)

    # ── Step 4: Z → occlusal surface ─────────────────────────────────────────
    if prep_jaw == 'upper':
        cz = np.percentile(narrow[:, 2], 15)
    else:
        cz = np.percentile(narrow[:, 2], 85)

    return np.array([cx, cy, cz])


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

def build_vedo_mesh(verts, faces, colors, textured):
    vm = vedo.Mesh([verts, faces])
    if textured and colors is not None:
        vm.pointdata['RGB'] = colors
        vm.pointdata.select('RGB')
        vm.lighting('off')
    else:
        vm.color([215, 205, 190]).lighting('default')
    return vm


def render_view(mesh_list, cam_pos, focal, up_vec, fov, hflip=False, render_size=None):
    w, h = render_size if render_size else (RENDER_W, RENDER_H)
    plt = vedo.Plotter(offscreen=True, size=(w, h), bg=tuple(BG_COLOR))
    plt.show(*mesh_list, resetcam=False)
    plt.camera.SetPosition(cam_pos)
    plt.camera.SetFocalPoint(focal)
    plt.camera.SetViewUp(up_vec)
    plt.camera.SetViewAngle(fov)
    plt.render()
    arr = plt.screenshot(asarray=True)
    plt.close()
    return np.fliplr(arr) if hflip else arr


def add_label(img, text, textured):
    draw = ImageDraw.Draw(img)
    tag  = 'TEXTURED' if textured else 'UNTEXTURED'
    col  = (220, 220, 255) if textured else (255, 220, 180)
    draw.rectangle([0, 0, img.width, 36], fill=(15, 15, 38))
    draw.text((12, 8), f'{text}  [{tag}]', fill=col)
    return img


def make_grid(entries, path, cols, thumb_w=900, thumb_h=580):
    """entries: list of (filepath, label, textured)"""
    imgs = []
    for fp, name, textured in entries:
        im = PILImage.open(fp).convert('RGB').resize((thumb_w, thumb_h), PILImage.LANCZOS)
        add_label(im, name, textured)
        imgs.append(im)
    rows = (len(imgs) + cols - 1) // cols
    grid = PILImage.new('RGB', (thumb_w * cols, thumb_h * rows), (18, 18, 36))
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        grid.paste(im, (c * thumb_w, r * thumb_h))
    grid.save(path, quality=95)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def process_scan_folder(folder: str, output_base: str = None) -> dict:
    """
    Process an iTero scan folder end-to-end.
    Returns the full result dict (same data written to result.json).
    output_base: directory in which output/{order_id}/ is created.
                 Defaults to ./output relative to cwd.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise ValueError(f"Not a directory: {folder}")

    # ── Parse RX XML ──────────────────────────────────────────────────────────
    print('\n── Parsing RX data ───────────────────────────────────────────────────')
    rx = parse_rx_xml(folder)
    if rx:
        o = rx['order']
        p = rx['prescription']
        print(f"  Order      : {o['id']}")
        print(f"  Patient    : {o['patient']}")
        print(f"  Doctor     : {o['doctor']}")
        print(f"  Due date   : {o['due_date']}")
        print(f"  Procedure  : {o['procedure']}")
        print(f"  Prep teeth : FDI {p['prep_teeth_fdi']}")
        print(f"  Bridge rgn : FDI {p['bridge_region_fdi']}")
        order_id = o['id']
    else:
        print('  ⚠  No v50 XML found — continuing with defaults.')
        rx       = {
            'order': {'id': os.path.basename(folder), 'notes': ''},
            'prescription': {'prep_teeth_fdi': [], 'bridge_region_fdi': []},
            'scan_files': {
                'upper_working':      {'ply': None, 'texture': None},
                'upper_pretreatment': {'ply': None, 'texture': None},
                'lower_working':      {'ply': None, 'texture': None},
                'lower_pretreatment': {'ply': None, 'texture': None},
            },
        }
        order_id = os.path.basename(folder)

    # ── Resolve file paths ────────────────────────────────────────────────────
    sf = rx['scan_files']

    # Prefer working scan (without_ditch) for both jaws; fall back to pretreatment.
    # IMPORTANT: XML SubType can be unreliable — validate by filename.
    # 'pretreatment' in the filename = pre-op scan, NOT the prepped one.
    # 'without_ditch' in the filename = working (prepped) scan.
    def _pick_working(working_entry, pretreat_entry, jaw_label):
        """Return (working_ply, working_tex, pretreat_ply, pretreat_tex)."""
        w_ply = working_entry.get('ply')
        w_tex = working_entry.get('texture')
        p_ply = pretreat_entry.get('ply')
        p_tex = pretreat_entry.get('texture')

        # If the "working" file has 'pretreatment' in its name, the XML lied — swap them
        if w_ply and 'pretreatment' in os.path.basename(w_ply).lower():
            w_ply, p_ply = p_ply, w_ply
            w_tex, p_tex = p_tex, w_tex
            if w_ply:
                print(f"  ⚠  {jaw_label}: XML mismapped pretreatment as working — corrected by filename")

        return w_ply or p_ply, w_tex or p_tex, p_ply, p_tex

    upper_ply, upper_tex, upper_pretx_ply, upper_pretx_tex = _pick_working(
        sf['upper_working'], sf['upper_pretreatment'], 'Upper')
    lower_ply, lower_tex, lower_pretx_ply, lower_pretx_tex = _pick_working(
        sf['lower_working'], sf.get('lower_pretreatment', {}), 'Lower')

    # Last resort: scan folder for any upper/lower .ply files
    if not upper_ply:
        candidates = sorted(glob.glob(os.path.join(folder, '*upper*.ply')))
        # Prefer without_ditch (working/prepped), avoid pretreatment
        upper_ply = next((f for f in candidates if 'without_ditch' in f), None) \
                    or next((f for f in candidates if 'pretreatment' not in f), None) \
                    or (candidates[0] if candidates else None)
    if not lower_ply:
        candidates = sorted(glob.glob(os.path.join(folder, '*lower*.ply')))
        lower_ply = next((f for f in candidates if 'without_ditch' in f), None) \
                    or next((f for f in candidates if 'pretreatment' not in f), None) \
                    or (candidates[0] if candidates else None)

    # Track pretreatment files separately (for 3D viewer Pre-Tx toggle)
    if not upper_pretx_ply:
        candidates = sorted(glob.glob(os.path.join(folder, '*upper*pretreatment*.ply')))
        upper_pretx_ply = candidates[0] if candidates else None
    if not lower_pretx_ply:
        candidates = sorted(glob.glob(os.path.join(folder, '*lower*pretreatment*.ply')))
        lower_pretx_ply = candidates[0] if candidates else None

    if not upper_ply:
        print('\nError: Could not find upper jaw PLY file.')
        sys.exit(1)

    print(f"\n── Scan files ────────────────────────────────────────────────────────")
    print(f"  Upper (working)  : {os.path.basename(upper_ply)}")
    print(f"  Upper texture    : {os.path.basename(upper_tex) if upper_tex else '(none)'}")
    if upper_pretx_ply:
        print(f"  Upper (pre-tx)   : {os.path.basename(upper_pretx_ply)}")
    print(f"  Lower (working)  : {os.path.basename(lower_ply) if lower_ply else '(skipped)'}")
    if lower_pretx_ply:
        print(f"  Lower (pre-tx)   : {os.path.basename(lower_pretx_ply)}")

    # ── Load meshes ───────────────────────────────────────────────────────────
    print(f"\n── Loading meshes ────────────────────────────────────────────────────")
    up_verts, up_faces, up_colors = load_mesh(upper_ply, upper_tex)

    lo_verts = lo_faces = lo_colors = None
    if lower_ply:
        lo_verts, lo_faces, lo_colors = load_mesh(lower_ply, lower_tex)

    # ── Camera geometry ───────────────────────────────────────────────────────
    all_verts = np.vstack([up_verts, lo_verts]) if lo_verts is not None else up_verts
    cx, cy, cz = all_verts.mean(axis=0)
    span       = (all_verts.max(axis=0) - all_verts.min(axis=0)).max()
    d_arch     = span * 1.55
    top_cam_z  = cz + d_arch      # reliable camera height — same formula as pal_ling view

    region_teeth = rx['prescription']['bridge_region_fdi'] or rx['prescription']['prep_teeth_fdi']
    prep_teeth   = rx['prescription']['prep_teeth_fdi']

    # Determine which jaw has the prep (FDI 3x/4x = lower, 1x/2x = upper)
    prep_jaw = 'lower' if any(t // 10 in (3, 4) for t in prep_teeth) else 'upper'

    # Assign primary jaw (the prepped one) and antagonist
    if prep_jaw == 'lower' and lo_verts is not None:
        pri_v, pri_f, pri_c = lo_verts, lo_faces, lo_colors
        ant_v, ant_f, ant_c = up_verts, up_faces, up_colors
    else:
        pri_v, pri_f, pri_c = up_verts, up_faces, up_colors
        ant_v, ant_f, ant_c = lo_verts,  lo_faces,  lo_colors

    bcx, bcy, bcz = get_prep_region(pri_v, region_teeth, prep_jaw)

    print(f"\n  Arch centre  : ({cx:.1f}, {cy:.1f}, {cz:.1f})  span={span:.1f}")
    print(f"  Prep jaw     : {prep_jaw.upper()}")
    print(f"  Prep focus   : ({bcx:.1f}, {bcy:.1f}, {bcz:.1f})")

    # ── Define views ──────────────────────────────────────────────────────────
    # Columns: key, label, cam_pos, focal, up_vec, fov, hflip, combined_with_lower
    #
    # Coordinate system (iTero):
    #   X neg = patient RIGHT   X pos = patient LEFT
    #   Y neg = anterior        Y pos = posterior
    #   Z pos = occlusal (up)
    #
    prep_label = f"FDI {sorted(region_teeth)}" if region_teeth else "Prep Region"

    # Buccal side: right (cam neg-X) for quadrants 1 & 4; left (cam pos-X) for 2 & 3
    buccal_quads = {t // 10 for t in prep_teeth} if prep_teeth else {1}
    if buccal_quads & {1, 4}:
        buccal_label = 'Arch — Right Buccal'
        buccal_cam   = (cx - d_arch, cy, cz)
    else:
        buccal_label = 'Arch — Left Buccal'
        buccal_cam   = (cx + d_arch, cy, cz)

    # Up vector for prep_occlusal: clinical standard = lingual at top, buccal at bottom.
    # For right-side preps (Q1/Q4): lingual = +X → up = (1, 0, 0)
    # For left-side preps  (Q2/Q3): lingual = -X → up = (-1, 0, 0)
    # Anterior (−Y) lands on the LEFT, posterior on the RIGHT — natural reading direction.
    occlusal_up = (1, 0, 0) if buccal_quads & {1, 4} else (-1, 0, 0)

    # Prep occlusal camera: direction MUST match which side the occlusal surface faces.
    # Upper jaw: occlusal surface faces DOWN → camera goes BELOW (cz - d_arch), same as pal_ling.
    # Lower jaw: occlusal surface faces UP   → camera goes ABOVE (cz + d_arch).
    if prep_jaw == 'upper':
        prep_cam   = (bcx, bcy, cz - d_arch)   # below upper arch, looks up at biting surface
        prep_up    = (0, -1, 0)                 # consistent with pal_ling for upper jaw
        prep_hflip = False
    else:
        prep_cam   = (bcx, bcy, cz + d_arch)   # above lower arch, looks down at biting surface
        prep_up    = occlusal_up                # quadrant-aware: lingual at top
        prep_hflip = False

    # Palatal (upper) vs Lingual/Occlusal (lower)
    # Upper palatal: camera below arch looking up  → (cz - d_arch)
    # Lower lingual: camera above arch looking down → (cz + d_arch)
    if prep_jaw == 'lower':
        pal_ling_label = 'Arch — Lingual / Occlusal'
        pal_ling_cam   = (cx, cy, cz + d_arch)
        pal_ling_hflip = False
    else:
        pal_ling_label = 'Arch — Palatal'
        pal_ling_cam   = (cx, cy, cz - d_arch)
        pal_ling_hflip = False

    # Up vector for pal_ling view:
    # Upper palatal (camera below): anterior at top → up = (0, -1, 0)
    # Lower lingual (camera above): anterior at bottom → up = (0, 1, 0)
    pal_ling_up = (0, 1, 0) if prep_jaw == 'lower' else (0, -1, 0)

    # HI_RES applied to pal_ling and prep_occlusal for detailed margin review.
    # prep_occlusal uses a narrower FOV (25°) to zoom into the prep region;
    # camera distance ≈ d_arch so visible width ≈ 2 × d_arch × tan(12.5°) ≈ 38 mm —
    # enough to frame a single crown or a 3-unit bridge with ~6 mm breathing room each side.
    STD = None                               # standard resolution (1400 × 900)
    HI  = (HI_RES_W, HI_RES_H)             # 4× resolution (5600 × 3600)

    views = [
        # ( key, label, cam_pos, focal, up_vec, fov, hflip, combined, render_size )
        ('buccal', buccal_label,
         buccal_cam,       (cx, cy, cz),    (0, 0, 1),  40, False,         True,  STD),

        ('anterior', 'Arch — Anterior',
         (cx, cy-d_arch, cz), (cx, cy, cz), (0, 0, 1),  40, False,         True,  STD),

        ('pal_ling', pal_ling_label,
         pal_ling_cam,     (cx, cy, cz),    pal_ling_up, 38, pal_ling_hflip, False, HI),

        ('prep_occlusal', f'Prep — Occlusal ({prep_label})',
         prep_cam,         (bcx, bcy, bcz), prep_up,    25, prep_hflip,     False, HI),
    ]

    # ── Output directory ──────────────────────────────────────────────────────
    _base   = output_base if output_base else os.path.join(os.getcwd(), 'output')
    out_dir = os.path.join(_base, order_id)
    os.makedirs(out_dir, exist_ok=True)
    prefix  = os.path.join(out_dir, order_id)

    # ── Render all views ──────────────────────────────────────────────────────
    print(f"\n── Rendering ─────────────────────────────────────────────────────────")
    saved          = {}    # key → {tex: (path, label), grey: (path, label)}
    rendered_arrays = {}   # key_mode → numpy array (for quality analysis)

    for textured in (True, False):
        mode   = 'tex' if textured else 'grey'
        suffix = 'textured' if textured else 'untextured'
        print(f"  {suffix.capitalize()}:")

        pri_mesh = build_vedo_mesh(pri_v, pri_f, pri_c, textured)
        ant_mesh = build_vedo_mesh(ant_v, ant_f, ant_c, textured) if ant_v is not None else None

        for key, label, pos, focal, up_vec, fov, hflip, combined, rsize in views:
            # Combined views show primary + antagonist; individual views show primary only
            meshes = [pri_mesh] + ([ant_mesh] if combined and ant_mesh else [])
            arr    = render_view(meshes, pos, focal, up_vec, fov, hflip=hflip, render_size=rsize)

            path = f'{prefix}_{key}_{suffix}.png'
            PILImage.fromarray(arr).save(path)
            rendered_arrays[f'{key}_{mode}'] = arr

            if key not in saved:
                saved[key] = {}
            saved[key][mode] = (path, label)
            print(f'    ✓  {label}')

    # ── Quality analysis ──────────────────────────────────────────────────────
    print(f"\n── Quality analysis ──────────────────────────────────────────────────")
    flags, status = analyze_quality(pri_v, pri_f, pri_c, rx, rendered_arrays)

    status_icon = {'pass': '✅', 'needs_review': '⚠️ ', 'flagged': '🚨'}.get(status, '?')
    print(f"  Status: {status_icon} {status.upper()}")
    if flags:
        for f in flags:
            icon = '🚨' if f['severity'] == 'critical' else '⚠️ '
            print(f"  {icon} [{f['code']}] {f['description']}")
    else:
        print("  No quality issues detected.")

    # ── Build grids ───────────────────────────────────────────────────────────
    print(f"\n── Building output grids ─────────────────────────────────────────────")

    tex_entries  = [(saved[k]['tex'][0],  saved[k]['tex'][1],  True)  for k, *_ in views if 'tex'  in saved.get(k, {})]
    grey_entries = [(saved[k]['grey'][0], saved[k]['grey'][1], False) for k, *_ in views if 'grey' in saved.get(k, {})]
    all_entries  = tex_entries + grey_entries

    grid_tex  = f'{prefix}_grid_textured.png'
    grid_grey = f'{prefix}_grid_untextured.png'
    grid_all  = f'{prefix}_all_views.png'

    make_grid(tex_entries,  grid_tex,  cols=2)
    make_grid(grey_entries, grid_grey, cols=2)
    make_grid(all_entries,  grid_all,  cols=4)   # Row 1: textured, Row 2: untextured
    print(f"  ✓  Grids saved")

    # ── Write result.json ─────────────────────────────────────────────────────
    result_data = {
        'schema_version': '1.0',
        'processed_at':   datetime.datetime.utcnow().isoformat() + 'Z',
        'order':          rx['order'],
        'prescription':   rx['prescription'],
        'scan_files': {
            'upper_ply':         os.path.basename(upper_ply) if upper_ply else None,
            'upper_texture':     os.path.basename(upper_tex) if upper_tex else None,
            'lower_ply':         os.path.basename(lower_ply) if lower_ply else None,
            'lower_texture':     os.path.basename(lower_tex) if lower_tex else None,
            'upper_pretreat_ply': os.path.basename(sf['upper_pretreatment']['ply'])
                                  if sf['upper_pretreatment']['ply'] else None,
            'lower_pretreat_ply': os.path.basename(sf['lower_pretreatment']['ply'])
                                  if sf['lower_pretreatment']['ply'] else None,
        },
        'prep_jaw': prep_jaw,
        'quality': {
            'status': status,
            'flags':  flags,
        },
        'output': {
            'folder':           out_dir,
            'all_views':        os.path.basename(grid_all),
            'textured_grid':    os.path.basename(grid_tex),
            'untextured_grid':  os.path.basename(grid_grey),
            'individual': {
                f'{k}_{m}': os.path.basename(saved[k][m][0])
                for k, *_ in views
                for m in ('tex', 'grey')
            },
        },
    }

    json_path = f'{prefix}_result.json'
    with open(json_path, 'w') as f:
        json.dump(result_data, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_files = len(views) * 2 + 3 + 1
    print(f"\n── Done ──────────────────────────────────────────────────────────────")
    print(f"  Output folder : {out_dir}/")
    print(f"  All views     : {os.path.basename(grid_all)}")
    print(f"  Result JSON   : {os.path.basename(json_path)}")
    print(f"  Total files   : {total_files}")
    print(f"  Status        : {status_icon} {status.upper()}")

    return result_data


def main():
    if len(sys.argv) < 2:
        print('Usage: python render_scan.py <scan_folder>')
        sys.exit(1)
    result = process_scan_folder(sys.argv[1])
    sys.exit(0 if result else 1)


if __name__ == '__main__':
    main()