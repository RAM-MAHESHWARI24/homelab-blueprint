#!/usr/bin/env python3
"""Capture visual regression screenshots of Control Hub across Git commits.

Uses isolated detached git worktrees + Playwright so the current checkout is never
modified, and writes PNG captures plus docs/CONTROL_HUB_VISUAL_HISTORY.md.

Usage:
    python testing/capture_visual_history.py
    python testing/capture_visual_history.py --commits 2ff463b 032e103 8cda9bc e4a7879
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = REPO_ROOT / "docs" / "assets" / "visual-history"
REPORT_PATH = REPO_ROOT / "docs" / "CONTROL_HUB_VISUAL_HISTORY.md"

DEFAULT_STAGES = [
    ("01-pr56-pivot-b", "2ff463b", "PR #56 — Pivot Phase A & B (5-View Console Baseline)"),
    ("02-pr57-polish", "032e103", "PR #57 — De-AI Polish Pass (Impeccable & Hallmark)"),
    ("03-pr60-console-c1", "8cda9bc", "PR #60 — Hallmark Console C1 (OKLCH Tokens, Fonts & 4px Scale)"),
    ("04-pr61-console-c2", "e4a7879", "PR #61 — Hallmark Console C2 (Bench, Audit Spine & Service Ledger)"),
]

WORKER_SCRIPT = textwrap.dedent(
    """
    from __future__ import annotations

    from datetime import datetime, timedelta, timezone
    import os
    from pathlib import Path
    import sys
    import tempfile
    import threading
    from unittest import mock

    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    worktree_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    hub_dir = worktree_dir / "apps" / "control-hub"
    sys.path.insert(0, str(hub_dir))

    import config  # noqa: E402
    from core.config_core import auth_password  # noqa: E402
    import server  # noqa: E402
    from widgets import alerts as alerts_widget  # noqa: E402

    SAMPLE_SERVICES = [
        {"id": "jellyfin", "docker_id": "a1b2c3d4e5f6", "name": "Jellyfin", "port": 8096, "has_web_ui": True, "description": "Media Streaming", "category": "media", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/jellyfin:latest", "is_up": True},
        {"id": "seerr", "docker_id": "b2c3d4e5f6a1", "name": "Seerr", "port": 5055, "has_web_ui": True, "description": "Media Requests", "category": "media", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "ghcr.io/seerr-team/seerr:latest", "is_up": True},
        {"id": "immich_server", "docker_id": "c3d4e5f6a1b2", "name": "Immich", "port": 2283, "has_web_ui": True, "description": "Photo Cloud", "category": "media", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "ghcr.io/immich-app/immich-server:release", "is_up": True},
        {"id": "sonarr", "docker_id": "d4e5f6a1b2c3", "name": "Sonarr", "port": 8989, "has_web_ui": True, "description": "TV Series Manager", "category": "ingest", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/sonarr:latest", "is_up": True},
        {"id": "radarr", "docker_id": "e5f6a1b2c3d4", "name": "Radarr", "port": 7878, "has_web_ui": True, "description": "Movie Manager", "category": "ingest", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/radarr:latest", "is_up": True},
        {"id": "prowlarr", "docker_id": "f6a1b2c3d4e5", "name": "Prowlarr", "port": 9696, "has_web_ui": True, "description": "Indexer Manager", "category": "ingest", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/prowlarr:latest", "is_up": True},
        {"id": "bazarr", "docker_id": "112233445566", "name": "Bazarr", "port": 6767, "has_web_ui": True, "description": "Subtitle Manager", "category": "ingest", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/bazarr:latest", "is_up": True},
        {"id": "qbittorrent", "docker_id": "223344556677", "name": "qBittorrent", "port": 8080, "has_web_ui": True, "description": "Download Client", "category": "ingest", "state": "running", "health": "healthy", "status": "Up 5 days (healthy)", "image": "lscr.io/linuxserver/qbittorrent:latest", "is_up": True},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pw_file = root / "password"
        os.environ["HOMELAB_STATE_DIR"] = str(root)
        os.environ["CONTROL_HUB_PASSWORD_FILE"] = str(pw_file)
        os.environ["CONTROL_HUB_TOKEN"] = "visual-history-token"

        with (
            mock.patch.object(auth_password, "PASSWORD_FILE", pw_file),
            mock.patch.object(alerts_widget.engine, "config_path", root / "alerts.json"),
            mock.patch.object(alerts_widget.engine, "state_path", root / "alerts_state.json"),
        ):
            auth_password.set_password("VisualShotPass1!", path=pw_file)
            app = server.create_app()

            recent_bak = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

            def mock_services():
                from flask import jsonify
                return jsonify({
                    "services": SAMPLE_SERVICES,
                    "other_count": 0,
                    "docker_available": True,
                    "docker_error": None,
                    "dozzle_installed": False,
                    "cockpit_installed": False,
                })

            def mock_vitals():
                from flask import jsonify
                return jsonify({
                    "hostname": "homelab-node",
                    "port": 7575,
                    "uptime": "5d 14h 22m",
                    "local_time": "20:45:00",
                    "timezone": "UTC",
                    "tz_abbr": "UTC",
                    "cpu": {"usage_percent": 14.2, "temp_c": 46, "model": "Intel(R) N100", "cores": 4, "threads": 4},
                    "memory": {"used_gib": 3.4, "total_gib": 16.0, "free_gib": 12.6, "percent": 21.3},
                    "swap": {"used_gib": 0.0, "total_gib": 4.0, "percent": 0.0},
                    "storage": {
                        "single_disk": False,
                        "ssd": {"mount": "/", "total_gb": 256, "used_gb": 42, "free_gb": 214, "percent": 16.4, "breakdown": {"appdata_gb": 14.2}},
                        "hdd": {"available": True, "mount": "/mnt/hdd", "total_gb": 4000, "used_gb": 1420, "free_gb": 2580, "percent": 35.5, "is_warning": False, "is_critical": False, "breakdown": {"measured": True, "media_gb": 1120.0, "photos_gb": 280.0, "appdata_gb": None, "other_gb": 20.0, "media_pct": 28.0, "photos_pct": 7.0, "appdata_pct": 0.0, "other_pct": 0.5}},
                    },
                })

            def mock_network():
                from flask import jsonify
                return jsonify({
                    "lan": {"interface": "enp3s0", "rx_mbs": 8.4, "tx_mbs": 1.2, "total_mbs": 9.6, "link_speed_mbps": 1000, "duplex": "full", "spec_text": "1000 Mbps Full"},
                    "speedtest": {"available": True, "download_mbps": 284.5, "upload_mbps": 92.1, "ping_ms": 6.4, "isp": "Fiber ISP", "server": "Local IX", "timestamp": recent_bak},
                    "torrents": {
                        "status": "connected",
                        "collective_dl_mbs": 12.4,
                        "collective_up_mbs": 1.8,
                        "all_paused": False,
                        "total_count": 2,
                        "paused_count": 0,
                        "items": [
                            {"hash": "abc123", "name": "ubuntu-24.04.2-live-server-amd64.iso", "category": "isos", "state": "downloading", "progress": 64.5, "completed_gb": 1.72, "size_gb": 2.67, "dl_mbs": 12.4, "up_mbs": 1.8, "eta": "1m 18s"}
                        ],
                    },
                })

            def mock_backup():
                from flask import jsonify
                return jsonify({
                    "installed": True,
                    "status": "synced",
                    "current_stage": 4,
                    "is_syncing": False,
                    "db_size": "342.0 MB",
                    "gdrive_remote": "offsite-remote:",
                    "gdrive_total_gb": 2000.0,
                    "gdrive_used_gb": 310.0,
                    "gdrive_free_gb": 1690.0,
                    "gdrive_used_percent": 15.5,
                    "health": {"state": "synced", "age": "3h ago", "title": "Backup verified", "detail": "Last good backup 3h ago"},
                    "last_backup_at": recent_bak,
                    "history": [],
                })

            def mock_sleep():
                from flask import jsonify
                return jsonify({
                    "installed": True,
                    "enabled": True,
                    "state_mode": "default",
                    "skip_active": False,
                    "effective_sleep_time": "00:00",
                    "effective_wake_time": "06:00",
                    "timezone": "UTC",
                    "tz_abbr": "UTC",
                    "window_left_pct": 0.0,
                    "window_width_pct": 25.0,
                    "permanent_config": {
                        "enabled": True,
                        "sleep_hour": 0,
                        "sleep_minute": 0,
                        "wake_hour": 6,
                        "wake_minute": 0,
                        "sleep_time": "00:00",
                        "wake_time": "06:00",
                    },
                    "seconds_until_sleep": 4800,
                })

            def mock_tv():
                from flask import jsonify
                return jsonify({
                    "installed": True,
                    "status": "synced",
                    "all_up_to_date": True,
                    "pending_updates_count": 0,
                    "total_devices": 2,
                    "online_devices": 2,
                    "upstream_apps": {},
                    "devices": [],
                })

            for ep, fn in (
                ("service_matrix.get_services_status", mock_services),
                ("system_vitals.get_system_vitals", mock_vitals),
                ("network_speed.get_network_speed", mock_network),
                ("backup_sync.get_backup_status", mock_backup),
                ("sleep_guard.get_sleep_status", mock_sleep),
                ("tv_updater.get_tv_updater_status", mock_tv),
            ):
                if ep in app.view_functions:
                    app.view_functions[ep] = fn

            httpd = make_server("127.0.0.1", 0, app, threaded=True)
            base_url = f"http://127.0.0.1:{httpd.server_port}"
            threading.Thread(target=httpd.serve_forever, daemon=True).start()

            out_dir.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(viewport={"width": 1366, "height": 860})
                ctx.request.post(f"{base_url}/api/auth/login", data={"password": "VisualShotPass1!"})
                page = ctx.new_page()

                # Overview (Dark)
                page.goto(f"{base_url}/#/overview", wait_until="networkidle")
                page.wait_for_selector("#overview-apps-grid .quick-app-tile", state="visible", timeout=10000)
                page.wait_for_timeout(450)
                page.screenshot(path=str(out_dir / "overview-dark.png"))

                # Apps (Dark)
                page.goto(f"{base_url}/#/apps", wait_until="networkidle")
                page.wait_for_selector(".service-row", state="visible", timeout=10000)
                page.wait_for_timeout(450)
                page.screenshot(path=str(out_dir / "apps-dark.png"))

                # Overview (Light)
                page.goto(f"{base_url}/#/overview", wait_until="networkidle")
                page.wait_for_timeout(200)
                page.click("#btn-theme-toggle")
                page.wait_for_timeout(350)
                page.screenshot(path=str(out_dir / "overview-light.png"))

                browser.close()

            httpd.shutdown()
            httpd.server_close()
    """
)


def git_info(commit: str) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", "-s", "--format=%h%n%cs%n%s", commit],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    parts = proc.stdout.strip().splitlines()
    return {
        "sha": parts[0] if len(parts) > 0 else commit,
        "date": parts[1] if len(parts) > 1 else "",
        "subject": parts[2] if len(parts) > 2 else commit,
    }


def capture_stage(slug: str, commit: str) -> dict[str, str]:
    info = git_info(commit)
    out_dir = ASSETS_ROOT / slug
    if out_dir.exists():
        shutil.rmtree(out_dir)

    with tempfile.TemporaryDirectory() as tmp:
        wt_dir = Path(tmp) / "worktree"
        worker_file = Path(tmp) / "worker.py"
        worker_file.write_text(WORKER_SCRIPT, encoding="utf-8")

        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "add", "--detach", str(wt_dir), commit],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=True,
        )
        try:
            subprocess.run(
                [sys.executable, str(worker_file), str(wt_dir), str(out_dir)],
                timeout=120,
                check=True,
            )
        finally:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(wt_dir)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
    return info


def write_report(stages: list[tuple[str, str, str, dict[str, str]]]) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Control Hub GUI Visual History",
        "",
        "Automated side-by-side Playwright captures across the recent Control Hub GUI milestones (`1366x860`), rendered against identical deterministic hardware, container, backup, and download fixtures.",
        "",
        f"Generated by [`testing/capture_visual_history.py`](../testing/capture_visual_history.py) on `{generated}`.",
        "",
        "## Captured Commits",
        "",
        "| Stage | Commit | Date | Summary |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for _slug, _sha, title, info in stages:
        lines.append(f"| **{title}** | `{info['sha']}` | {info['date']} | {info['subject']} |")

    lines.extend([
        "",
        "## What Actually Changed Visually",
        "",
        "1. **`2ff463b` -> `032e103` (PR #57 — De-AI Polish):** Deliberately incremental; kept the `#090d14` slate + sky-blue `#38bdf8` layout intact while removing eyebrow clutter, glass blur, and nested card chrome.",
        "2. **`032e103` -> `8cda9bc` (PR #60 — Console C1):** Replaced blue-tinted navy slate with 3-step neutral graphite OKLCH (`console: graphite`) and warm cream (`console: paper`), self-hosted `Host Grotesk` + `Atkinson Hyperlegible Mono`, split **Amber** operator buttons from **Cool Blue** instrument bars, and normalized all spacing onto a 4px scale.",
        "3. **`8cda9bc` -> `e4a7879` (PR #61 — Console C2):** Replaced Overview's separated cards and Quick Launch tiles with flush 1px hairline grids (`Host Record` audit spine added beside Live Activity), and converted `#/apps` from stacked rows into a ruled multi-column `service-ledger` table on desktop.",
        "",
    ])

    sections = [
        ("overview-dark.png", "Overview (Dark Theme)", "Quick Launch, 4-cell Vitals Bench, Live Activity, and Host Record across commits."),
        ("apps-dark.png", "Apps & Media (Dark Theme)", "Installed Services list/table and qBittorrent download queue across commits."),
        ("overview-light.png", "Overview (Light Theme)", "Light colorway parity (`Carbon Slate` -> Hallmark `console: paper`)."),
    ]
    for filename, heading, subtitle in sections:
        lines.extend(["", f"## {heading}", "", subtitle, ""])
        for slug, _sha, title, info in stages:
            lines.extend([
                f"### {title} (`{info['sha']}`)",
                "",
                f"![{title} — {heading}](assets/visual-history/{slug}/{filename})",
                "",
            ])

    lines.extend([
        "## Re-Running Captures",
        "",
        "```bash",
        "python testing/capture_visual_history.py",
        "# Or compare custom commits:",
        "python testing/capture_visual_history.py --commits 2ff463b 032e103 8cda9bc e4a7879",
        "```",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture side-by-side Control Hub screenshots across commits.")
    parser.add_argument("--commits", nargs="+", help="Git commits/refs to capture in chronological order.")
    args = parser.parse_args()

    if args.commits:
        stages_input = [(f"{i + 1:02d}-{c}", c, f"Commit {c}") for i, c in enumerate(args.commits)]
    else:
        stages_input = DEFAULT_STAGES

    rendered: list[tuple[str, str, str, dict[str, str]]] = []
    for slug, commit, title in stages_input:
        print(f"Capturing {title} ({commit})...")
        info = capture_stage(slug, commit)
        rendered.append((slug, commit, title, info))
        print(f"  -> saved to docs/assets/visual-history/{slug}/")

    write_report(rendered)
    print(f"Updated {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
