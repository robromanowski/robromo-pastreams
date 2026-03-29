#!/usr/bin/env python3
"""
Fetch NHD flowline geometry for PA Class A wild trout streams.
Queries the USGS NHD REST service, matches streams by name + proximity,
and writes data/stream_lines.geojson.

Resumable: already-matched streams are skipped on re-run.
Requires: pip install requests
"""

import json
import time
import re
import os
import math
import requests
from difflib import SequenceMatcher

STREAMS_JSON = os.path.join(os.path.dirname(__file__), 'data', 'streams.json')
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), 'data', 'stream_lines.geojson')

NHD_URL = 'https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query'

# Slower = more reliable. The API throttles hard above ~1 req/sec.
REQUEST_DELAY = 1.0   # seconds between requests
TIMEOUT       = 20    # seconds per request (fail fast, then retry)


# ---------------------------------------------------------------------------
def name_sim(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def simplify(name):
    """Strip stream-type words so 'Pine Run' ~ 'Pine Creek'."""
    s = name.lower().strip()
    s = re.sub(r'\b(creek|run|branch|river|stream|tributary|hollow|spring|fork|'
               r'prong|kill|lick|gut|swamp|pond|lake|reservoir)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def is_unt(name):
    return bool(re.match(r'^(unt\b|unnamed)', name.strip().lower()))


def get_attr(feat, *keys):
    """Case-insensitive attribute lookup — NHD returns lowercase field names."""
    attrs = feat.get('attributes', {})
    for k in keys:
        v = attrs.get(k) or attrs.get(k.lower()) or attrs.get(k.upper())
        if v:
            return str(v).strip()
    return ''


def stream_key(s):
    return '|'.join([
        s.get('county', ''), s.get('stream', ''),
        s.get('section', ''), s.get('bulletin_doc', ''),
    ])


def nhd_request(params, timeout=TIMEOUT):
    """Single NHD request with retries and exponential backoff."""
    for attempt in range(4):
        try:
            r = requests.get(NHD_URL, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if 'error' in data:
                raise RuntimeError(f"API error: {data['error']}")
            return data
        except requests.exceptions.Timeout:
            wait = 2 ** attempt * 3   # 3, 6, 12, 24s
            if attempt < 3:
                print(f"[timeout, retry in {wait}s] ", end='', flush=True)
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt * 2
            if attempt < 3:
                print(f"[{e}, retry in {wait}s] ", end='', flush=True)
                time.sleep(wait)
            else:
                raise


def nhd_near_point(lat, lon, radius_m):
    """NHD flowline attributes (no geometry) within bbox around point."""
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * math.cos(math.radians(lat)))
    envelope = f"{lon-dlon:.6f},{lat-dlat:.6f},{lon+dlon:.6f},{lat+dlat:.6f}"
    data = nhd_request({
        'geometry':       envelope,
        'geometryType':   'esriGeometryEnvelope',
        'inSR':           '4326',
        'spatialRel':     'esriSpatialRelIntersects',
        'outFields':      'GNIS_NAME,GNIS_ID',
        'returnGeometry': 'false',
        'f':              'json',
    })
    return data.get('features', [])


def nhd_by_gnis_id(gnis_id):
    """All flowline segments for a given GNIS_ID, with geometry."""
    data = nhd_request({
        'where':          f"GNIS_ID='{gnis_id}'",
        'outFields':      'GNIS_NAME,GNIS_ID',
        'returnGeometry': 'true',
        'outSR':          '4326',
        'f':              'geojson',
    }, timeout=45)
    return data.get('features', [])


def best_match(stream_name, candidates):
    """Return (gnis_id, score) for the best-scoring NHD candidate."""
    best_id, best_score = None, 0.0
    for feat in candidates:
        nhd_name = get_attr(feat, 'GNIS_NAME')
        gnis_id  = get_attr(feat, 'GNIS_ID')
        if not nhd_name or not gnis_id:
            continue
        score = max(
            name_sim(stream_name, nhd_name),
            name_sim(simplify(stream_name), simplify(nhd_name)),
        )
        if score > best_score:
            best_score, best_id = score, gnis_id
    return best_id, best_score


def segments_to_multiline(seg_features):
    coords = []
    for seg in seg_features:
        geom = seg.get('geometry', {})
        t = geom.get('type', '')
        if t == 'LineString':
            coords.append(geom['coordinates'])
        elif t == 'MultiLineString':
            coords.extend(geom['coordinates'])
    return coords


def load_existing():
    """Load already-matched keys from the output file (for resuming)."""
    if not os.path.exists(OUTPUT_PATH):
        return {}, []
    try:
        with open(OUTPUT_PATH, encoding='utf-8') as f:
            gj = json.load(f)
        features = gj.get('features', [])
        done = {f['properties']['key'] for f in features if f.get('properties', {}).get('key')}
        return done, features
    except Exception:
        return {}, []


def save(features):
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


# ---------------------------------------------------------------------------
def check_api():
    print("Checking NHD API... ", end='', flush=True)
    try:
        feats = nhd_near_point(41.45, -77.46, radius_m=3000)
        named = [get_attr(f, 'GNIS_NAME') for f in feats if get_attr(f, 'GNIS_NAME')]
        if named:
            print(f"OK ({len(feats)} features, e.g. {named[:3]})")
            return True
        print(f"WARNING — {len(feats)} features but none named. Check layer.")
        return False
    except Exception as e:
        print(f"FAILED — {e}")
        return False


def main():
    if not check_api():
        print("Aborting.")
        return

    with open(STREAMS_JSON, encoding='utf-8') as f:
        streams = json.load(f)

    # Resume: skip streams already in the output file
    done_keys, features = load_existing()
    if done_keys:
        print(f"Resuming — {len(done_keys)} streams already matched\n")

    to_process = [s for s in streams if s.get('latitude') and s.get('longitude')]
    todo = [s for s in to_process if stream_key(s) not in done_keys]
    print(f"{len(todo)} streams to process ({len(to_process)} total, {len(done_keys)} already done)\n")

    matched = skipped = 0
    SAVE_EVERY = 25  # write to disk every N matched streams

    for i, s in enumerate(todo):
        lat  = s['latitude']
        lon  = s['longitude']
        name = s.get('stream', '')
        key  = stream_key(s)

        print(f"[{i+1}/{len(todo)}] {name} ({s.get('county')}) ... ", end='', flush=True)

        # Skip unnamed tributaries — no GNIS name to match against
        if is_unt(name):
            skipped += 1
            print("skip (UNT)")
            continue

        # Step 1: find candidates near the point
        try:
            candidates = nhd_near_point(lat, lon, radius_m=3000)
            time.sleep(REQUEST_DELAY)

            # Wider search if needed (e.g. multi-county streams where point is near boundary)
            if not candidates or best_match(name, candidates)[1] < 0.55:
                wider = nhd_near_point(lat, lon, radius_m=8000)
                time.sleep(REQUEST_DELAY)
                if wider:
                    candidates = wider

        except Exception as e:
            skipped += 1
            print(f"ERROR: {e}")
            time.sleep(3)
            continue

        gnis_id, score = best_match(name, candidates)

        if not gnis_id or score < 0.55:
            skipped += 1
            print(f"no match (best={score:.2f})")
            continue

        # Step 2: fetch full geometry by GNIS_ID
        try:
            segs = nhd_by_gnis_id(gnis_id)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            skipped += 1
            print(f"ERROR fetching geometry: {e}")
            time.sleep(3)
            continue

        coords = segments_to_multiline(segs)
        if not coords:
            skipped += 1
            print("matched but no geometry")
            continue

        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": coords},
            "properties": {
                "key":                key,
                "stream":             name,
                "county":             s.get('county', ''),
                "section":            s.get('section', ''),
                "limits":             s.get('limits', ''),
                "dominant_species":   s.get('dominant_species', ''),
                "brook_trout_kg_ha":  s.get('brook_trout_kg_ha'),
                "brown_trout_kg_ha":  s.get('brown_trout_kg_ha'),
                "rainbow_trout_kg_ha":s.get('rainbow_trout_kg_ha'),
                "total_biomass_kg_ha":s.get('total_biomass_kg_ha'),
                "length_miles":       s.get('length_miles'),
                "survey_year":        s.get('survey_year'),
                "bulletin_year":      s.get('bulletin_year'),
                "latitude":           lat,
                "longitude":          lon,
                "nhd_match_score":    round(score, 3),
            },
        })
        matched += 1
        print(f"ok  score={score:.2f}  {len(segs)} seg")

        if matched % SAVE_EVERY == 0:
            save(features)
            print(f"  -- saved {len(features)} features so far --")

    save(features)
    print(f"\nDone. {matched} matched, {skipped} skipped -> {OUTPUT_PATH}")
    print(f"Total in file: {len(features)}")


if __name__ == '__main__':
    main()
