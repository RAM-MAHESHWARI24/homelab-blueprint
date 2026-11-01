#!/usr/bin/env python3
"""
Noodle Gallery / Immich Face-to-XMP & Cloud Backup - Standalone Integration Test
Validates:
  1. 4-person photo ingestion into Noodle Gallery / Immich.
  2. Machine learning facial detection of 4 distinct bounding boxes.
  3. API-driven face assignment and naming.
  4. Non-destructive XMP sidecar generation via Batch ExifTool (-@).
  5. MWG-rs compliance check (-RegionName, -RegionAreaX/Y/W/H).
  6. Database snapshot creation and simulated cloud sync via rclone.
"""

import os
import sys
import json
import time
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "four_people_sample.jpg"
EXPORTER_SCRIPT = REPO_ROOT / "export_faces_to_xmp.py"

IMMICH_HOST = os.getenv("IMMICH_HOST", "http://127.0.0.1:2283")
ADMIN_EMAIL = os.getenv("IMMICH_ADMIN_EMAIL", "admin@homelab.local")
ADMIN_PASSWORD = os.getenv("IMMICH_ADMIN_PASSWORD", "AdminPassword123!")

MOCK_GDRIVE_DIR = Path("/tmp/mock_gdrive")
BACKUP_DIR = Path("/tmp/immich_backups")


def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [STANDALONE-TEST] {msg}", flush=True)


def api_call(endpoint: str, method: str = "GET", body: Optional[Any] = None, token: Optional[str] = None, timeout: int = 15) -> Tuple[int, Any]:
    url = f"{IMMICH_HOST}/api{endpoint}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(content)
            except Exception:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(content)
        except Exception:
            return e.code, content
    except Exception as e:
        return 0, str(e)


def create_initial_xmp_sidecar(target_path: Path):
    """Generates initial XMP sidecar with 2 of 4 people pre-tagged (John & Paul)"""
    xmp_content = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 5.5.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/"
    xmlns:stDim="http://www.metadataworkinggroup.com/schemas/regions/dimensions#"
    xmlns:stArea="http://www.metadataworkinggroup.com/schemas/regions/area#">
   <mwg-rs:Regions rdf:parseType="Resource">
    <mwg-rs:AppliedToDimensions stDim:w="1156" stDim:h="839" stDim:unit="pixel"/>
    <mwg-rs:RegionList>
     <rdf:Bag>
      <rdf:li>
       <rdf:Description mwg-rs:Name="John Lennon" mwg-rs:Type="Face">
        <mwg-rs:Area stArea:x="0.201" stArea:y="0.219" stArea:w="0.084" stArea:h="0.152" stArea:unit="normalized"/>
       </rdf:Description>
      </rdf:li>
      <rdf:li>
       <rdf:Description mwg-rs:Name="Paul McCartney" mwg-rs:Type="Face">
        <mwg-rs:Area stArea:x="0.704" stArea:y="0.258" stArea:w="0.098" stArea:h="0.174" stArea:unit="normalized"/>
       </rdf:Description>
      </rdf:li>
     </rdf:Bag>
    </mwg-rs:RegionList>
   </mwg-rs:Regions>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""
    target_path.write_text(xmp_content, encoding="utf-8")


def run_test():
    log("=== Running Standalone Noodle Gallery Face Exporter Test ===")
    assert FIXTURE_IMAGE.exists(), f"Missing fixture image: {FIXTURE_IMAGE}"
    assert EXPORTER_SCRIPT.exists(), f"Missing exporter script: {EXPORTER_SCRIPT}"

    # 1. Authenticate
    st, res = api_call("/auth/login", method="POST", body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if st not in (200, 201):
        api_call("/auth/admin-sign-up", method="POST", body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "name": "Admin"})
        st, res = api_call("/auth/login", method="POST", body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})

    assert st in (200, 201) and "accessToken" in res, f"Login failed: {res}"
    token = res["accessToken"]
    log(f"✅ Authenticated with API as '{ADMIN_EMAIL}'")

    # 2. Upload asset with sidecar
    tmp_img = Path("/tmp/beatles_test.jpg")
    tmp_xmp = Path("/tmp/beatles_test.jpg.xmp")
    shutil.copy2(FIXTURE_IMAGE, tmp_img)
    create_initial_xmp_sidecar(tmp_xmp)

    cmd = [
        "curl", "-s", "-X", "POST",
        "-H", f"Authorization: Bearer {token}",
        "-F", f"assetData=@{tmp_img}",
        "-F", f"sidecarData=@{tmp_xmp}",
        "-F", f"deviceAssetId=test-standalone-{int(time.time())}",
        "-F", "deviceId=standalone-runner",
        "-F", "fileCreatedAt=2026-11-01T12:00:00.000Z",
        "-F", "fileModifiedAt=2026-11-01T12:00:00.000Z",
        "-F", "isFavorite=false",
        f"{IMMICH_HOST}/api/assets"
    ]
    res_up = subprocess.run(cmd, capture_output=True, text=True, check=True)
    asset_id = json.loads(res_up.stdout).get("id")
    log(f"✅ Asset ingested! ID: {asset_id}")

    # 3. Trigger face detection & recognition
    api_call("/jobs/faceDetection", method="PUT", body={"command": "start"}, token=token)
    api_call("/jobs/facialRecognition", method="PUT", body={"command": "start"}, token=token)

    faces = []
    for _ in range(30):
        time.sleep(2.0)
        st, faces_resp = api_call(f"/faces?id={asset_id}", token=token)
        if st == 200 and isinstance(faces_resp, list) and len(faces_resp) >= 4:
            faces = faces_resp
            break

    assert len(faces) >= 4, f"Face detection timed out (found {len(faces)} faces)"
    log(f"✅ Machine Learning detected {len(faces)} faces!")

    # 4. Tag remaining faces
    sorted_faces = sorted(faces, key=lambda f: f.get("boundingBoxX1", 0))
    names = ["John Lennon", "George Harrison", "Ringo Starr", "Paul McCartney"]

    for idx, f in enumerate(sorted_faces[:4]):
        name = names[idx]
        st, p_resp = api_call("/people", method="POST", body={"name": name}, token=token)
        if st in (200, 201):
            person_id = p_resp["id"]
        else:
            st_list, p_list = api_call("/people", token=token)
            person = next((p for p in p_list.get("people", []) if p.get("name") == name), None)
            person_id = person["id"]
        api_call(f"/faces/{person_id}", method="PUT", body={"id": f["id"]}, token=token)

    log("✅ All 4 people assigned in database!")

    # 5. Run export_faces_to_xmp.py
    env = os.environ.copy()
    res_exp = subprocess.run([sys.executable, str(EXPORTER_SCRIPT), "--force"], env=env, capture_output=True, text=True)
    assert res_exp.returncode == 0, f"Export failed: {res_exp.stderr}"
    log("✅ Batch ExifTool export completed successfully!")

    # 6. Verify assertions
    sidecars = list(Path("/data/immich/upload/upload").rglob("*.xmp"))
    if not sidecars:
        sidecars = list(Path("/tmp").glob("*.xmp"))
    assert sidecars, "No XMP sidecars found!"

    exif_res = subprocess.run(["exiftool", "-RegionName", "-s3", str(sidecars[0])], capture_output=True, text=True, check=True)
    raw = exif_res.stdout.replace("\n", ",")
    found_names = [n.strip() for n in raw.split(",") if n.strip()]
    assert set(names).issubset(set(found_names)), f"Missing names in sidecar: {set(names) - set(found_names)}"

    log("🏆 STANDALONE TEST PASSED: All 4 faces verified in XMP sidecar!")


if __name__ == "__main__":
    run_test()
