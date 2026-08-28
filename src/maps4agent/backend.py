"""Core Google Maps operations for the maps CLI (stdlib only — urllib + json).

Faithful port of the pi maps extension: same endpoints, same response shaping,
same sorting. API key is read from $GOOGLE_MAPS_API_KEY, falling back to a
`GOOGLE_MAPS_API_KEY=...` line in ~/.env (mirrors the extension's readEnvFile).
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime


# ── config / HTTP ─────────────────────────────────────────────────────────

def _read_env_file(key: str) -> str:
    env_path = os.path.join(os.environ.get("HOME", "/root"), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                m = re.match(rf"^{re.escape(key)}=(.*)$", line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return ""


def api_key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or _read_env_file("GOOGLE_MAPS_API_KEY")


def check_api_key() -> str:
    k = api_key()
    if not k:
        raise SystemExit(
            "No Google Maps API key. Set GOOGLE_MAPS_API_KEY in ~/.env or the environment. "
            "Get one free at mapsplatform.google.com"
        )
    return k


def call_google_maps(endpoint: str, params: dict, key: str) -> dict:
    url = (
        f"https://maps.googleapis.com/maps/api/{endpoint}/json?"
        + urllib.parse.urlencode(params)
        + f"&key={key}"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    status = data.get("status", "")
    if status == "OVER_QUERY_LIMIT":
        raise SystemExit("Google Maps: Over query limit — wait a moment and retry.")
    if status == "REQUEST_DENIED":
        msg = data.get("error_message", "")
        raise SystemExit(f"Google Maps: Request denied — check API key permissions for {endpoint}."
                         + (f" {msg}" if msg else ""))
    if status == "ZERO_RESULTS":
        return {"status": "ZERO_RESULTS", "data": data}
    if status != "OK":
        msg = data.get("error_message", "")
        raise SystemExit(f"Google Maps API: {status}" + (f" — {msg}" if msg else ""))
    return {"status": "OK", "data": data}


# ── geo / time helpers ────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_COORD_RE = re.compile(r"^-?\d+\.?\d*,-?\d+\.?\d*$")


def is_coords(s: str) -> bool:
    return bool(_COORD_RE.match(s.strip().replace(" ", "")))


def geocode(location: str, key: str) -> tuple[float, float]:
    """Return (lat, lng) for an address, or parse a 'lat,lng' string directly."""
    s = location.strip().replace(" ", "")
    if is_coords(s):
        lat, lng = s.split(",")
        return float(lat), float(lng)
    geo = call_google_maps("geocode", {"address": location}, key)
    if geo["status"] != "OK":
        raise SystemExit(f"Could not geocode location: {location}")
    loc = geo["data"]["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def parse_time_param(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^(\d{2}):(\d{2})$", value)
    if m:
        now = datetime.now()
        d = datetime(now.year, now.month, now.day, int(m.group(1)), int(m.group(2)))
        return int(d.timestamp())
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        pass
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_seconds(s: str) -> int:
    if not s:
        return 0
    m = re.match(r"(\d+)\s*hours?\s*(\d+)?\s*mins?", s, re.I)
    if m:
        return int(m.group(1)) * 3600 + (int(m.group(2)) * 60 if m.group(2) else 0)
    m = re.match(r"(\d+)\s*mins?", s, re.I)
    if m:
        return int(m.group(1)) * 60
    m = re.match(r"(\d+)\s*hours?", s, re.I)
    if m:
        return int(m.group(1)) * 3600
    return 0


def epoch_to_time(sec: int) -> str:
    d = datetime.fromtimestamp(sec)
    return f"{d.hour:02d}:{d.minute:02d}"


def _strip_html(s: str | None) -> str:
    return re.sub(r"<[^>]*>", "", s or "")


def _fmt_duration(seconds: int) -> str:
    minutes = round(seconds / 60)
    h, m = divmod(minutes, 60)
    return f"{h}:{m:02d} h" if h >= 1 else f"{minutes} min"


# ── polyline decoder (Google encoded polyline) ───────────────────────────

def decode_polyline(s: str) -> list[tuple[float, float]]:
    index = lat = lng = 0
    coords: list[tuple[float, float]] = []
    while index < len(s):
        shift = result = 0
        while True:
            b = ord(s[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += ~(result >> 1) if (result & 1) else (result >> 1)
        shift = result = 0
        while True:
            b = ord(s[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lng += ~(result >> 1) if (result & 1) else (result >> 1)
        coords.append((lat * 1e-5, lng * 1e-5))
    return coords


# ── commands ──────────────────────────────────────────────────────────────

def cmd_places(query: str, location: str | None, radius: int, limit: int) -> dict:
    key = check_api_key()
    params = {"query": query, "radius": str(radius)}
    if location:
        params["location"] = location
    res = call_google_maps("place/textsearch", params, key)
    if res["status"] == "ZERO_RESULTS":
        return {"message": f"No results for: {query}"}
    places = [
        {
            "name": p.get("name"),
            "place_id": p.get("place_id"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total"),
            "price_level": p.get("price_level"),
            "opening_hours": "Open now" if p.get("opening_hours", {}).get("open_now") else "Closed",
            "lat": p.get("geometry", {}).get("location", {}).get("lat"),
            "lng": p.get("geometry", {}).get("location", {}).get("lng"),
            "types": p.get("types"),
        }
        for p in res["data"]["results"][:limit]
    ]
    return {
        "query": query,
        "total_found": len(res["data"]["results"]),
        "showing": len(places),
        "places": places,
    }


def cmd_parking(location: str, radius: int, sort_by: str) -> dict:
    key = check_api_key()
    lat, lng = geocode(location, key)
    places = call_google_maps(
        "place/textsearch",
        {"query": "parking lot near " + location, "location": f"{lat},{lng}", "radius": str(radius)},
        key,
    )
    if places["status"] == "ZERO_RESULTS":
        return {"message": "No parking found nearby. Try increasing the radius."}

    results = []
    for place in places["data"]["results"]:
        rating = place.get("rating")
        user_ratings_total = place.get("user_ratings_total", 0)
        reviews = []
        place_id = place.get("place_id", "")
        if place_id.startswith("Ch"):
            try:
                details = call_google_maps(
                    "place/details",
                    {"place_id": place_id, "fields": "rating,user_ratings_total,reviews,formatted_address,geometry"},
                    key,
                )
                if details["status"] == "OK" and details["data"].get("result"):
                    d = details["data"]["result"]
                    rating = d.get("rating", rating)
                    user_ratings_total = d.get("user_ratings_total", user_ratings_total)
                    reviews = [
                        {"author": r["author_name"], "rating": r["rating"],
                         "text": (r.get("text") or "")[:200], "time": r.get("relative_time_description")}
                        for r in (d.get("reviews") or [])[:3]
                    ]
            except Exception:
                pass
        pos = place["geometry"]["location"]
        dist = haversine_km(lat, lng, pos["lat"], pos["lng"])
        results.append({
            "name": place.get("name"),
            "place_id": place_id,
            "address": place.get("formatted_address"),
            "rating": rating,
            "user_ratings_total": user_ratings_total,
            "distance_km": round(dist * 100) / 100,
            "lat": pos["lat"],
            "lng": pos["lng"],
            "reviews": reviews or None,
            "types": place.get("types"),
        })

    results.sort(key=lambda a: (
        -(a["rating"] or 0) if sort_by == "rating" else a["distance_km"],
        -(a["user_ratings_total"]) if sort_by == "rating" else 0,
    ))
    return {
        "center": {"lat": lat, "lng": lng},
        "radius_m": radius,
        "total_found": len(results),
        "sort_by": sort_by,
        "parking": results,
    }


def _shape_steps(steps: list, leg_index: int) -> list[dict]:
    out = []
    for i, s in enumerate(steps):
        step = {
            "leg_index": leg_index,
            "step": i + 1,
            "instruction": _strip_html(s.get("html_instructions") or s.get("instructions")),
            "distance": s.get("distance", {}).get("text"),
            "duration": s.get("duration", {}).get("text"),
            "mode": s.get("travel_mode"),
        }
        td = s.get("transit_details") or s.get("transit")
        if td:
            step["transit_details"] = {
                "arrival_stop": td.get("arrival_stop"),
                "arrival_time": td.get("arrival_time"),
                "departure_stop": td.get("departure_stop"),
                "departure_time": td.get("departure_time"),
                "headsign": td.get("headsign"),
                "headway": td.get("headway"),
                "line": td.get("line"),
                "num_stops": td.get("num_stops"),
                "trip_short_name": td.get("trip_short_name"),
            }
        if s.get("steps"):
            step["sub_steps"] = [
                {
                    "step": j + 1,
                    "instruction": _strip_html(ss.get("html_instructions") or ss.get("instructions")),
                    "distance": ss.get("distance", {}).get("text"),
                    "duration": ss.get("duration", {}).get("text"),
                    "mode": ss.get("travel_mode"),
                }
                for j, ss in enumerate(s["steps"])
            ]
        out.append(step)
    return out


def cmd_directions(origin, destination, mode, alternatives, waypoints,
                   departure_time, arrival_time) -> dict:
    key = check_api_key()
    params = {"origin": origin, "destination": destination, "mode": mode}
    if waypoints:
        params["waypoints"] = "|".join(waypoints) if isinstance(waypoints, list) else waypoints
    if alternatives and mode in ("driving", "transit"):
        params["alternatives"] = "true"
    dep = parse_time_param(departure_time)
    arr = parse_time_param(arrival_time)
    if dep and arr:
        raise SystemExit("Cannot specify both departure_time and arrival_time. Use one or the other.")
    if dep:
        params["departure_time"] = str(dep)
    if arr:
        params["arrival_time"] = str(arr)

    res = call_google_maps("directions", params, key)
    if res["status"] == "ZERO_RESULTS":
        raise SystemExit("No route found. Try different origin/destination or travel mode.")

    routes = []
    for index, route in enumerate(res["data"]["routes"]):
        legs = route["legs"]
        total_m = sum(leg.get("distance", {}).get("value", 0) for leg in legs)
        total_s = sum(leg.get("duration", {}).get("value", 0) for leg in legs)
        steps = []
        for li, leg in enumerate(legs):
            steps.extend(_shape_steps(leg.get("steps", []), li))
        routes.append({
            "index": index,
            "summary": route.get("summary") or f"Route {index + 1}",
            "total_distance": f"{total_m / 1000:.1f} km",
            "total_distance_meters": total_m,
            "total_duration": _fmt_duration(total_s),
            "total_duration_seconds": total_s,
            "total_duration_in_traffic": route.get("duration_in_traffic", {}).get("text"),
            "legs": [
                {
                    "from": leg.get("start_address"),
                    "to": leg.get("end_address"),
                    "distance": leg.get("distance", {}).get("text"),
                    "duration": leg.get("duration", {}).get("text"),
                    "duration_in_traffic": leg.get("duration_in_traffic", {}).get("text"),
                }
                for leg in legs
            ],
            "steps": steps,
            "fare": route.get("fare"),
            "warnings": route.get("warnings"),
            "waypoint_order": route.get("waypoint_order"),
        })
    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "total_routes": len(routes),
        "routes": routes,
    }


_PNR_RE = re.compile(r"(\bP\+R\b|Park\s*&?\s*Ride|Park\s*and\s*Ride)", re.I)


def _transit_mode_label(mode: str | None) -> str:
    n = (mode or "").upper()
    return {
        "SUBWAY": "U-Bahn",
        "HEAVY_RAIL": "Bahn",
        "COMMUTER_TRAIN": "Bahn",
        "RAIL": "Bahn",
        "TRAM": "Tram",
        "BUS": "Bus",
        "FERRY": "Fähre",
    }.get(n, mode or "Transit")


def cmd_parking_route(origin, destination, radius, max_results, avoid_highways,
                      pnr_only, generate_map) -> dict:
    key = check_api_key()
    parking_res = call_google_maps(
        "place/textsearch",
        {
            "query": ("P+R or Park and Ride near " if pnr_only else "parking near ") + destination,
            "location": destination,
            "radius": str(radius),
        },
        key,
    )
    if parking_res["status"] == "ZERO_RESULTS":
        return {"message": "No parking found near destination."}

    candidates = []
    for place in parking_res["data"]["results"]:
        if pnr_only:
            haystack = f"{place.get('name', '')} {place.get('formatted_address', '')}"
            if not _PNR_RE.search(haystack):
                continue
        candidates.append(place)
    candidates = candidates[:max_results]

    if not candidates:
        return {
            "message": "No Park+Ride (P+R) parking found near destination.",
            "destination": destination, "origin": origin,
            "park_and_ride_only": True, "total_options": 0, "options": [],
            "recommendation": "None found",
        }

    options = []
    for place in candidates:
        ploc = place["geometry"]["location"]
        pcoords = f"{ploc['lat']},{ploc['lng']}"
        drive = call_google_maps("directions", {
            "origin": origin, "destination": pcoords, "mode": "driving",
            "avoid": "highways" if avoid_highways else "tolls",
        }, key)
        transit = call_google_maps("directions", {
            "origin": pcoords, "destination": destination, "mode": "transit",
        }, key)
        if drive["status"] != "OK" or not drive["data"]["routes"]:
            continue
        if transit["status"] != "OK" or not transit["data"]["routes"]:
            continue

        drive_leg = drive["data"]["routes"][0]["legs"][0]
        transit_leg = transit["data"]["routes"][0]["legs"][0]
        drive_s = int(drive_leg.get("duration", {}).get("value", 0))
        transit_s = int(transit_leg.get("duration", {}).get("value", 0))
        tsteps = transit_leg.get("steps", [])
        walk_s = sum(int(s.get("duration", {}).get("value", 0)) for s in tsteps if s.get("travel_mode") == "WALKING")
        vehicle_s = sum(int(s.get("duration", {}).get("value", 0)) for s in tsteps if s.get("travel_mode") == "TRANSIT")
        lines = []
        for s in tsteps:
            if s.get("travel_mode") != "TRANSIT":
                continue
            d = s.get("transit_details") or {}
            line = d.get("line") or {}
            vehicle = line.get("vehicle") or {}
            mode = vehicle.get("type", "TRANSIT")
            lines.append({
                "mode": mode,
                "mode_label": _transit_mode_label(mode),
                "line": line.get("short_name") or line.get("name"),
                "line_name": line.get("name"),
                "direction": d.get("headsign"),
                "departure_stop": (d.get("departure_stop") or {}).get("name"),
                "arrival_stop": (d.get("arrival_stop") or {}).get("name"),
                "num_stops": d.get("num_stops"),
            })
        dest_loc = transit_leg.get("end_location") or {}
        dist_km = round(haversine_km(ploc["lat"], ploc["lng"], dest_loc.get("lat", 0), dest_loc.get("lng", 0)) * 100) / 100
        options.append({
            "parking": {
                "name": place.get("name"),
                "address": place.get("formatted_address"),
                "place_id": place.get("place_id"),
                "rating": place.get("rating"),
                "user_ratings_total": place.get("user_ratings_total"),
                "distance_to_target_km": dist_km,
                "lat": ploc["lat"], "lng": ploc["lng"],
            },
            "drive": {
                "distance": drive_leg.get("distance", {}).get("text"),
                "duration": drive_leg.get("duration", {}).get("text"),
                "duration_sec": drive_s,
                "steps": [_strip_html(s.get("html_instructions")) for s in drive_leg.get("steps", [])],
                "polyline": drive["data"]["routes"][0].get("overview_polyline", {}).get("points", ""),
                "origin": drive_leg.get("start_location"),
            },
            "transit": {
                "distance": transit_leg.get("distance", {}).get("text"),
                "duration": transit_leg.get("duration", {}).get("text"),
                "duration_sec": transit_s,
                "walk_duration_sec": walk_s,
                "vehicle_duration_sec": vehicle_s,
                "has_public_transit": vehicle_s > 0,
                "lines": lines,
                "steps": [_strip_html(s.get("html_instructions")) for s in tsteps],
                "polyline": transit["data"]["routes"][0].get("overview_polyline", {}).get("points", ""),
                "destination": dest_loc,
            },
            "total_duration": f"{drive_leg.get('duration', {}).get('text', 'N/A')} drive + {transit_leg.get('duration', {}).get('text', 'N/A')} transit",
            "total_duration_sec": drive_s + transit_s,
        })

    options.sort(key=lambda o: o["total_duration_sec"])

    if generate_map and options:
        for opt in options:
            opt["map_path"] = _write_map_html({
                "title": f"{origin} → {destination}",
                "routes": [
                    {"coords": decode_polyline(opt["drive"]["polyline"]),
                     "style": {"color": "#0d6efd", "weight": 5, "opacity": 0.7}},
                    {"coords": decode_polyline(opt["transit"]["polyline"]),
                     "style": {"color": "#198754", "weight": 4, "opacity": 0.8, "dashArray": "6,6"}},
                ],
                "markers": [
                    {"lat": opt["drive"]["origin"]["lat"], "lng": opt["drive"]["origin"]["lng"], "label": "🏠 Start"},
                    {"lat": opt["parking"]["lat"], "lng": opt["parking"]["lng"], "label": "🅿️ " + (opt["parking"]["name"] or "Parkplatz")},
                    {"lat": opt["transit"]["destination"]["lat"], "lng": opt["transit"]["destination"]["lng"], "label": "🎯 Ziel"},
                ],
            })

    return {
        "destination": destination,
        "origin": origin,
        "total_options": len(options),
        "options": options,
        "recommendation": options[0]["parking"]["name"] if options else "None found",
        "park_and_ride_only": pnr_only,
    }


# ── map HTML (standalone file — Leaflet via CDN, polylines decoded in Python) ─

_MAP_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;padding:0;height:100vh}}#map{{width:100%;height:100%}}</style>
</head>
<body>
<div id="map"></div>
<script>
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap contributors'}}).addTo(map);
const routes={routes_json};
const markers={markers_json};
const all=[];
routes.forEach(r=>{{
  if(!r.coords||!r.coords.length)return;
  const s=r.style||{{}};
  L.polyline(r.coords,{{color:s.color||'#0d6efd',weight:s.weight||5,opacity:s.opacity||0.7,dashArray:s.dashArray||null}}).addTo(map);
  r.coords.forEach(c=>all.push(L.latLng(c[0],c[1])));
}});
markers.forEach(m=>{{L.marker([m.lat,m.lng]).bindPopup(m.label).addTo(map);all.push(L.latLng(m.lat,m.lng));}});
if(all.length)map.fitBounds(L.latLngBounds(all).pad(0.1));
</script>
</body>
</html>
"""


def _write_map_html(data: dict) -> str:
    routes_json = json.dumps([
        {"coords": r.get("coords"), "style": r.get("style", {})}
        for r in data.get("routes", [])
    ])
    markers_json = json.dumps(data.get("markers", []))
    html = _MAP_HTML_TEMPLATE.format(
        title=data.get("title", "Route"),
        routes_json=routes_json,
        markers_json=markers_json,
    )
    fd, path = tempfile.mkstemp(prefix="maps_", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    return path
