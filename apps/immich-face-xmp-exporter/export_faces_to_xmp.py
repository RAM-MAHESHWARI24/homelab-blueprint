#!/usr/bin/env python3
"""
Immich Face-to-XMP Sidecar Exporter (High-Performance Batch Version)
Exports named people and bounding boxes from Immich's PostgreSQL database
into standard XMP-mwg-rs (Metadata Working Group) sidecar files.

Compatible with: DigiKam, Adobe Lightroom, Adobe Bridge, and Immich reverse-sync.

Features:
- Incremental state cache (.faces_export_cache.json): Skips assets already exported.
- High-performance ExifTool batching (-@ argfile): 10x-50x faster than single invocations.
- Non-destructive: Never modifies original media binaries; writes only .xmp sidecars.
"""

import os
import sys
import json
import tempfile
import argparse
import subprocess
from pathlib import Path

# Configuration & Cache
CACHE_FILE = Path(os.getenv("FACES_CACHE_FILE", Path(__file__).resolve().parent / ".faces_export_cache.json"))
DB_CONTAINER = os.getenv("IMMICH_POSTGRES_CONTAINER", "immich_postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_NAME = os.getenv("DB_NAME", "immich")


def load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Warning: Could not save cache: {e}", file=sys.stderr)


def get_assets_with_faces(path_filter=None, limit=None):
    sql = """
    SELECT json_build_object(
        'asset_id', a.id,
        'original_path', a."originalPath",
        'width', COALESCE(a.width, MAX(af."imageWidth")),
        'height', COALESCE(a.height, MAX(af."imageHeight")),
        'orientation', MAX(ae.orientation),
        'faces', json_agg(json_build_object(
            'name', p.name,
            'x1', af."boundingBoxX1",
            'y1', af."boundingBoxY1",
            'x2', af."boundingBoxX2",
            'y2', af."boundingBoxY2",
            'img_w', af."imageWidth",
            'img_h', af."imageHeight"
        ))
    )::text
    FROM asset a
    JOIN asset_face af ON af."assetId" = a.id
    JOIN person p ON p."personGroupId" = af."personGroupId"
    LEFT JOIN asset_exif ae ON ae."assetId" = a.id
    WHERE p.name IS NOT NULL AND p.name != '' AND p."isHidden" = false AND af."isVisible" = true
    GROUP BY a.id, a."originalPath", a.width, a.height
    ORDER BY a."originalPath" ASC;
    """

    cmd = ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-t", "-A", "-c", sql]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)

    assets = []
    for line in p.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if path_filter and path_filter not in data["original_path"]:
                continue
            assets.append(data)
            if limit and len(assets) >= limit:
                break
        except Exception as e:
            print(f"Skipping unparseable line: {e}", file=sys.stderr)
    return assets


def get_sidecar_path(original_path):
    p = Path(original_path)
    candidate1 = Path(f"{original_path}.xmp")
    candidate2 = p.with_suffix(".xmp")
    
    if candidate1.exists():
        return candidate1
    if candidate2.exists():
        return candidate2
    return candidate1


def build_exiftool_args_for_asset(asset):
    original_path = asset["original_path"]
    faces = asset["faces"]

    if not os.path.exists(original_path):
        return None, None

    sidecar = get_sidecar_path(original_path)

    ref_w = asset["width"] or faces[0]["img_w"]
    ref_h = asset["height"] or faces[0]["img_h"]

    if not ref_w or not ref_h:
        return None, None

    args = [
        "-overwrite_original",
        "-RegionInfo=",
        f"-RegionAppliedToDimensionsW={ref_w}",
        f"-RegionAppliedToDimensionsH={ref_h}",
        "-RegionAppliedToDimensionsUnit=pixel"
    ]

    for idx, f in enumerate(faces):
        name = f["name"].strip()
        x1, y1, x2, y2 = f["x1"], f["y1"], f["x2"], f["y2"]

        cx = (x1 + x2) / 2.0 / ref_w
        cy = (y1 + y2) / 2.0 / ref_h
        w = abs(x2 - x1) / ref_w
        h = abs(y2 - y1) / ref_h

        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        w = max(0.0, min(1.0, w))
        h = max(0.0, min(1.0, h))

        args.extend([
            f"-RegionAreaX+={cx:.5f}",
            f"-RegionAreaY+={cy:.5f}",
            f"-RegionAreaW+={w:.5f}",
            f"-RegionAreaH+={h:.5f}",
            "-RegionAreaUnit+=normalized",
            "-RegionType+=Face",
            f"-RegionName+={name}"
        ])

    args.append(str(sidecar))
    return sidecar, args


def main():
    parser = argparse.ArgumentParser(description="Export Immich Faces to MWG XMP Sidecars")
    parser.add_argument("--filter", help="Path substring filter", default=None)
    parser.add_argument("--limit", type=int, help="Limit number of assets", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying sidecars")
    parser.add_argument("--force", action="store_true", help="Ignore cache and re-export all assets")
    args = parser.parse_args()

    print("Fetching named face assets from PostgreSQL...")
    assets = get_assets_with_faces(path_filter=args.filter, limit=args.limit)
    print(f"Found {len(assets)} assets with named faces.")

    cache = {} if args.force else load_cache()
    pending = []

    for a in assets:
        aid = a["asset_id"]
        face_hash = json.dumps(sorted([f["name"] for f in a["faces"]]))
        if aid in cache and cache[aid] == face_hash:
            continue
        pending.append((a, face_hash))

    print(f"Pending export: {len(pending)} assets (skipped {len(assets) - len(pending)} cached).")
    if not pending:
        print("All assets are up to date!")
        return

    all_exiftool_args = []
    processed_items = []

    for a, fhash in pending:
        sidecar, cmd_args = build_exiftool_args_for_asset(a)
        if cmd_args:
            all_exiftool_args.extend(cmd_args)
            all_exiftool_args.append("-execute")
            processed_items.append((a["asset_id"], fhash))

    if args.dry_run:
        print(f"[DRY-RUN] Would process {len(processed_items)} sidecars using batch ExifTool.")
        return

    # Write batch argfile for ExifTool (-@)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
        for arg in all_exiftool_args:
            tf.write(arg + "\n")
        argfile_path = tf.name

    try:
        print(f"Running batch ExifTool against {len(processed_items)} sidecars...")
        proc = subprocess.run(["exiftool", "-@", argfile_path], capture_output=True, text=True)
        if proc.returncode == 0:
            for aid, fhash in processed_items:
                cache[aid] = fhash
            save_cache(cache)
            print("Batch export completed successfully!")
        else:
            print(f"ExifTool had warnings/errors:\n{proc.stderr}", file=sys.stderr)
    finally:
        if os.path.exists(argfile_path):
            os.remove(argfile_path)


if __name__ == "__main__":
    main()
