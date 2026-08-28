"""maps — Google Maps from the shell.

Subcommands: places, parking, directions, pr (park+ride route).
Run `maps help` for the full manual.
"""
import argparse
import json
import sys
from importlib.resources import files

from . import backend


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _stars(rating) -> str:
    if rating is None:
        return "–"
    return f"{rating:.1f}★"


# ── places ────────────────────────────────────────────────────────────────

def cmd_places(a) -> None:
    res = backend.cmd_places(a.query, a.location, a.radius, a.limit)
    if a.json:
        _print_json(res)
        return
    if "message" in res:
        print(res["message"])
        return
    print(f'{res["showing"]}/{res["total_found"]} Treffer für "{res["query"]}"\n')
    for i, p in enumerate(res["places"], 1):
        if i > 1:
            print("─" * 42)
        rating = _stars(p.get("rating"))
        n = p.get("user_ratings_total", 0)
        oh = p.get("opening_hours", "Unbekannt")
        print(f'{i}. {p.get("name","Unbekannter Ort")} {rating} [{n} Bewertungen]')
        print(f'   {p.get("address","Keine Adresse")}')
        print(f'   {"Open" if oh=="Open now" else "Closed" if oh=="Closed" else oh}')


# ── parking ───────────────────────────────────────────────────────────────

def cmd_parking(a) -> None:
    res = backend.cmd_parking(a.location, a.radius, a.sort_by)
    if a.json:
        _print_json(res)
        return
    if "message" in res:
        print(res["message"])
        return
    c = res["center"]
    print(f'center: {c["lat"]},{c["lng"]}  radius: {res["radius_m"]}m  sort: {res["sort_by"]}  found: {res["total_found"]}\n')
    for i, p in enumerate(res["parking"], 1):
        rating = _stars(p.get("rating"))
        n = p.get("user_ratings_total", 0)
        print(f'{i}. {p.get("name")}  {rating} [{n}]  {p["distance_km"]}km')
        print(f'   {p.get("address")}')


# ── directions ────────────────────────────────────────────────────────────

def _line_label(line_info: dict | None) -> str:
    if not line_info:
        return ""
    name = line_info.get("short_name") or line_info.get("name") or ""
    if name.isdigit():
        return f"Line {name}"
    return name


def cmd_directions(a) -> None:
    res = backend.cmd_directions(
        a.origin, a.destination, a.mode, a.alternatives, a.waypoints,
        a.departure, a.arrival,
    )
    if a.json:
        _print_json(res)
        return
    routes = res["routes"]
    print(f'{res["origin"]} → {res["destination"]}  (mode: {res["mode"]}, {res["total_routes"]} route(s))\n')
    for r in routes:
        print(f'Route {r["index"] + 1}: {r["total_distance"]} · {r["total_duration"]}'
              + (f' · traffic {r["total_duration_in_traffic"]}' if r.get("total_duration_in_traffic") else ""))
        if a.steps and r["steps"]:
            for s in r["steps"]:
                instr = s["instruction"] or "–"
                line = _line_label((s.get("transit_details") or {}).get("line"))
                if line:
                    instr = f"{line} {instr[0].lower()}{instr[1:]}" if instr else line
                td = s.get("transit_details") or {}
                stops = ""
                if td.get("departure_stop") and td.get("arrival_stop"):
                    stops = f' ({td["departure_stop"]["name"]} → {td["arrival_stop"]["name"]})'
                tp = ""
                if td.get("departure_time") and td.get("arrival_time"):
                    tp = f'{backend.epoch_to_time(td["departure_time"]["value"])} → {backend.epoch_to_time(td["arrival_time"]["value"])} '
                print(f'  {s["step"]}. {tp}{instr}{stops}  {s.get("distance","–")} {s.get("duration","–")}')
        print()


# ── pr (park + ride) ──────────────────────────────────────────────────────

def _fmt_min(sec: int | None) -> str:
    if not sec or sec <= 0:
        return "N/A"
    return f"{round(sec / 60)} min"


def _bar(drive_sec: int, transit_sec: int, length: int = 32) -> str:
    total = max(0, drive_sec) + max(0, transit_sec)
    if total <= 0:
        drive_blocks = length // 2
    else:
        drive_blocks = max(0, min(length, round(drive_sec / total * length)))
    return "█" * drive_blocks + "░" * (length - drive_blocks)


def cmd_pr(a) -> None:
    res = backend.cmd_parking_route(
        a.origin, a.destination, a.radius, a.max_results, a.avoid_highways,
        a.pnr_only, a.map,
    )
    if a.json:
        _print_json(res)
        return
    print(f'{res["origin"]} → {res["destination"]}\n')
    opts = res["options"]
    if not opts:
        print(res.get("message", "Keine passende Route gefunden."))
        return
    best = max(1, opts[0].get("total_duration_sec", 0))
    for i, opt in enumerate(opts):
        if i > 0:
            print("\n" + "─" * 38 + "\n")
        p = opt["parking"]
        print(f'Parkplatz: {p["name"]}')
        print(f'Fahrzeit:  {_fmt_min(opt["drive"]["duration_sec"])}  │  '
              f'{"Transit" if opt["transit"]["has_public_transit"] else "Fußweg"}: {_fmt_min(opt["transit"]["duration_sec"])}')
        lines = opt["transit"]["lines"]
        if lines:
            parts = []
            for l in lines:
                lbl = l["mode_label"]
                if l.get("line"):
                    lbl += f' {l["line"]}'
                parts.append(lbl)
            print(f'Linien:    {", ".join(parts)}')
        if opt.get("map_path"):
            print(f'Karte:     {opt["map_path"]}')
        print(f'Gesamt:    {_fmt_min(opt["total_duration_sec"])}')
        print(_bar(opt["drive"]["duration_sec"] or 0, opt["transit"]["duration_sec"] or 0,
                   max(4, min(32, round(32 * (opt["total_duration_sec"] / best))))))


# ── help ──────────────────────────────────────────────────────────────────

def cmd_help(a) -> None:
    print(files("maps4agent").joinpath("help.md").read_text().rstrip())


# ── entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="maps",
        description="Google Maps from the shell. Run 'maps help' for the full manual.",
    )
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("places", help="text-search any place (restaurants, landmarks, …)")
    p.add_argument("query", help="search query (e.g. 'ramen restaurant Düsseldorf')")
    p.add_argument("--location", metavar="LAT,LNG", help="bias to a coordinate")
    p.add_argument("--radius", type=int, default=5000, metavar="M", help="search radius in meters (default 5000)")
    p.add_argument("--limit", type=int, default=10, metavar="N", help="max results (default 10)")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.set_defaults(fn=cmd_places)

    p = sub.add_parser("parking", help="parking lots near a location, with ratings + distance")
    p.add_argument("location", help="'lat,lng' or address (e.g. 'Burgplatz Düsseldorf')")
    p.add_argument("--radius", type=int, default=3000, metavar="M", help="radius in meters, 500..50000 (default 3000)")
    p.add_argument("--sort-by", choices=["distance", "rating"], default="distance", help="sort key (default distance)")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.set_defaults(fn=cmd_parking)

    p = sub.add_parser("directions", help="turn-by-turn directions between two points")
    p.add_argument("origin", help="address or 'lat,lng'")
    p.add_argument("destination", help="address or 'lat,lng'")
    p.add_argument("--mode", choices=["driving", "transit", "walking", "bicycling"], default="driving")
    p.add_argument("--alternatives", action="store_true", help="request alt routes (driving/transit only)")
    p.add_argument("--waypoints", help="comma-separated intermediate stops (address or lat,lng)")
    p.add_argument("--departure", metavar="TIME", help="ISO datetime or HH:MM (today)")
    p.add_argument("--arrival", metavar="TIME", help="ISO datetime or HH:MM (transit only)")
    p.add_argument("--steps", action="store_true", help="print step-by-step instructions")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.set_defaults(fn=cmd_directions)

    p = sub.add_parser("pr", help="park+ride: drive to parking, transit to destination")
    p.add_argument("origin", help="starting address or 'lat,lng'")
    p.add_argument("destination", help="destination address or 'lat,lng'")
    p.add_argument("--radius", type=int, default=2000, metavar="M", help="parking search radius in meters (default 2000)")
    p.add_argument("--max-results", type=int, default=5, metavar="N", help="parking candidates to evaluate (default 5)")
    p.add_argument("--avoid-highways", action="store_true", help="avoid highways on the drive leg")
    p.add_argument("--pnr-only", action="store_true", help="only consider Park+Ride lots")
    p.add_argument("--no-map", dest="map", action="store_false", help="skip generating the HTML map file")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.set_defaults(fn=cmd_pr)

    p = sub.add_parser("help", help="show this help", add_help=False)
    p.set_defaults(fn=cmd_help)

    args = ap.parse_args()
    if getattr(args, "fn", None) is None:
        cmd_help(args)
        return
    try:
        args.fn(args)
    except SystemExit:
        raise
    except Exception as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
