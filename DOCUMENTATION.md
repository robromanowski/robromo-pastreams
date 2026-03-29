# Smokies Streams Map Documentation

This document explains the main architecture of the app and includes the full code blocks for the most relevant parts pulled directly from `index.html`.

## Overview

- `init()` is the main controller.
- `renderStreams()` is the main renderer inside `init()`.
- OpenStreetMap geometry is fetched with Overpass.
- Park boundary clipping is done client-side.
- Elevation profiles are built from sampled stream geometry plus Open-Meteo elevation data.

## Included Code Blocks

### `const COLORS =`

```js
    const COLORS = {
      excellent: getComputedStyle(document.documentElement).getPropertyValue('--excellent').trim(),
      'very good': getComputedStyle(document.documentElement).getPropertyValue('--very-good').trim(),
      good: getComputedStyle(document.documentElement).getPropertyValue('--good').trim(),
      fair: getComputedStyle(document.documentElement).getPropertyValue('--fair').trim(),
      poor: getComputedStyle(document.documentElement).getPropertyValue('--poor').trim(),
      unknown: getComputedStyle(document.documentElement).getPropertyValue('--unknown').trim(),
    };

    const GRADE_ORDER = ['excellent', 'very good', 'good', 'fair', 'poor'];
    const GRADE_RANK = {
      excellent: 0,
      'very good': 1,
      good: 2,
      fair: 3,
      poor: 4,
    };
    const STREAM_MATCH_OVERRIDES = {
      'east prong little river': {
        fallbackNameKey: 'little river',
        nearNameKeys: ['jake s creek', 'jakes creek'],
        maxDistanceM: 16000,
        branchHint: 'east',
        minSeedDistanceM: 250,
        seedDistanceM: 2400,
        seedTopN: 1,
        splitGuardM: 320,
        connectDistanceM: 520,
        hardGate: false,
      },
    };
    const STREAM_HARD_GATES = {
      // Force-trim at Gatlinburg park edge for the remaining overrun.
      'west prong little pigeon river': { maxLat: 35.72 },
    };
    const GSMNP_BBOX = [35.42, -84.16, 35.82, -83.07];

    const map = L.map('map', {
      preferCanvas: true,
      zoomControl: true,
    }).setView([35.62, -83.54], 10);
    map.createPane('slopePane');
    map.getPane('slopePane').style.zIndex = 650;
    map.getPane('slopePane').style.pointerEvents = 'none';

    const baseLayers = {
      'Street (OSM)': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }),
      'Street (Positron)': L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 20,
        subdomains: 'abcd',
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
      }),
      'Street (Voyager)': L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 20,
        subdomains: 'abcd',
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
      }),
      'Terrain (Topo)': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        maxZoom: 17,
        attribution: 'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap'
      }),
      Satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19,
        attribution: 'Tiles &copy; Esri'
      }),
      Dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 20,
        subdomains: 'abcd',
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
      }),
    };

    baseLayers['Street (OSM)'].addTo(map);
    L.control.layers(baseLayers, null, { position: 'topright', collapsed: true }).addTo(map);

    const streamLayerGroup = L.layerGroup().addTo(map);
    const slopeLayerGroup = L.layerGroup().addTo(map);
    const labelLayerGroup = L.layerGroup().addTo(map);
    let profileMarker = null;
    const elevationCache = new Map();
    let activeProfileToken = 0;
    const PROFILE_MAX_POINTS = 120;
    const PROFILE_POINT_SPACING_M = 40;
    const ELEVATION_CHUNK_SIZE = 100;
    const GRADE_MIN_SEGMENT_M = 20;
    const PARK_CLIP_STEP_M = 10;
    const PARK_BOUNDARY_CACHE_KEY = 'smokiesParkBoundaryPolygonsV1';
    const PARK_BOUNDARY_CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 14;

    function haversineMeters(a, b) {
      const r = 6371000;
      const toRad = (v) => (v * Math.PI) / 180;
      const dLat = toRad(b.lat - a.lat);
      const dLon = toRad(b.lng - a.lng);
      const lat1 = toRad(a.lat);
      const lat2 = toRad(b.lat);
      const aa = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
      return 2 * r * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
    }
```

### `function fixEncoding`

```js
    function fixEncoding(text = '') {
      const value = String(text);
      try {
        return decodeURIComponent(escape(value));
      } catch (e) {
        return value;
      }
    }
```

### `function normalizeName`

```js
    function normalizeName(name = '') {
      return fixEncoding(name)
        .toLowerCase()
        .replace(/\b(the|of)\b/g, ' ')
        .replace(/[^a-z0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    }
```

### `function gradeFromQuality`

```js
    function gradeFromQuality(rawQuality = '') {
      const q = fixEncoding(rawQuality).toLowerCase();

      if (q.includes('excellent') || q.includes('best in the park')) return 'excellent';
      if (q.includes('very good')) return 'very good';
      if (q.includes('good') || q.includes('fairly good')) return 'good';
      if (q.includes('fair') || q.includes('fish are small but plentiful')) return 'fair';
      if (q.includes('poor') || q.includes('marginal') || q.includes('questionable') || q.includes('worse')) return 'poor';
      return 'unknown';
    }
```

### `async function fetchOSMWaterways`

```js
    async function fetchOSMWaterways() {
      const [s, w, n, e] = GSMNP_BBOX;
      const bboxQuery = `
[out:json][timeout:60];
(
  way["waterway"]["name"](${s},${w},${n},${e});
  relation["waterway"]["name"](${s},${w},${n},${e});
);
out body geom;
      `.trim();
      const parkAreaQuery = `
[out:json][timeout:90];
rel["boundary"="national_park"]["name"="Great Smoky Mountains National Park"]->.park;
map_to_area.park->.parkArea;
(
  way["waterway"]["name"](area.parkArea);
  relation["waterway"]["name"](area.parkArea);
);
out body geom;
      `.trim();

      const endpoints = [
        'https://overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
      ];

      let lastError = null;

      for (const endpoint of endpoints) {
        for (const query of [parkAreaQuery, bboxQuery]) {
          try {
            const resp = await fetch(endpoint, {
              method: 'POST',
              headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
              body: `data=${encodeURIComponent(query)}`,
            });

            if (!resp.ok) throw new Error(`Overpass failed (${resp.status})`);
            const data = await resp.json();
            if (Array.isArray(data.elements) && data.elements.length > 0) return data;
            lastError = new Error('No waterways returned');
          } catch (err) {
            lastError = err;
          }
        }
      }

      throw lastError || new Error('Overpass unavailable');
    }
```

### `async function fetchParkBoundaryPolygons`

```js
    async function fetchParkBoundaryPolygons() {
      try {
        const cachedRaw = localStorage.getItem(PARK_BOUNDARY_CACHE_KEY);
        if (cachedRaw) {
          const cached = JSON.parse(cachedRaw);
          if (cached && Array.isArray(cached.polygons) && cached.polygons.length && (Date.now() - (cached.ts || 0) < PARK_BOUNDARY_CACHE_TTL_MS)) {
            return cached.polygons;
          }
        }
      } catch (e) {
        // ignore cache parse failures
      }

      const url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&polygon_geojson=1&polygon_threshold=0&countrycodes=us&limit=8&q=Great%20Smoky%20Mountains%20National%20Park';
      try {
        const resp = await fetch(url, { headers: { Accept: 'application/json' } });
        if (!resp.ok) throw new Error(`Nominatim failed (${resp.status})`);
        const data = await resp.json();
        if (!Array.isArray(data) || !data.length) return [];

        const preferred = data.find((d) => {
          const cls = String(d.class || '').toLowerCase();
          const typ = String(d.type || '').toLowerCase();
          const name = String(d.display_name || '').toLowerCase();
          return (
            (typ.includes('national_park') || typ.includes('protected_area') || typ.includes('park')) &&
            (cls.includes('boundary') || cls.includes('leisure') || cls.includes('place')) &&
            name.includes('great smoky mountains national park') &&
            d.geojson
          );
        }) || data.find((d) => d.geojson);

        if (!preferred || !preferred.geojson) return [];
        const gj = preferred.geojson;
        if (gj.type === 'Polygon' && Array.isArray(gj.coordinates)) {
          const polygons = [gj.coordinates];
          try { localStorage.setItem(PARK_BOUNDARY_CACHE_KEY, JSON.stringify({ ts: Date.now(), polygons })); } catch (e) {}
          return polygons;
        }
        if (gj.type === 'MultiPolygon' && Array.isArray(gj.coordinates)) {
          const polygons = gj.coordinates;
          try { localStorage.setItem(PARK_BOUNDARY_CACHE_KEY, JSON.stringify({ ts: Date.now(), polygons })); } catch (e) {}
          return polygons;
        }
      } catch (e) {
        return [];
      }
      return [];
    }
```

### `function pointInRing`

```js
    function pointInRing(point, ring) {
      const y = point[0];
      const x = point[1];
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        // GeoJSON rings are [lon, lat], while point is [lat, lon].
        const yi = ring[i][1];
        const xi = ring[i][0];
        const yj = ring[j][1];
        const xj = ring[j][0];
        const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    }
```

### `function pointInPolygon`

```js
    function pointInPolygon(point, polygon) {
      if (!Array.isArray(polygon) || !polygon.length) return false;
      const outer = polygon[0];
      if (!pointInRing(point, outer)) return false;
      for (let i = 1; i < polygon.length; i += 1) {
        if (pointInRing(point, polygon[i])) return false;
      }
      return true;
    }
```

### `function pointInPark`

```js
    function pointInPark(point, parkPolygons) {
      if (!parkPolygons || !parkPolygons.length) return true;
      return parkPolygons.some((poly) => pointInPolygon(point, poly));
    }
```

### `function sampleSegment`

```js
    function sampleSegment(a, b, stepM) {
      const dist = haversineMeters({ lat: a[0], lng: a[1] }, { lat: b[0], lng: b[1] });
      const samples = [];
      if (dist <= stepM) return [b];
      const n = Math.max(1, Math.ceil(dist / stepM));
      for (let i = 1; i <= n; i += 1) {
        const t = i / n;
        samples.push([
          a[0] + (b[0] - a[0]) * t,
          a[1] + (b[1] - a[1]) * t,
        ]);
      }
      return samples;
    }
```

### `function clipPolylineToPark`

```js
    function clipPolylineToPark(latlngs, parkPolygons) {
      if (!parkPolygons || !parkPolygons.length) return [latlngs];
      // Fast path: if all vertices are already inside park, skip expensive dense sampling.
      let allInside = true;
      for (const p of latlngs) {
        if (!pointInPark([p[0], p[1]], parkPolygons)) {
          allInside = false;
          break;
        }
      }
      if (allInside) return [latlngs];

      const runs = [];
      let current = [];
      const stepM = PARK_CLIP_STEP_M;

      for (let i = 1; i < latlngs.length; i += 1) {
        const start = latlngs[i - 1];
        const segPoints = [[start[0], start[1]], ...sampleSegment(start, latlngs[i], stepM)];
        for (const p of segPoints) {
          const inside = pointInPark([p[0], p[1]], parkPolygons);
          if (inside) {
            current.push([p[0], p[1]]);
          } else if (current.length) {
            if (current.length > 1) runs.push(current);
            current = [];
          }
        }
      }
      if (current.length > 1) runs.push(current);
      return runs;
    }
```

### `function applyStreamHardGateRuns`

```js
    function applyStreamHardGateRuns(runs, streamNameKey) {
      const gate = STREAM_HARD_GATES[streamNameKey];
      if (!gate) return runs;
      const out = [];
      for (const run of runs) {
        let current = [];
        for (const p of run) {
          const inside = gate.maxLat !== undefined ? p[0] <= gate.maxLat : true;
          if (inside) current.push(p);
          else if (current.length) {
            if (current.length > 1) out.push(current);
            current = [];
          }
        }
        if (current.length > 1) out.push(current);
      }
      return out;
    }
```

### `function buildOsmNameIndex`

```js
    function buildOsmNameIndex(elements) {
      const index = new Map();

      for (const el of elements) {
        const rawName = el.tags?.name;
        if (!rawName) continue;

        const key = normalizeName(rawName);
        if (!index.has(key)) index.set(key, []);
        index.get(key).push(el);
      }

      return index;
    }
```

### `function coordinatesForElement`

```js
    function coordinatesForElement(element) {
      if (element.type === 'way' && Array.isArray(element.geometry)) {
        return element.geometry.map((g) => [g.lat, g.lon]);
      }

      if (element.type === 'relation' && Array.isArray(element.members)) {
        return element.members
          .filter((m) => Array.isArray(m.geometry))
          .map((m) => m.geometry.map((g) => [g.lat, g.lon]));
      }

      return [];
    }
```

### `function flattenElementCoords`

```js
    function flattenElementCoords(element) {
      const coords = coordinatesForElement(element);
      const out = [];
      if (!Array.isArray(coords)) return out;

      for (const c of coords) {
        if (Array.isArray(c) && typeof c[0] === 'number' && typeof c[1] === 'number') {
          out.push(c);
        } else if (Array.isArray(c)) {
          for (const p of c) {
            if (Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number') out.push(p);
          }
        }
      }
      return out;
    }
```

### `function centerOfElement`

```js
    function centerOfElement(element) {
      const pts = flattenElementCoords(element);
      if (!pts.length) return null;
      let latSum = 0;
      let lonSum = 0;
      for (const p of pts) {
        latSum += p[0];
        lonSum += p[1];
      }
      return { lat: latSum / pts.length, lng: lonSum / pts.length };
    }
```

### `function minDistanceToAnchors`

```js
    function minDistanceToAnchors(element, anchors) {
      const pts = flattenElementCoords(element);
      if (!pts.length || !anchors.length) return Number.POSITIVE_INFINITY;
      let min = Number.POSITIVE_INFINITY;
      for (const p of pts) {
        const point = { lat: p[0], lng: p[1] };
        for (const a of anchors) {
          const d = haversineMeters(point, a);
          if (d < min) min = d;
        }
      }
      return min;
    }
```

### `function branchHintMatch`

```js
    function branchHintMatch(element, anchors, branchHint) {
      if (!branchHint || !anchors.length) return true;
      const pts = flattenElementCoords(element);
      if (!pts.length) return false;

      const anchorLng = anchors.reduce((s, a) => s + a.lng, 0) / anchors.length;
      const anchorLat = anchors.reduce((s, a) => s + a.lat, 0) / anchors.length;

      let matchCount = 0;
      for (const p of pts) {
        const lat = p[0];
        const lng = p[1];
        if (branchHint === 'east' && lng >= anchorLng) matchCount += 1;
        if (branchHint === 'west' && lng <= anchorLng) matchCount += 1;
        if (branchHint === 'north' && lat >= anchorLat) matchCount += 1;
        if (branchHint === 'south' && lat <= anchorLat) matchCount += 1;
      }
      return (matchCount / pts.length) >= 0.55;
    }
```

### `function elementKey`

```js
    function elementKey(el) {
      return `${el.type || 'x'}:${el.id}`;
    }
```

### `function elementEndpoints`

```js
    function elementEndpoints(element) {
      const pts = [];
      if (element.type === 'way' && Array.isArray(element.geometry) && element.geometry.length > 1) {
        const first = element.geometry[0];
        const last = element.geometry[element.geometry.length - 1];
        pts.push({ lat: first.lat, lng: first.lon });
        pts.push({ lat: last.lat, lng: last.lon });
      }

      if (element.type === 'relation' && Array.isArray(element.members)) {
        for (const m of element.members) {
          if (!Array.isArray(m.geometry) || m.geometry.length < 2) continue;
          const first = m.geometry[0];
          const last = m.geometry[m.geometry.length - 1];
          pts.push({ lat: first.lat, lng: first.lon });
          pts.push({ lat: last.lat, lng: last.lon });
        }
      }
      return pts;
    }
```

### `function elementsConnected`

```js
    function elementsConnected(a, b, maxDistanceM) {
      const aEnds = elementEndpoints(a);
      const bEnds = elementEndpoints(b);
      if (!aEnds.length || !bEnds.length) return false;
      for (const pa of aEnds) {
        for (const pb of bEnds) {
          if (haversineMeters(pa, pb) <= maxDistanceM) return true;
        }
      }
      return false;
    }
```

### `function hardGatePass`

```js
    function hardGatePass(element, anchor, gateVector) {
      const c = centerOfElement(element);
      if (!c || !anchor || !gateVector) return true;
      const vx = gateVector.lng;
      const vy = gateVector.lat;
      const wx = c.lng - anchor.lng;
      const wy = c.lat - anchor.lat;
      const dot = (vx * wx) + (vy * wy);
      return dot >= 0;
    }
```

### `function getCandidatesForStream`

```js
    function getCandidatesForStream(stream, nameIndex) {
      const direct = nameIndex.get(stream.nameKey) || [];
      if (direct.length) return direct;

      const override = STREAM_MATCH_OVERRIDES[stream.nameKey];
      if (!override) return direct;

      const fallback = nameIndex.get(override.fallbackNameKey) || [];
      if (!fallback.length) return fallback;

      const nearKeys = Array.isArray(override.nearNameKeys)
        ? override.nearNameKeys
        : (override.nearNameKey ? [override.nearNameKey] : []);
      if (!nearKeys.length) return fallback;

      const nearElements = nearKeys.flatMap((k) => nameIndex.get(k) || []);
      if (!nearElements.length) return fallback;

      const anchors = nearElements.map(centerOfElement).filter(Boolean);
      if (!anchors.length) return fallback;

      const nearFiltered = fallback.filter((el) => minDistanceToAnchors(el, anchors) <= override.maxDistanceM);
      if (!nearFiltered.length) return fallback;

      const branchFiltered = nearFiltered.filter((el) => branchHintMatch(el, anchors, override.branchHint));
      const seedPool = branchFiltered.length ? branchFiltered : nearFiltered;
      const candidateSet = nearFiltered;

      if (!override.seedDistanceM) return candidateSet;

      const ranked = seedPool
        .map((el) => ({ el, dist: minDistanceToAnchors(el, anchors) }))
        .sort((a, b) => a.dist - b.dist);
      const distByKey = new Map(ranked.map((r) => [elementKey(r.el), r.dist]));

      const minSeedDistance = override.minSeedDistanceM || 0;
      let seeds = ranked
        .filter((r) => r.dist >= minSeedDistance && r.dist <= override.seedDistanceM)
        .slice(0, override.seedTopN || 3)
        .map((r) => r.el);

      if (!seeds.length) {
        seeds = ranked
          .filter((r) => r.dist <= override.seedDistanceM)
          .slice(0, override.seedTopN || 2)
          .map((r) => r.el);
      }
      if (!seeds.length) return candidateSet;

      let growthCandidates = candidateSet;
      if (override.hardGate) {
        const anchor = {
          lat: anchors.reduce((s, a) => s + a.lat, 0) / anchors.length,
          lng: anchors.reduce((s, a) => s + a.lng, 0) / anchors.length,
        };
        const seedCenter = centerOfElement(seeds[0]);
        if (seedCenter) {
          const gateVector = {
            lat: seedCenter.lat - anchor.lat,
            lng: seedCenter.lng - anchor.lng,
          };
          growthCandidates = candidateSet.filter((el) => hardGatePass(el, anchor, gateVector));
        }
      }

      const selected = [...seeds];
      const selectedKeys = new Set(seeds.map(elementKey));
      const seedKeys = new Set(seeds.map(elementKey));
      let changed = true;
      while (changed) {
        changed = false;
        for (const el of growthCandidates) {
          const key = elementKey(el);
          if (selectedKeys.has(key)) continue;
          const d = distByKey.get(key) ?? minDistanceToAnchors(el, anchors);
          if ((override.splitGuardM || 0) > 0 && d < override.splitGuardM && !seedKeys.has(key)) continue;
          const connected = selected.some((s) => elementsConnected(el, s, override.connectDistanceM || 120));
          if (connected) {
            selected.push(el);
            selectedKeys.add(key);
            changed = true;
          }
        }
      }

      return selected.length ? selected : candidateSet;
    }
```

### `function boundsFromLayers`

```js
    function boundsFromLayers(layers) {
      if (!Array.isArray(layers) || !layers.length) return null;
      const fg = L.featureGroup(layers);
      const b = fg.getBounds();
      return b.isValid() ? b : null;
    }
```

### `function reconcileLittleRiverBranches`

```js
    function reconcileLittleRiverBranches(streamEntries) {
      const east = streamEntries.find((e) => e.stream?.nameKey === 'east prong little river');
      const little = streamEntries.find((e) => e.stream?.nameKey === 'little river');
      if (!east || !little) return;

      const eastElementIds = new Set(
        east.layers
          .map((l) => l._sourceElementId)
          .filter((id) => id !== undefined && id !== null),
      );
      if (!eastElementIds.size) return;

      little.layers = little.layers.filter((l) => !eastElementIds.has(l._sourceElementId));
      little.candidatesCount = little.layers.length;
      little.streamBounds = boundsFromLayers(little.layers);
    }
```

### `function haversineMeters`

```js
    function haversineMeters(a, b) {
      const r = 6371000;
      const toRad = (v) => (v * Math.PI) / 180;
      const dLat = toRad(b.lat - a.lat);
      const dLon = toRad(b.lng - a.lng);
      const lat1 = toRad(a.lat);
      const lat2 = toRad(b.lat);
      const aa = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
      return 2 * r * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
    }
```

### `function polylineLengthMeters`

```js
    function polylineLengthMeters(latlngs) {
      let meters = 0;
      for (let i = 1; i < latlngs.length; i += 1) {
        meters += haversineMeters(latlngs[i - 1], latlngs[i]);
      }
      return meters;
    }
```

### `function sampleLatLngs`

```js
    function sampleLatLngs(latlngs, maxPoints) {
      if (latlngs.length <= maxPoints) return latlngs.slice();
      const sampled = [];
      const step = (latlngs.length - 1) / (maxPoints - 1);
      for (let i = 0; i < maxPoints; i += 1) {
        sampled.push(latlngs[Math.round(i * step)]);
      }
      return sampled;
    }
```

### `function sampleLineByDistance`

```js
    function sampleLineByDistance(latlngs, spacingM) {
      if (!Array.isArray(latlngs) || latlngs.length < 2) return latlngs ? latlngs.slice() : [];
      const out = [{ lat: latlngs[0].lat, lng: latlngs[0].lng }];
      let accumulated = 0;
      let nextTarget = spacingM;

      for (let i = 1; i < latlngs.length; i += 1) {
        const a = latlngs[i - 1];
        const b = latlngs[i];
        const segLen = haversineMeters(a, b);
        if (segLen <= 0) continue;

        while (accumulated + segLen >= nextTarget) {
          const t = (nextTarget - accumulated) / segLen;
          out.push({
            lat: a.lat + (b.lat - a.lat) * t,
            lng: a.lng + (b.lng - a.lng) * t,
          });
          nextTarget += spacingM;
        }

        accumulated += segLen;
      }

      const last = latlngs[latlngs.length - 1];
      const lastOut = out[out.length - 1];
      if (!lastOut || lastOut.lat !== last.lat || lastOut.lng !== last.lng) {
        out.push({ lat: last.lat, lng: last.lng });
      }
      return out;
    }
```

### `function smoothElevations`

```js
    function smoothElevations(values, windowSize = 5) {
      if (!Array.isArray(values) || values.length < 3) return values.slice();
      const half = Math.floor(windowSize / 2);
      const out = [];
      for (let i = 0; i < values.length; i += 1) {
        let sum = 0;
        let count = 0;
        for (let j = Math.max(0, i - half); j <= Math.min(values.length - 1, i + half); j += 1) {
          sum += values[j];
          count += 1;
        }
        out.push(sum / count);
      }
      return out;
    }
```

### `function getEntryParts`

```js
    function getEntryParts(entry) {
      const parts = [];
      for (const layer of entry.layers) {
        const latlngs = layer.getLatLngs();
        if (!Array.isArray(latlngs) || latlngs.length < 2) continue;
        const len = polylineLengthMeters(latlngs);
        if (len > 0) parts.push({ latlngs, lengthM: len });
      }
      return parts;
    }
```

### `function sampleEntryParts`

```js
    function sampleEntryParts(parts, maxPoints) {
      if (!parts.length) return [];
      const totalLength = parts.reduce((sum, p) => sum + p.lengthM, 0);
      const sampledParts = [];

      for (let i = 0; i < parts.length; i += 1) {
        const p = parts[i];
        const ratio = totalLength > 0 ? p.lengthM / totalLength : 1 / parts.length;
        let target = Math.max(2, Math.round(maxPoints * ratio));
        const distanceSampled = sampleLineByDistance(p.latlngs, PROFILE_POINT_SPACING_M);
        target = Math.min(target, distanceSampled.length);
        sampledParts.push(sampleLatLngs(distanceSampled, target));
      }

      return sampledParts;
    }
```

### `async function fetchElevations`

```js
    async function fetchElevations(latlngs) {
      const out = [];
      for (let i = 0; i < latlngs.length; i += ELEVATION_CHUNK_SIZE) {
        const chunk = latlngs.slice(i, i + ELEVATION_CHUNK_SIZE);
        const lats = chunk.map((p) => p.lat.toFixed(6)).join(',');
        const lons = chunk.map((p) => p.lng.toFixed(6)).join(',');
        const url = `https://api.open-meteo.com/v1/elevation?latitude=${encodeURIComponent(lats)}&longitude=${encodeURIComponent(lons)}`;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`Elevation API failed (${resp.status})`);
        const data = await resp.json();
        if (!Array.isArray(data.elevation)) throw new Error('Invalid elevation response');
        out.push(...data.elevation);
      }
      return out;
    }
```

### `function slopeColor`

```js
    function slopeColor(absGradePct) {
      const capped = Math.min(20, Math.max(0, absGradePct));
      const hue = 120 - (120 * capped) / 20;
      return `hsl(${hue}, 85%, 45%)`;
    }
```

### `function buildProfile`

```js
    function buildProfile(sampledParts, elevationsRaw) {
      const preparedParts = [];
      let cursor = 0;

      for (let pIdx = 0; pIdx < sampledParts.length; pIdx += 1) {
        let part = sampledParts[pIdx].slice();
        const partElevRaw = elevationsRaw.slice(cursor, cursor + part.length);
        let partElev = smoothElevations(partElevRaw, 5);

        if (partElev.length > 1 && partElev[0] < partElev[partElev.length - 1]) {
          part = part.slice().reverse();
          partElev = partElev.slice().reverse();
        }

        for (let i = 1; i < partElev.length; i += 1) {
          partElev[i] = Math.min(partElev[i], partElev[i - 1]);
        }

        preparedParts.push({ part, partElev, startElev: partElev[0] ?? 0 });
        cursor += part.length;
      }

      preparedParts.sort((a, b) => b.startElev - a.startElev);

      const points = [];
      const pointParts = [];
      let cumulative = 0;

      for (let pIdx = 0; pIdx < preparedParts.length; pIdx += 1) {
        const { part, partElev } = preparedParts[pIdx];

        const startIndex = points.length;

        for (let i = 0; i < part.length; i += 1) {
          if (i > 0) cumulative += haversineMeters(part[i - 1], part[i]);
          points.push({
            lat: part[i].lat,
            lng: part[i].lng,
            elevation: partElev[i],
            distKm: cumulative / 1000,
            partIndex: pIdx,
          });
        }
        pointParts.push({ startIndex, endIndex: points.length - 1 });
      }

      for (let i = 1; i < points.length; i += 1) {
        points[i].elevation = Math.min(points[i].elevation, points[i - 1].elevation);
      }

      const segments = [];
      let absGradeSum = 0;
      for (const pp of pointParts) {
        for (let i = pp.startIndex + 1; i <= pp.endIndex; i += 1) {
          const distM = haversineMeters(points[i - 1], points[i]);
          if (distM < GRADE_MIN_SEGMENT_M) continue;
          const rise = points[i].elevation - points[i - 1].elevation;
          const grade = distM > 0 ? (rise / distM) * 100 : 0;
          const absGrade = Math.abs(grade);
          absGradeSum += absGrade;
          segments.push({
            from: points[i - 1],
            to: points[i],
            grade,
            absGrade,
          });
        }
      }

      const totalDistanceKm = points.length ? points[points.length - 1].distKm : 0;
      const netRise = points.length ? points[points.length - 1].elevation - points[0].elevation : 0;
      const avgAbsGrade = segments.length ? absGradeSum / segments.length : 0;
      const netGrade = totalDistanceKm > 0 ? (netRise / (totalDistanceKm * 1000)) * 100 : 0;
      return { points, pointParts, segments, totalDistanceKm, netRise, avgAbsGrade, netGrade };
    }
```

### `function setProfileStatus`

```js
    function setProfileStatus(title, summary, status) {
      const panel = document.getElementById('profile-panel');
      document.getElementById('profile-title').textContent = title;
      document.getElementById('profile-summary').textContent = summary;
      document.getElementById('profile-status').textContent = status;
      panel.classList.remove('hidden');
    }
```

### `function clearSlopeOverlay`

```js
    function clearSlopeOverlay() {
      slopeLayerGroup.clearLayers();
      if (profileMarker) {
        map.removeLayer(profileMarker);
        profileMarker = null;
      }
      const chart = document.getElementById('profile-chart');
      chart.innerHTML = '';
    }
```

### `function closeProfilePanel`

```js
    function closeProfilePanel() {
      clearSlopeOverlay();
      document.getElementById('profile-panel').classList.add('hidden');
    }
```

### `function drawSlopeOverlay`

```js
    function drawSlopeOverlay(profile) {
      slopeLayerGroup.clearLayers();
      for (const seg of profile.segments) {
        L.polyline(
          [[seg.from.lat, seg.from.lng], [seg.to.lat, seg.to.lng]],
          { color: slopeColor(seg.absGrade), weight: 6, opacity: 0.95, pane: 'slopePane', interactive: false },
        ).addTo(slopeLayerGroup);
      }
    }
```

### `function renderProfileChart`

```js
    function renderProfileChart(entry, profile) {
      const svg = document.getElementById('profile-chart');
      const width = 640;
      const height = 120;
      const pad = 8;
      const values = profile.points.map((p) => p.elevation);
      const minElev = Math.min(...values);
      const maxElev = Math.max(...values);
      const elevSpan = Math.max(1, maxElev - minElev);
      const distMax = Math.max(0.001, profile.totalDistanceKm);

      const pt = profile.points.map((p) => {
        const x = pad + ((width - pad * 2) * p.distKm) / distMax;
        const y = height - pad - ((height - pad * 2) * (p.elevation - minElev)) / elevSpan;
        return { ...p, x, y };
      });

      const line = pt.map((p) => `${p.x},${p.y}`).join(' ');
      const area = `${pad},${height - pad} ${line} ${width - pad},${height - pad}`;

      svg.innerHTML = `
        <polygon points="${area}" fill="rgba(59,130,246,0.14)"></polygon>
        <polyline points="${line}" fill="none" stroke="#2563eb" stroke-width="2.5"></polyline>
        <line id="profile-cursor-line" x1="${pad}" x2="${pad}" y1="${pad}" y2="${height - pad}" stroke="#334155" stroke-width="1" opacity="0.55"></line>
      `;

      const cursorLine = document.getElementById('profile-cursor-line');
      const moveCursor = (clientX) => {
        const rect = svg.getBoundingClientRect();
        const x = Math.min(rect.right, Math.max(rect.left, clientX)) - rect.left;
        const xScaled = (x / rect.width) * width;
        let idx = 0;
        let best = Number.POSITIVE_INFINITY;
        for (let i = 0; i < pt.length; i += 1) {
          const d = Math.abs(pt[i].x - xScaled);
          if (d < best) {
            best = d;
            idx = i;
          }
        }
        const active = pt[idx];
        cursorLine.setAttribute('x1', String(active.x));
        cursorLine.setAttribute('x2', String(active.x));
        document.getElementById('profile-status').textContent = `Distance ${active.distKm.toFixed(2)} km | Elev ${active.elevation.toFixed(0)} m | Avg abs grade ${profile.avgAbsGrade.toFixed(1)}%`;

        if (!profileMarker) {
          profileMarker = L.circleMarker([active.lat, active.lng], {
            radius: 6,
            color: '#111827',
            fillColor: '#f8fafc',
            fillOpacity: 0.95,
            weight: 2,
          }).addTo(map);
        } else {
          profileMarker.setLatLng([active.lat, active.lng]);
        }
      };

      svg.onpointerdown = (e) => moveCursor(e.clientX);
      svg.onpointermove = (e) => {
        if (e.buttons === 1 || e.pointerType === 'mouse') moveCursor(e.clientX);
      };
      svg.onclick = (e) => moveCursor(e.clientX);
      const rect = svg.getBoundingClientRect();
      moveCursor(rect.left + 1);
    }
```

### `function labelLatLngForEntry`

```js
    function labelLatLngForEntry(entry) {
      if (!entry.layers || !entry.layers.length) return null;

      let bestLayer = null;
      let bestLen = 0;
      for (const layer of entry.layers) {
        const latlngs = layer.getLatLngs();
        if (!Array.isArray(latlngs) || latlngs.length < 2) continue;
        const len = polylineLengthMeters(latlngs);
        if (len > bestLen) {
          bestLen = len;
          bestLayer = layer;
        }
      }
      if (!bestLayer || bestLen <= 0) return null;

      const latlngs = bestLayer.getLatLngs();
      const target = bestLen / 2;
      let walked = 0;
      for (let i = 1; i < latlngs.length; i += 1) {
        const a = latlngs[i - 1];
        const b = latlngs[i];
        const seg = haversineMeters(a, b);
        if (walked + seg >= target && seg > 0) {
          const t = (target - walked) / seg;
          return L.latLng(
            a.lat + (b.lat - a.lat) * t,
            a.lng + (b.lng - a.lng) * t,
          );
        }
        walked += seg;
      }

      return latlngs[Math.floor(latlngs.length / 2)] || null;
    }
```

### `function formatGradeLabel`

```js
    function formatGradeLabel(grade) {
      return String(grade)
        .split(' ')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
    }
```

### `function escapeHtml`

```js
    function escapeHtml(text) {
      return String(text)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }
```

### `function parseTroutTypes`

```js
    function parseTroutTypes(stream) {
      const candidates = [
        stream.TROUT_TYPES,
        stream['TROUT TYPES'],
        stream.TROUT_TYPE,
        stream['TROUT TYPE'],
        stream.TROUT,
        stream.SPECIES,
      ];

      let raw = null;
      for (const c of candidates) {
        if (c !== undefined && c !== null && String(c).trim() !== '') {
          raw = c;
          break;
        }
      }
      if (!raw) return [];

      const tokens = Array.isArray(raw)
        ? raw.map((v) => String(v).toLowerCase())
        : String(raw)
            .toLowerCase()
            .split(/[;,/|]+/)
            .map((v) => v.trim())
            .filter(Boolean);

      const set = new Set();
      for (const t of tokens) {
        if (t.includes('rainbow')) set.add('rainbow');
        if (t.includes('brook')) set.add('brook');
        if (t.includes('brown')) set.add('brown');
      }
      return ['rainbow', 'brook', 'brown'].filter((k) => set.has(k));
    }
```

### `function streamLabelHtml`

```js
    function streamLabelHtml(stream) {
      const name = escapeHtml(stream.NAME);
      const trout = parseTroutTypes(stream);
      if (!trout.length) return name;

      const icons = trout
        .map((t) => `<i class="fa-solid fa-fish fish-icon ${t}" title="${t} trout" aria-label="${t} trout"></i>`)
        .join('');
      return `${name}<span class="fish-icons">${icons}</span>`;
    }
```

### `function renderGradeFilters`

```js
    function renderGradeFilters(selectedGrades) {
      const container = document.getElementById('grade-filters');
      container.innerHTML = GRADE_ORDER.map((grade) => `
        <button type="button" class="grade-chip ${selectedGrades.has(grade) ? 'selected' : ''}" data-grade="${grade}" aria-pressed="${selectedGrades.has(grade) ? 'true' : 'false'}">
          <span class="swatch" style="background:${COLORS[grade]}"></span>
          <span>${formatGradeLabel(grade)}</span>
        </button>
      `).join('');
    }
```

### `function addMapLegend`

```js
    function addMapLegend() {
      const legend = L.control({ position: 'bottomright' });
      legend.onAdd = function onAdd() {
        const div = L.DomUtil.create('div', 'map-legend');
        div.innerHTML = `
          <div class="map-legend-title">Stream Grades</div>
          ${GRADE_ORDER.map((grade) => `
            <div class="map-legend-row">
              <span class="swatch" style="background:${COLORS[grade]}"></span>
              <span>${formatGradeLabel(grade)}</span>
            </div>
          `).join('')}
        `;
        return div;
      };
      legend.addTo(map);
    }
```

### `function compareEntriesByGrade`

```js
    function compareEntriesByGrade(a, b, sortMode) {
      const aRank = GRADE_RANK[a.stream.grade] ?? 99;
      const bRank = GRADE_RANK[b.stream.grade] ?? 99;
      if (aRank !== bRank) {
        return sortMode === 'worst' ? bRank - aRank : aRank - bRank;
      }
      return a.stream.NAME.localeCompare(b.stream.NAME);
    }
```

### `function makePopup`

```js
    function makePopup(stream) {
      return `
        <div style="max-width: 260px; font-size: 13px;">
          <div style="font-weight: 700; margin-bottom: 6px;">${stream.NAME}</div>
          <div><b>Grade:</b> ${stream.grade}</div>
          <div><b>Fishing quality:</b> ${fixEncoding(stream['FISHING QUALITY'])}</div>
          <div><b>Size:</b> ${fixEncoding(stream.SIZE || 'N/A')}</div>
          <div><b>Pressure:</b> ${fixEncoding(stream['FISHING PRESSURE'] || 'N/A')}</div>
          <div><b>Access:</b> ${fixEncoding(stream.ACCESS || 'N/A')}</div>
        </div>
      `;
    }
```

### `function lineStyle`

```js
    function lineStyle(grade) {
      return {
        color: COLORS[grade] || COLORS.unknown,
        weight: 4,
        opacity: 0.9,
      };
    }
```

### `function highlightLineStyle`

```js
    function highlightLineStyle(grade) {
      return {
        color: COLORS[grade] || COLORS.unknown,
        weight: 7,
        opacity: 1,
      };
    }
```

### `function setupThemeToggle`

```js
    function setupThemeToggle() {
      const panel = document.querySelector('aside');
      const toggle = document.getElementById('theme-toggle');
      const saved = localStorage.getItem('smokiesSidebarTheme');
      const startTheme = saved === 'dark' ? 'dark' : 'light';
      function applyTheme(theme) {
        const isDark = theme === 'dark';
        panel.setAttribute('data-theme', theme);
        localStorage.setItem('smokiesSidebarTheme', theme);
        toggle.checked = isDark;
        toggle.setAttribute('aria-label', 'Sidebar dark mode ' + (isDark ? 'on' : 'off'));
      }
      toggle.addEventListener('change', () => {
        applyTheme(toggle.checked ? 'dark' : 'light');
      });
      applyTheme(startTheme);
    }
```

### `function loadFavorites`

```js
    function loadFavorites() {
      try {
        const raw = localStorage.getItem('smokiesFavoriteStreams');
        const arr = raw ? JSON.parse(raw) : [];
        return new Set(Array.isArray(arr) ? arr : []);
      } catch (e) {
        return new Set();
      }
    }
```

### `function saveFavorites`

```js
    function saveFavorites(favoritesSet) {
      localStorage.setItem('smokiesFavoriteStreams', JSON.stringify(Array.from(favoritesSet)));
    }
```

### `async function init`

```js
    async function init() {
      setupThemeToggle();
      addMapLegend();

      const stats = document.getElementById('stats');
      const list = document.getElementById('stream-list');
      const sortSelect = document.getElementById('sort-quality');
      const filterContainer = document.getElementById('grade-filters');
      const mappedOnlyToggle = document.getElementById('mapped-only');
      const favoritesOnlyToggle = document.getElementById('favorites-only');
      const showLabelsToggle = document.getElementById('show-labels');
      const profileCloseBtn = document.getElementById('profile-close');
      const selectedGrades = new Set(GRADE_ORDER);
      const favoritesSet = loadFavorites();
      renderGradeFilters(selectedGrades);
      profileCloseBtn.addEventListener('click', closeProfilePanel);

      const streams = await fetch('./streams_data.json').then((r) => r.json());
      streams.forEach((s) => {
        s.NAME = fixEncoding(s.NAME);
        s.grade = gradeFromQuality(s['FISHING QUALITY']);
        s.nameKey = normalizeName(s.NAME);
      });

      stats.textContent = `Loaded ${streams.length} streams. Matching stream geometry from OpenStreetMap...`;

      let nameIndex = new Map();
      let geometryUnavailableNote = '';
      let parkPolygons = [];
      const [osmResult, parkResult] = await Promise.allSettled([
        fetchOSMWaterways(),
        fetchParkBoundaryPolygons(),
      ]);

      if (osmResult.status === 'fulfilled') {
        nameIndex = buildOsmNameIndex(osmResult.value.elements || []);
      } else {
        geometryUnavailableNote = `Geometry service unavailable (${osmResult.reason?.message || 'request failed'}).`;
      }

      if (parkResult.status === 'fulfilled') {
        parkPolygons = Array.isArray(parkResult.value) ? parkResult.value : [];
      }

      const streamEntries = [];

      for (const stream of streams) {
        const candidates = getCandidatesForStream(stream, nameIndex);
        const entry = {
          stream,
          candidatesCount: candidates.length,
          streamBounds: null,
          layers: [],
        };

        for (const c of candidates) {
          const coords = coordinatesForElement(c);

          if (Array.isArray(coords[0]) && Array.isArray(coords[0][0])) {
            for (const seg of coords) {
              let clippedRuns = clipPolylineToPark(seg, parkPolygons);
              clippedRuns = applyStreamHardGateRuns(clippedRuns, stream.nameKey);
              for (const run of clippedRuns) {
                const pl = L.polyline(run, lineStyle(stream.grade))
                  .bindPopup(makePopup(stream))
                  .bindTooltip(stream.NAME, { sticky: true, direction: 'top', opacity: 0.9 });
                pl._sourceElementId = c.id;
                entry.layers.push(pl);
                entry.streamBounds = entry.streamBounds ? entry.streamBounds.extend(pl.getBounds()) : pl.getBounds();
              }
            }
          } else if (Array.isArray(coords[0])) {
            let clippedRuns = clipPolylineToPark(coords, parkPolygons);
            clippedRuns = applyStreamHardGateRuns(clippedRuns, stream.nameKey);
            for (const run of clippedRuns) {
              const pl = L.polyline(run, lineStyle(stream.grade))
                .bindPopup(makePopup(stream))
                .bindTooltip(stream.NAME, { sticky: true, direction: 'top', opacity: 0.9 });
              pl._sourceElementId = c.id;
              entry.layers.push(pl);
              entry.streamBounds = entry.streamBounds ? entry.streamBounds.extend(pl.getBounds()) : pl.getBounds();
            }
          }
        }

        streamEntries.push(entry);
      }

      reconcileLittleRiverBranches(streamEntries);

      async function loadElevationProfile(entry) {
        const token = ++activeProfileToken;
        clearSlopeOverlay();

        if (!entry.layers.length) {
          setProfileStatus(entry.stream.NAME, '', 'No mapped geometry available for this stream.');
          return;
        }

        const parts = getEntryParts(entry);
        if (!parts.length) {
          setProfileStatus(entry.stream.NAME, '', 'Could not determine a valid stream path for profiling.');
          return;
        }

        const sampledParts = sampleEntryParts(parts, PROFILE_MAX_POINTS);
        const sampledFlat = sampledParts.flat();
        if (sampledFlat.length < 2) {
          setProfileStatus(entry.stream.NAME, '', 'Stream path is too short for profile.');
          return;
        }

        const cacheKey = `${entry.stream.nameKey}:${sampledFlat.length}:${sampledFlat[0].lat.toFixed(4)}:${sampledFlat[0].lng.toFixed(4)}`;
        setProfileStatus(entry.stream.NAME, 'Loading elevation profile...', 'Fetching elevation samples...');

        let profile = elevationCache.get(cacheKey);
        if (!profile) {
          try {
            const elevations = await fetchElevations(sampledFlat);
            profile = buildProfile(sampledParts, elevations);
            elevationCache.set(cacheKey, profile);
          } catch (err) {
            if (token !== activeProfileToken) return;
            setProfileStatus(entry.stream.NAME, '', `Elevation profile failed: ${err.message}`);
            return;
          }
        }

        if (token !== activeProfileToken) return;

        const summary = `Length ${profile.totalDistanceKm.toFixed(2)} km | Net rise ${profile.netRise.toFixed(0)} m | Net grade ${profile.netGrade.toFixed(1)}% | Avg abs grade ${profile.avgAbsGrade.toFixed(1)}%`;
        setProfileStatus(entry.stream.NAME, summary, 'Move or drag over chart to follow the stream.');
        drawSlopeOverlay(profile);
        renderProfileChart(entry, profile);
      }

      function renderStreams() {
        const sortMode = sortSelect.value;
        const mappedOnly = mappedOnlyToggle.checked;
        const favoritesOnly = favoritesOnlyToggle.checked;
        const visibleEntries = streamEntries
          .filter((entry) => selectedGrades.has(entry.stream.grade))
          .filter((entry) => !mappedOnly || Boolean(entry.streamBounds))
          .filter((entry) => !favoritesOnly || favoritesSet.has(entry.stream.nameKey))
          .sort((a, b) => compareEntriesByGrade(a, b, sortMode));

        list.innerHTML = '';
        streamLayerGroup.clearLayers();
        labelLayerGroup.clearLayers();

        for (const entry of visibleEntries) {
          const { stream, candidatesCount, streamBounds, layers } = entry;
          const card = document.createElement('div');
          card.className = 'stream-card';

          const color = COLORS[stream.grade] || COLORS.unknown;
          const isFavorite = favoritesSet.has(stream.nameKey);
          const mappedClass = candidatesCount ? 'mapped' : '';
          const mappedLabel = candidatesCount ? 'Mapped' : 'No map match';
          card.innerHTML = `
            <div class="stream-head">
              <p class="stream-title">${stream.NAME}</p>
              <button type="button" class="favorite-btn ${isFavorite ? 'active' : ''}" aria-label="${isFavorite ? 'Unfavorite stream' : 'Favorite stream'}" title="${isFavorite ? 'Unfavorite' : 'Favorite'}">
                <i class="${isFavorite ? 'fa-solid' : 'fa-regular'} fa-star"></i>
              </button>
            </div>
            <p class="meta"><span class="pill" style="background:${color}">${formatGradeLabel(stream.grade)}</span></p>
            ${mappedOnly ? '' : `<div class="stream-details"><span class="map-status ${mappedClass}">${mappedLabel}</span></div>`}
          `;

          if (streamBounds) {
            card.addEventListener('click', () => {
              map.fitBounds(streamBounds.pad(0.3));
              loadElevationProfile(entry);
            });
          } else {
            card.style.opacity = '0.7';
            card.addEventListener('click', () => {
              loadElevationProfile(entry);
            });
          }

          card.addEventListener('mouseenter', () => {
            for (const layer of layers) {
              layer.setStyle(highlightLineStyle(stream.grade));
              if (typeof layer.bringToFront === 'function') layer.bringToFront();
            }
          });

          card.addEventListener('mouseleave', () => {
            for (const layer of layers) {
              layer.setStyle(lineStyle(stream.grade));
            }
          });

          const favoriteBtn = card.querySelector('.favorite-btn');
          if (favoriteBtn) {
            favoriteBtn.addEventListener('click', (event) => {
              event.preventDefault();
              event.stopPropagation();
              if (favoritesSet.has(stream.nameKey)) favoritesSet.delete(stream.nameKey);
              else favoritesSet.add(stream.nameKey);
              saveFavorites(favoritesSet);
              renderStreams();
            });
          }

          for (const layer of layers) {
            layer.addTo(streamLayerGroup);
          }

          if (showLabelsToggle.checked && streamBounds) {
            const anchor = labelLatLngForEntry(entry);
            if (anchor) {
              L.marker(anchor, {
                interactive: false,
                icon: L.divIcon({
                  className: 'stream-label',
                  html: streamLabelHtml(stream),
                  iconSize: null,
                }),
              }).addTo(labelLayerGroup);
            }
          }

          list.appendChild(card);
        }

        const visibleLayers = visibleEntries.flatMap((entry) => entry.layers);
        if (visibleLayers.length) {
          const groupBounds = L.featureGroup(visibleLayers).getBounds();
          map.fitBounds(groupBounds.pad(0.1));
        }

        const visibleMapped = visibleEntries.filter((entry) => entry.streamBounds).length;
        const baseStatus = `Showing ${visibleEntries.length}/${streams.length} streams (${visibleMapped} mapped in current filter).`;
        stats.textContent = geometryUnavailableNote ? `${baseStatus} ${geometryUnavailableNote}` : baseStatus;
      }

      sortSelect.addEventListener('change', renderStreams);
      mappedOnlyToggle.addEventListener('change', renderStreams);
      favoritesOnlyToggle.addEventListener('change', renderStreams);
      showLabelsToggle.addEventListener('change', renderStreams);
      filterContainer.addEventListener('click', (event) => {
        const chip = event.target.closest('.grade-chip');
        if (!chip) return;
        const grade = chip.dataset.grade;
        if (!grade) return;

        if (selectedGrades.has(grade)) selectedGrades.delete(grade);
        else selectedGrades.add(grade);

        if (selectedGrades.size === 0) selectedGrades.add(grade);

        renderGradeFilters(selectedGrades);
        renderStreams();
      });

      renderStreams();
    }
```

