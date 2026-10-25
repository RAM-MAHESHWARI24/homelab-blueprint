#!/usr/bin/env python3
"""
Sonarr Season Pack Preference Setup
Adds custom formats for season pack preference to 1080p Compact profile
WITHOUT overwriting any existing settings or sizes.
"""

import os
import requests
import json
import sys

# Configuration via environment variables
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "YOUR_SONARR_API_KEY")
QUALITY_PROFILE = os.getenv("QUALITY_PROFILE", "1080p Compact")


def get_quality_profiles():
    """Get all quality profiles"""
    url = f"{SONARR_URL}/api/v3/qualityprofile"
    headers = {"X-Api-Key": SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    return response.json()


def get_custom_formats():
    """Get all custom formats"""
    url = f"{SONARR_URL}/api/v3/customformat"
    headers = {"X-Api-Key": SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    return response.json()


def add_custom_format(name, spec_pattern):
    """Add a new custom format"""
    url = f"{SONARR_URL}/api/v3/customformat"
    headers = {
        "X-Api-Key": SONARR_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "name": name,
        "includeCustomFormatWhenRenaming": False,
        "specifications": [
            {
                "name": "Release Name",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": False,
                "fields": [
                    {
                        "order": 0,
                        "name": "value",
                        "label": "Regular Expression",
                        "value": spec_pattern,
                        "type": "textbox",
                        "advanced": False
                    }
                ]
            }
        ]
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 201:
        print(f"✓ Created custom format: {name}")
        return response.json()
    else:
        print(f"✗ Failed to create {name}: {response.text}")
        return None


def update_quality_profile_scoring(profile_id, new_formats):
    """Update quality profile with custom format scores"""
    url = f"{SONARR_URL}/api/v3/qualityprofile/{profile_id}"
    headers = {
        "X-Api-Key": SONARR_API_KEY,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)
    profile = response.json()

    format_items = list(profile.get('formatItems', []))

    for format_name, format_id in new_formats:
        if not any(item.get('format') == format_id for item in format_items):
            score = 100 if "Season" in format_name else 50
            format_items.append({
                "format": format_id,
                "name": format_name,
                "score": score
            })
        else:
            for item in format_items:
                if item.get('format') == format_id:
                    item['score'] = 100 if "Season" in format_name else 50

    profile['formatItems'] = format_items

    response = requests.put(url, json=profile, headers=headers)
    if response.status_code == 200:
        print(f"✓ Updated quality profile: {profile['name']}")
        return True
    else:
        print(f"✗ Failed to update profile: {response.text}")
        return False


def main():
    print("=" * 60)
    print("Sonarr Season Pack Preference Setup")
    print("=" * 60)

    print("\n[1] Fetching quality profiles...")
    profiles = get_quality_profiles()
    target_profile = None
    for profile in profiles:
        print(f"  - {profile['name']} (ID: {profile['id']})")
        if profile['name'] == QUALITY_PROFILE:
            target_profile = profile

    if not target_profile:
        print(f"\n✗ Error: Could not find '{QUALITY_PROFILE}' profile")
        return False

    print(f"✓ Found target profile: {target_profile['name']} (ID: {target_profile['id']})")

    print("\n[2] Checking existing custom formats...")
    custom_formats = get_custom_formats()
    existing_names = {cf['name']: cf['id'] for cf in custom_formats}
    print(f"✓ Found {len(custom_formats)} existing custom formats")

    season_formats = {
        "Season Complete": r"(?i)(season.complete|season.pack|complete.season|full.season)",
        "Multi Episode": r"(?i)(s\d{2}e\d{2}).*(s\d{2}e\d{2})"
    }

    print("\n[3] Creating/checking custom formats...")
    format_list = []

    for format_name, pattern in season_formats.items():
        if format_name in existing_names:
            print(f"✓ Custom format already exists: {format_name}")
            format_id = existing_names[format_name]
        else:
            print(f"  Creating custom format: {format_name}")
            cf = add_custom_format(format_name, pattern)
            if cf:
                format_id = cf['id']
            else:
                continue

        format_list.append((format_name, format_id))

    print(f"\n[4] Updating '{QUALITY_PROFILE}' with season pack scoring...")
    print("  - Season Complete: +100 points")
    print("  - Multi Episode: +50 points")

    if update_quality_profile_scoring(target_profile['id'], format_list):
        print("\n" + "=" * 60)
        print("✓ SUCCESS: Season pack preference configured!")
        print("=" * 60)
        return True
    else:
        print("\n✗ Failed to update quality profile")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
