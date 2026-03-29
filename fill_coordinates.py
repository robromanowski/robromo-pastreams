#!/usr/bin/env python3
"""
Fill missing lat/lon in streams.json using OSM Nominatim geocoding.

Nominatim is OpenStreetMap's free geocoder — no API key, ~1 req/s rate limit.
For ~90-100 named streams this takes about 2 minutes.

Requires: pip install requests
"""

import json
import os
import re
import time
import requests
from difflib import SequenceMatcher

STREAMS_JSON = os.path.join(os.path.dirname(__file__), 'data', 'streams.json')

# PA bounding box — reject results outside this
PA_LAT = (39.5, 42.5)
PA_LON = (-80.6, -74.6)

HEADERS = {'User-Agent': 'PA-WildTrout-StreamFinder/1.0 (research)'}

MATCH_THRESHOLD = 0.60


def name_sim(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def is_unt(name):
    return bool(re.match(r'^(unt\b|unnamed)', name.strip().lower()))


def in_pa(lat, lon):
    return PA_LAT[0] <= lat <= PA_LAT[1] and PA_LON[0] <= lon <= PA_LON[1]


def geocode(stream_name, county):
    """
    Query Nominatim for a stream name in a PA county.
    Returns (lat, lon) or None.
    """
    # Try specific county query first, then just stream + Pennsylvania
    queries = [
        f"{stream_name}, {county} County, Pennsylvania, USA",
        f"{stream_name}, Pennsylvania, USA",
    ]
    for q in queries:
        try:
            r = requests.get(
                'https://nominatim.openstreetmap.org/search',
                params={'q': q, 'format': 'json', 'limit': 5,
                        'countrycodes': 'us'},
                headers=HEADERS,
                timeout=15,
            )
            r.raise_for_status()
            results = r.json()

            # Prefer waterway/natural results in PA
            for res in results:
                lat = float(res['lat'])
                lon = float(res['lon'])
                if not in_pa(lat, lon):
                    continue
                cls = res.get('class', '')
                typ = res.get('type', '')
                # Waterway or natural features are best matches
                if cls in ('waterway', 'natural') or typ in ('water', 'stream',
                                                              'river', 'creek'):
                    return lat, lon

            # Fall back to any PA result whose display name contains the stream name
            for res in results:
                lat = float(res['lat'])
                lon = float(res['lon'])
                if not in_pa(lat, lon):
                    continue
                display = res.get('display_name', '')
                if name_sim(stream_name, display.split(',')[0]) >= MATCH_THRESHOLD:
                    return lat, lon

        except Exception:
            pass

        time.sleep(1.1)  # Nominatim rate limit: 1 req/s

    return None


def main():
    with open(STREAMS_JSON, encoding='utf-8') as f:
        streams = json.load(f)

    missing = [s for s in streams if not s.get('latitude') or not s.get('longitude')]
    print(f"{len(missing)} streams missing coordinates\n")

    matched = skipped = not_found = 0

    for i, s in enumerate(missing):
        name = s.get('stream', '')
        county_raw = s.get('county', '')
        # Use first county for multi-county streams
        county = county_raw.split('/')[0].strip()

        print(f"[{i+1}/{len(missing)}] {name} ({county_raw}) ... ", end='', flush=True)

        if is_unt(name):
            skipped += 1
            print("skip (UNT)")
            continue

        result = geocode(name, county)
        time.sleep(1.1)  # ensure rate limit between streams

        if result:
            lat, lon = result
            s['latitude']  = round(lat, 6)
            s['longitude'] = round(lon, 6)
            matched += 1
            print(f"ok  ({lat:.4f}, {lon:.4f})")
        else:
            not_found += 1
            print("no match")

    with open(STREAMS_JSON, 'w', encoding='utf-8') as f:
        json.dump(streams, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {matched} matched, {skipped} skipped (UNT), {not_found} not found")
    print(f"Updated {STREAMS_JSON}")


if __name__ == '__main__':
    main()
