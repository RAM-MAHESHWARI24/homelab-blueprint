#!/usr/bin/env python3
"""
Seerr Webhook Listener & Downloader Dispatcher
Receives approved media requests from Seerr, checks Radarr/Sonarr, and triggers automated workflows.
"""

import os
import re
import json
import subprocess
import requests
import threading
import time
import queue
from flask import Flask, request, jsonify

app = Flask(__name__)

RADARR_API = os.getenv("RADARR_API_KEY", "YOUR_RADARR_API_KEY")
SONARR_API = os.getenv("SONARR_API_KEY", "YOUR_SONARR_API_KEY")
RADARR_URL = os.getenv("RADARR_URL", "http://localhost:7878")
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989")
LOGS_DIR = os.getenv("LOGS_DIR", "./logs")
HISTORY_FILE = os.getenv("HISTORY_FILE", "./download_history.json")

download_queue = queue.Queue()
request_counter = 0


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def is_duplicate(tmdb_id, season_num=None):
    history = load_history()
    key = str(tmdb_id)
    if key not in history:
        return False
    if season_num is not None:
        return season_num in history[key].get("seasons", [])
    return history[key].get("downloaded", False)


def mark_success(tmdb_id, title, season_num=None):
    history = load_history()
    key = str(tmdb_id)
    if key not in history:
        history[key] = {"title": title, "seasons": [], "downloaded": False}
    if season_num is not None:
        if season_num not in history[key]["seasons"]:
            history[key]["seasons"].append(season_num)
    else:
        history[key]["downloaded"] = True
    save_history(history)


def get_radarr_data(tmdb_id):
    for _ in range(5):
        resp = requests.get(f"{RADARR_URL}/api/v3/movie?tmdbId={tmdb_id}", headers={"X-Api-Key": RADARR_API})
        if resp.status_code == 200 and resp.json():
            movies = resp.json()
            if movies:
                return movies[0]
        time.sleep(3)
    return None


def get_sonarr_data(tvdb_id):
    for _ in range(5):
        resp = requests.get(f"{SONARR_URL}/api/v3/series?tvdbId={tvdb_id}", headers={"X-Api-Key": SONARR_API})
        if resp.status_code == 200 and resp.json():
            series = resp.json()
            if series:
                return series[0]
        time.sleep(3)
    return None


def trigger_radarr_search(movie_id):
    requests.post(f"{RADARR_URL}/api/v3/command", headers={"X-Api-Key": RADARR_API}, json={"name": "MoviesSearch", "movieIds": [movie_id]})


def trigger_sonarr_search(series_id, season_num):
    requests.post(f"{SONARR_URL}/api/v3/command", headers={"X-Api-Key": SONARR_API}, json={"name": "SeasonSearch", "seriesId": series_id, "seasonNumber": season_num})


def process_request(data, log_file):
    media_type = data.get("media", {}).get("media_type")
    tmdb_id = data.get("media", {}).get("tmdbId")
    tvdb_id = data.get("media", {}).get("tvdbId")

    if media_type == "movie":
        radarr_data = get_radarr_data(tmdb_id)
        if not radarr_data:
            print(f"[!] Radarr does not have TMDB ID {tmdb_id} yet.")
            return False

        title = radarr_data["title"]
        year = radarr_data.get("year", "")
        if radarr_data.get("hasFile", False):
            print(f"[OK] Movie '{title} ({year})' is already in Radarr library. Skipping.")
            mark_success(tmdb_id, title)
            return True

        print(f"[*] Triggering Radarr Search for Movie: {title} ({year})")
        trigger_radarr_search(radarr_data["id"])
        mark_success(tmdb_id, title)
        return True

    elif media_type == "tv":
        sonarr_data = get_sonarr_data(tvdb_id)
        if not sonarr_data:
            print(f"[!] Sonarr does not have TVDB ID {tvdb_id} yet.")
            return False

        title = sonarr_data["title"]
        seasons_to_fetch = []
        for ext in data.get("extra", []):
            if ext.get("name") == "Requested Seasons":
                val = ext.get("value", "")
                seasons_to_fetch = [int(s.strip()) for s in str(val).split(",") if s.strip().isdigit()]

        for s in seasons_to_fetch:
            if is_duplicate(tmdb_id, s):
                print(f"[OK] TV Show '{title}' Season {s} already in history. Skipping.")
                continue

            print(f"[*] Triggering Sonarr Search for TV Show: {title} Season {s}")
            trigger_sonarr_search(sonarr_data["id"], s)
            mark_success(tmdb_id, title, s)


def worker_thread():
    global request_counter
    os.makedirs(LOGS_DIR, exist_ok=True)
    while True:
        data = download_queue.get()
        if data is None:
            break
        request_counter += 1
        raw_title = data.get("subject", f"Request_{request_counter}")
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', raw_title).strip('_')
        log_file = os.path.join(LOGS_DIR, f"{request_counter}_{safe_title}.log")

        try:
            print(f"[*] Starting Request #{request_counter} -> logging to {log_file}")
            process_request(data, log_file)
        except Exception as e:
            print(f"[ERROR] Exception in worker thread: {e}")
        finally:
            download_queue.task_done()


threading.Thread(target=worker_thread, daemon=True).start()


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    notification_type = data.get("notification_type", "")

    if "Test" in notification_type or "TEST" in notification_type:
        return jsonify({"status": "test_success"}), 200

    if notification_type not in ["REQUEST_APPROVED", "MEDIA_AUTO_APPROVED", "TEST"] and "Approved" not in notification_type:
        return jsonify({"status": "ignored"}), 200

    download_queue.put(data)
    print(f"[*] Payload queued. Queue size: {download_queue.qsize()}")
    return jsonify({"status": "queued"}), 200


if __name__ == '__main__':
    port = int(os.getenv("WEBHOOK_PORT", 5050))
    print(f"[*] Webhook Listener starting on 0.0.0.0:{port}...")
    app.run(host='0.0.0.0', port=port)
