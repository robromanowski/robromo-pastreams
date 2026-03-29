"""
Parser for PA Fish & Boat Commission Class A Wild Trout stream bulletins.
Extracts stream survey data from PDF files into a structured JSON format.
"""

import pdfplumber
import re
import json
import os
from collections import defaultdict

PDFS_DIR = os.path.join(os.path.dirname(__file__), 'pdfs')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'data', 'streams.json')

# Characters representing a null/missing value in the PDFs
NULL_SET = {'\u2014', '\u2013', '\u2212', '\u2015', '—', '–', '-', '—', '—', '–', '—-', '–-'}

# All 67 Pennsylvania counties (lowercase for comparison)
PA_COUNTIES = {
    'adams', 'allegheny', 'armstrong', 'beaver', 'bedford', 'berks', 'blair',
    'bradford', 'bucks', 'butler', 'cambria', 'cameron', 'carbon', 'centre',
    'chester', 'clarion', 'clearfield', 'clinton', 'columbia', 'crawford',
    'cumberland', 'dauphin', 'delaware', 'elk', 'erie', 'fayette', 'forest',
    'franklin', 'fulton', 'greene', 'huntingdon', 'indiana', 'jefferson',
    'juniata', 'lackawanna', 'lancaster', 'lawrence', 'lebanon', 'lehigh',
    'luzerne', 'lycoming', 'mckean', 'mercer', 'mifflin', 'monroe',
    'montgomery', 'montour', 'northampton', 'northumberland', 'perry',
    'philadelphia', 'pike', 'potter', 'schuylkill', 'snyder', 'somerset',
    'sullivan', 'susquehanna', 'tioga', 'union', 'venango', 'warren',
    'washington', 'wayne', 'westmoreland', 'wyoming', 'york',
}


def is_null_val(s):
    s = s.strip()
    return s in NULL_SET or s == '' or re.fullmatch(r'[\u2012-\u2015\-]+', s) is not None


def parse_float(s):
    """Parse a float, returning None for dashes/empty."""
    if not s:
        return None
    s = s.strip()
    if is_null_val(s):
        return None
    cleaned = re.sub(r'[^\d.]', '', s)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_lat_and_brook(text):
    """
    In many newer PDFs, pdfplumber merges the lat and brook trout values:
      '40.26542738.55' → lat=40.265427, brook='38.55'
      '40.811536—'    → lat=40.811536, brook=None
      '40.966944'     → lat=40.966944, brook=None (separate column PDF)
    PA latitudes: XX.XXXXXX (2 integer digits + dot + 6 decimal = 9 chars).
    Returns (lat_float_or_None, brook_str_or_None).
    """
    text = text.strip()
    if not text:
        return None, None
    m = re.match(r'^(\d{2}\.\d{6})(.*)', text)
    if m:
        lat = float(m.group(1))
        remainder = m.group(2).strip()
        brook_str = None if (not remainder or is_null_val(remainder)) else remainder
        return lat, brook_str
    # Not a lat value - might be something else in that column
    return None, text if not is_null_val(text) else None


def group_into_rows(words, top_tolerance=2.5):
    """Group words into rows by their vertical position."""
    rows = defaultdict(list)
    for w in words:
        bucket = round(w['top'] / top_tolerance) * top_tolerance
        rows[bucket].append(w)
    return dict(sorted(rows.items()))


def words_in_x_range(row_words, x_min, x_max):
    """Get all words in a horizontal x range, joined by space."""
    parts = [w['text'] for w in sorted(row_words, key=lambda w: w['x0'])
             if w['x0'] >= x_min and w['x0'] < x_max]
    return ' '.join(parts).strip()


def build_col_ranges(anchors):
    """
    Given a sorted list of (x_position, col_name), build column x ranges as
    (x_min, x_max) for each column using midpoints between adjacent anchors.
    """
    anchors = sorted(anchors, key=lambda a: a[0])
    ranges = {}
    for i, (x, name) in enumerate(anchors):
        x_min = (anchors[i-1][0] + x) / 2 if i > 0 else 0
        x_max = (x + anchors[i+1][0]) / 2 if i < len(anchors) - 1 else 9999
        ranges[name] = (x_min, x_max)
    return ranges


def detect_cols(words, header_top):
    """
    Detect column layout from the header row.
    Returns (format, col_ranges_dict) where col_ranges_dict maps
    col_name → (x_min, x_max).
    """
    # Look at a tight vertical band around the header row
    header_words = [w for w in words if abs(w['top'] - header_top) < 20]

    # --- County (left edge) ---
    county_w = next((w for w in header_words if 'County' in w['text'] and w['x0'] < 150), None)
    if not county_w:
        return None, None

    county_x = county_w['x0']
    merged = county_w['text']  # may be 'County', 'CountyStream', 'CountyStreamSection'

    # --- Stream header (separate word or inferred) ---
    stream_w = next((w for w in header_words if w['text'] == 'Stream'
                     and w['x0'] > county_x + 20), None)
    # Also handle 'StreamSection' merged
    stream_section_merged_w = next(
        (w for w in header_words if w['text'] == 'StreamSection'
         and w['x0'] > county_x + 20), None)

    # --- Section header ---
    section_candidates = [w for w in header_words
                          if ('Section' in w['text'] or w['text'] == 'SectionLimits')
                          and w['x0'] > county_x + 30
                          and w['text'] != 'StreamSection']  # handled separately
    section_w = section_candidates[0] if section_candidates else None

    # --- Limits header (old format only: separate "Limits" word at x<300) ---
    limits_candidates = [w for w in header_words
                         if w['text'] in ('Limits',) and w['x0'] > county_x + 60
                         and w['x0'] < 350]
    limits_w = limits_candidates[0] if limits_candidates else None

    # --- Tributary / Lat/Lon (new format indicators) ---
    trib_w = next((w for w in header_words
                   if 'Tributary' in w['text'] and w['x0'] > 240), None)
    lat_w = next((w for w in header_words
                  if 'Lat' in w['text'] and w['x0'] > 290), None)

    fmt = 'new' if (trib_w or lat_w) else 'old'

    # --- Numeric column headers (ha), (kg/ha), (miles), Year ---
    ha_words = sorted([w for w in header_words
                       if w['text'] in ('ha)', '(kg/ha)') and w['x0'] > 290],
                      key=lambda w: w['x0'])
    miles_w = next((w for w in header_words
                    if 'miles' in w['text'].lower() and w['x0'] > 350), None)
    year_w = next((w for w in header_words
                   if w['text'].lower() == 'year' and w['x0'] > 400), None)

    # Also look for the multi-line 'LengthSurvey' merged word
    if not year_w:
        ls_w = next((w for w in header_words
                     if 'LengthSurvey' in w['text'] or 'Survey' in w['text']), None)
        if ls_w and ls_w['x0'] > 400:
            year_w = ls_w  # use as proxy for year column start

    # --- Build anchor list ---
    # Anchors are (x_position, col_name) pairs.
    # 'county' is always first.
    anchors = [(county_x, 'county')]

    if fmt == 'new':
        # New format: county | stream | section_limits | tributary | lat_lon | brook | brown | rainbow | length | year
        # Note: section number and section limits text share one column ('section_limits'),
        # split later in finalize_record.

        if stream_w:
            anchors.append((stream_w['x0'], 'stream'))
        elif stream_section_merged_w:
            # StreamSection merged: stream data starts here
            anchors.append((stream_section_merged_w['x0'], 'stream'))
            # Section estimated from Limits header or Tributary position
            if limits_w:
                sec_est = limits_w['x0'] - 28
            elif trib_w:
                sec_est = trib_w['x0'] - 65
            else:
                sec_est = stream_section_merged_w['x0'] + 55
            anchors.append((sec_est, 'section_limits'))
        else:
            # Estimate stream from section/trib positions
            section_x = section_w['x0'] if section_w else (
                trib_w['x0'] - 90 if trib_w else county_x + 120)
            stream_est = county_x + (section_x - county_x) * 0.45
            anchors.append((stream_est, 'stream'))

        # Section anchor (only add if not already handled above)
        if not stream_section_merged_w:
            if section_w:
                anchors.append((section_w['x0'], 'section_limits'))
            else:
                sec_est = county_x + 115
                anchors.append((sec_est, 'section_limits'))

        # Add explicit limits anchor if available (some hybrid-format PDFs)
        if limits_w and limits_w['x0'] < (trib_w['x0'] if trib_w else 9999):
            anchors.append((limits_w['x0'], 'limits'))

        if trib_w:
            anchors.append((trib_w['x0'], 'tributary'))

        if lat_w:
            anchors.append((lat_w['x0'], 'lat_lon'))
        elif ha_words:
            anchors.append((ha_words[0]['x0'] - 60, 'lat_lon'))

        # brook: first ha) - may be separate or merged with lat
        if len(ha_words) >= 1:
            anchors.append((ha_words[0]['x0'], 'brook'))
        if len(ha_words) >= 2:
            anchors.append((ha_words[1]['x0'], 'brown'))

        # rainbow: (kg/ha) after brown
        rainbow_candidates = [w for w in header_words
                               if '(kg/ha)' in w['text'] and w['x0'] > 400]
        if rainbow_candidates:
            anchors.append((rainbow_candidates[0]['x0'], 'rainbow'))

    else:
        # Old format: county | stream | section | limits | brook | brown | rainbow | length | year

        if stream_w:
            anchors.append((stream_w['x0'], 'stream'))
        else:
            section_x = section_w['x0'] if section_w else (
                limits_w['x0'] - 35 if limits_w else county_x + 125)
            stream_est = county_x + (section_x - county_x) * 0.5
            anchors.append((stream_est, 'stream'))

        if section_w:
            anchors.append((section_w['x0'], 'section'))
        elif 'Section' not in merged:
            anchors.append((county_x + 125, 'section'))

        if limits_w:
            anchors.append((limits_w['x0'], 'limits'))
        else:
            sec_x = section_w['x0'] if section_w else county_x + 125
            anchors.append((sec_x + 32, 'limits'))

        # brook, brown, rainbow
        if len(ha_words) >= 1:
            anchors.append((ha_words[0]['x0'], 'brook'))
        if len(ha_words) >= 2:
            anchors.append((ha_words[1]['x0'], 'brown'))

        rainbow_candidates = [w for w in header_words
                               if '(kg/ha)' in w['text'] and w['x0'] > 350]
        if rainbow_candidates:
            anchors.append((rainbow_candidates[0]['x0'], 'rainbow'))

    # Add length and year
    if miles_w:
        anchors.append((miles_w['x0'], 'length'))
    if year_w:
        anchors.append((year_w['x0'], 'year'))

    # Remove duplicates and sort
    seen_names = set()
    unique_anchors = []
    for x, name in sorted(anchors):
        if name not in seen_names:
            unique_anchors.append((x, name))
            seen_names.add(name)

    col_ranges = build_col_ranges(unique_anchors)
    return fmt, col_ranges


def row_has_biomass(row):
    """Check if a row has any non-null biomass values."""
    for col in ('brook', 'brown', 'rainbow'):
        val = row.get(col, '').strip()
        if val and not is_null_val(val):
            return True
    return False


def parse_page(page, doc_no, pub_year, inherited_fmt=None, inherited_cols=None):
    """
    Parse a single page and return (records, fmt, col_ranges).
    inherited_fmt/inherited_cols: column layout from previous page (for continuation pages).
    """
    words = page.extract_words()

    # Find the header row: "County" (or merged variant) in leftmost column
    county_markers = [w for w in words if 'County' in w['text'] and w['x0'] < 150]

    if county_markers:
        header_top = county_markers[0]['top']
        fmt, col_ranges = detect_cols(words, header_top)
        if not col_ranges:
            return [], inherited_fmt, inherited_cols
    elif inherited_cols:
        # Continuation page: use previous page's column layout
        fmt = inherited_fmt
        col_ranges = inherited_cols
        header_top = -999  # treat entire page as data
    else:
        return [], None, None

    # Get only words in the data area (below header, above footer)
    data_words = [w for w in words if w['top'] > header_top + 8]

    stop_markers = [w for w in data_words if w['text'] == 'Persons']
    if stop_markers:
        stop_top = stop_markers[0]['top']
        data_words = [w for w in data_words if w['top'] < stop_top]

    if not data_words:
        return [], fmt, col_ranges

    # Group words into rows by vertical position
    rows = group_into_rows(data_words, top_tolerance=2.5)

    # Build (row_top, row_dict) pairs
    parsed_rows = []
    for row_top, row_words in rows.items():
        row = {'_top': row_top}
        for col_name, (x_min, x_max) in col_ranges.items():
            row[col_name] = words_in_x_range(row_words, x_min, x_max)
        parsed_rows.append(row)

    # Group rows into records.
    # A new record starts when the 'county' cell is non-empty.
    records = []
    current = None

    for row in parsed_rows:
        county_val = row.get('county', '').strip()
        # Skip page number rows
        if re.match(r'^\d+$', county_val):
            continue

        if county_val and not is_null_val(county_val):
            # Check if this is a multi-county continuation row.
            # Criteria:
            #   1. The county cell is a valid PA county name (not a merged fragment)
            #   2. This row has no biomass values
            #   3. The current record already has biomass data (so it's complete enough
            #      to be the "first" county row, and this row is the 2nd county line)
            #   4. The current record's accumulated stream text is very short (≤2 words),
            #      suggesting the stream name was split across rows.
            is_multi_county = False
            if current is not None:
                cv_clean = county_val.strip().rstrip('/')
                # First county part of current record (before any slash)
                cur_county_first = current['county'][0].strip().rstrip('/').split('/')[0].lower() \
                    if current.get('county') else ''
                if (cv_clean.lower() in PA_COUNTIES
                        and cv_clean.lower() != cur_county_first  # different county = real split-row
                        and not row_has_biomass(row)):
                    # Check current record has biomass
                    current_has_biomass = any(
                        any(v.strip() and not is_null_val(v.strip())
                            for v in current.get(col, []))
                        for col in ('brook', 'brown', 'rainbow')
                    )
                    # Check current record's stream is suspiciously short
                    cur_stream = ' '.join(
                        v for v in current.get('stream', []) if v.strip()
                    ).strip()
                    stream_is_short = len(cur_stream.split()) <= 1
                    if current_has_biomass and stream_is_short:
                        is_multi_county = True

            if is_multi_county:
                # Merge: combine county as "county1/county2" and append other fields
                prev_county = current['county'][0].strip().rstrip('/') if current.get('county') else ''
                current['county'] = [prev_county + '/' + county_val.strip().rstrip('/')]
                for k in list(current.keys()):
                    if k.startswith('_') or k == 'county':
                        continue
                    v = row.get(k, '').strip()
                    if v:
                        current[k].append(v)
            else:
                if current:
                    records.append(finalize_record(current, fmt, doc_no, pub_year))
                current = {k: [v] for k, v in row.items() if not k.startswith('_')}
                current['_fmt'] = fmt
        elif current is not None:
            for k in list(current.keys()):
                if k.startswith('_'):
                    continue
                v = row.get(k, '').strip()
                if v:
                    current[k].append(v)

    if current:
        records.append(finalize_record(current, fmt, doc_no, pub_year))

    return records, fmt, col_ranges


def first_val(raw, key):
    """Get the first non-empty value for a column."""
    vals = raw.get(key, [])
    for v in vals:
        v = v.strip()
        if v:
            return v
    return ''


def join_col(raw, key):
    """Join all values for a column."""
    return ' '.join(v for v in raw.get(key, []) if v.strip()).strip()


def split_section_limits(text):
    """
    In new-format PDFs, section number and limits text share a column.
    Extract the leading section number (1-2 digits) and the rest as limits.
    E.g. '1 Headwaters to Mouth' → ('1', 'Headwaters to Mouth')
    """
    text = text.strip()
    m = re.match(r'^(\d{1,2})\s*(.*)', text)
    if m:
        return m.group(1), m.group(2).strip()
    return '', text


def clean_county(raw_county):
    """
    Strip trailing slashes and validate multi-county 'X/Y' values.
    Keeps 'Snyder/Union' but drops 'Lycoming/UNT' → 'Lycoming'.
    """
    c = raw_county.strip().rstrip('/')
    if '/' in c:
        parts = [p.strip() for p in c.split('/')]
        valid = [p for p in parts if p.lower() in PA_COUNTIES]
        if len(valid) == len(parts):
            return '/'.join(valid)   # all parts valid → keep full form
        return valid[0] if valid else c  # drop invalid second part
    return c


def finalize_record(raw, fmt, doc_no, pub_year):
    county = clean_county(join_col(raw, 'county'))
    stream = join_col(raw, 'stream')

    if fmt == 'new':
        # section_limits column contains both section number and description
        section_limits_text = join_col(raw, 'section_limits')
        section, limits_from_sec = split_section_limits(section_limits_text)
        # If there's an explicit limits column (hybrid format), prefer that
        limits_explicit = join_col(raw, 'limits')
        limits = limits_explicit if limits_explicit else limits_from_sec
    else:
        section = join_col(raw, 'section')
        limits = join_col(raw, 'limits')

    if fmt == 'new':
        tributary = join_col(raw, 'tributary')

        # Parse lat/lon and potentially merged brook trout
        lat_parts = raw.get('lat_lon', [])
        lat = None
        lon = None
        brook_from_lat = None

        if lat_parts:
            lat, brook_from_lat_str = parse_lat_and_brook(lat_parts[0])
            brook_from_lat = parse_float(brook_from_lat_str) if brook_from_lat_str else None
            if len(lat_parts) > 1:
                lon_text = lat_parts[1].strip()
                m = re.match(r'^(\d{2}\.\d{6})', lon_text)
                if m:
                    lon = -float(m.group(1))  # W longitude → negative

        # Brook trout: prefer merged value, fall back to separate column
        brook_col_str = first_val(raw, 'brook')
        if brook_from_lat is not None:
            brook = brook_from_lat
        else:
            brook = parse_float(brook_col_str)

        brown = parse_float(first_val(raw, 'brown'))
        rainbow = parse_float(first_val(raw, 'rainbow'))

    else:  # old format
        tributary = None
        lat = None
        lon = None
        brook = parse_float(first_val(raw, 'brook'))
        brown = parse_float(first_val(raw, 'brown'))
        rainbow = parse_float(first_val(raw, 'rainbow'))

    length = parse_float(first_val(raw, 'length'))

    year_str = first_val(raw, 'year')
    survey_year = None
    m = re.search(r'(\d{4})', year_str)
    if m:
        survey_year = int(m.group(1))

    # Derived
    vals = [v for v in [brook, brown, rainbow] if v is not None]
    total_biomass = round(sum(vals), 2) if vals else None

    species = []
    if brook:
        species.append('Brook')
    if brown:
        species.append('Brown')
    if rainbow:
        species.append('Rainbow')

    if not species:
        dominant = 'Unknown'
    elif len(species) == 1:
        dominant = species[0]
    else:
        dominant = 'Mixed (' + '+'.join(species) + ')'

    return {
        'county': county,
        'stream': stream,
        'section': section,
        'limits': limits,
        'tributary_to': tributary,
        'latitude': round(lat, 6) if lat else None,
        'longitude': round(lon, 6) if lon else None,
        'brook_trout_kg_ha': brook,
        'brown_trout_kg_ha': brown,
        'rainbow_trout_kg_ha': rainbow,
        'total_biomass_kg_ha': total_biomass,
        'dominant_species': dominant,
        'length_miles': length,
        'survey_year': survey_year,
        'bulletin_doc': doc_no,
        'bulletin_year': pub_year,
    }


def parse_pdf(filepath):
    doc_match = re.search(r'(\d+)-(\d+)', os.path.basename(filepath))
    if doc_match:
        doc_no = doc_match.group(0)
        pub_year = int(doc_match.group(1))
        if pub_year < 100:
            pub_year += 2000
    else:
        doc_no = 'unknown'
        pub_year = None

    records = []
    last_fmt = None
    last_cols = None
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_records, last_fmt, last_cols = parse_page(
                page, doc_no, pub_year, last_fmt, last_cols)
            records.extend(page_records)

    # Deduplicate within the same bulletin
    seen = set()
    unique = []
    for r in records:
        key = (r['county'], r['stream'], r['section'], r['bulletin_doc'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def validate_record(r):
    """Sanity check: must look like a real stream survey record."""
    if not r['county'] or not r['stream']:
        return False

    # County must start with a valid PA county name (handles "Blair/Huntingdon" etc.)
    county_first = re.split(r'[/\s]', r['county'].strip())[0].lower()
    if county_first not in PA_COUNTIES:
        return False

    # Stream name should be a reasonable string
    if len(r['stream']) > 80:
        return False
    # Reject obvious sentence fragments (words that only appear in body text, not stream names)
    if re.search(r'\b(respect|exhibition|fishing|commission|biomass|pursuant)\b',
                 r['stream'].lower()):
        return False

    # Must have at least one valid biomass value
    if (r['brook_trout_kg_ha'] is None and
            r['brown_trout_kg_ha'] is None and
            r['rainbow_trout_kg_ha'] is None):
        return False

    # Biomass values should be in plausible range (0-500 kg/ha)
    for key in ('brook_trout_kg_ha', 'brown_trout_kg_ha', 'rainbow_trout_kg_ha'):
        v = r[key]
        if v is not None and (v <= 0 or v > 500):
            return False

    # Survey year should be reasonable
    if r['survey_year'] and (r['survey_year'] < 1990 or r['survey_year'] > 2030):
        return False

    # Length should be reasonable (0.1 to 30 miles)
    if r['length_miles'] is not None and (r['length_miles'] <= 0 or r['length_miles'] > 50):
        return False

    return True


# PA coordinate patterns: lat 39–42°N, lon 74–81°W, always XX.XXXXXX
_LON_PAT = re.compile(r'(7[4-9]|8[01])\.\d{6}')
_LAT_PAT = re.compile(r'(3[9-9]|4[0-2])\.\d{6}')
# String fields that could accidentally absorb a coordinate word
_COORD_RESCUE_FIELDS = ('tributary_to', 'limits', 'section')


def rescue_embedded_coordinates(records):
    """
    If lat or lon is missing but a PA coordinate value is embedded in an
    adjacent string field (column boundary misalignment in PDF), extract
    it and clean that field.
    """
    fixed = 0
    for r in records:
        missing_lon = r.get('longitude') is None
        missing_lat = r.get('latitude') is None
        if not missing_lon and not missing_lat:
            continue
        for field in _COORD_RESCUE_FIELDS:
            val = r.get(field)
            if not isinstance(val, str):
                continue
            if missing_lon:
                m = _LON_PAT.search(val)
                if m:
                    r['longitude'] = -round(float(m.group()), 6)
                    r[field] = (val[:m.start()] + val[m.end():]).strip()
                    missing_lon = False
                    fixed += 1
            if missing_lat:
                m = _LAT_PAT.search(val)
                if m:
                    r['latitude'] = round(float(m.group()), 6)
                    r[field] = (val[:m.start()] + val[m.end():]).strip()
                    missing_lat = False
                    fixed += 1
            if not missing_lon and not missing_lat:
                break
    return fixed


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    all_records = []
    pdf_files = sorted(f for f in os.listdir(PDFS_DIR) if f.endswith('.pdf'))

    for fname in pdf_files:
        fpath = os.path.join(PDFS_DIR, fname)
        print(f'Parsing {fname}...')
        try:
            records = parse_pdf(fpath)
            valid = [r for r in records if validate_record(r)]
            print(f'  -> {len(valid)} valid records ({len(records) - len(valid)} filtered)')
            all_records.extend(valid)
        except Exception as e:
            import traceback
            print(f'  ERROR: {e}')
            traceback.print_exc()

    fixed = rescue_embedded_coordinates(all_records)
    if fixed:
        print(f'\nRescued coordinates from adjacent columns for {fixed} records')

    # Sort by total biomass descending
    all_records.sort(key=lambda r: (-(r['total_biomass_kg_ha'] or 0), r['county'] or ''))

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    print(f'\nDone. {len(all_records)} total records -> {OUTPUT_PATH}')

    species_counts = {}
    for r in all_records:
        s = r['dominant_species']
        species_counts[s] = species_counts.get(s, 0) + 1
    print('\nSpecies breakdown:')
    for s, c in sorted(species_counts.items(), key=lambda x: -x[1]):
        print(f'  {s}: {c}')


if __name__ == '__main__':
    main()
