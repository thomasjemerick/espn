#!/usr/bin/env python3
"""
Read teams.csv (from your prior scrape), fetch logos for each team, and write team_logos.csv/json.

Usage:
  python espn_cfb_team_logos.py --teams ./out/teams.csv --outdir ./out --delay 0.2

Outputs:
  ./out/team_logos.csv
  ./out/team_logos.json
"""

import argparse, csv, json, os, sys, time
from typing import Dict, Any, List, Optional

import requests

CORE_TEAM_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/teams/{id}?lang=en&region=us"

def req_json(url: str, timeout=20) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "logo-bot/1.0"})
        if r.status_code != 200: 
            return None
        return r.json()
    except Exception:
        return None

def deref(url: str) -> Optional[Dict[str, Any]]:
    return req_json(url)

def best_from_core_logos(logo_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Given dereferenced logo items, pick a few useful variants:
      - default (light background) largest available
      - dark (for dark backgrounds) largest available
      Also collect sizes (50/200/500) if present.
    """
    def rel_contains(item, key): 
        rel = item.get("rel") or []
        return key in rel

    def largest(items, want_dark=False):
        filt = [it for it in items if rel_contains(it, "full")]
        if want_dark:
            filt = [it for it in items if rel_contains(it, "dark")] or filt
        # pick max width if available
        def keyw(it): 
            return int(it.get("width") or 0)
        return sorted(filt, key=keyw)[-1] if filt else (sorted(items, key=keyw)[-1] if items else None)

    # Build a small map of width->href for defaults and dark
    out = {
        "default": None, "dark": None,
        "default_50": None, "default_200": None, "default_500": None,
        "dark_50": None, "dark_200": None, "dark_500": None
    }

    # Normalize items: ESPN Core logos often look like:
    # { "href": "https://a.espncdn.com/i/teamlogos/ncaa/500/2.png", "width": 500, "height": 500, "rel": ["full","default"] }
    items = []
    for it in logo_items:
        # Already dereferenced?
        if "href" in it:
            items.append(it)
        elif "$ref" in it:
            obj = deref(it["$ref"])
            if obj and "href" in obj: items.append(obj)

    if not items:
        return out

    # largest candidates
    d = largest([i for i in items if not rel_contains(i, "dark")], want_dark=False)
    dk = largest([i for i in items if rel_contains(i, "dark")], want_dark=True)
    if d: out["default"] = d.get("href")
    if dk: out["dark"] = dk.get("href")

    # size-specific picks by nearest width
    def nearest(want: int, dark: bool):
        cands = [i for i in items if (("dark" in (i.get("rel") or [])) == dark)]
        if not cands: cands = items
        # choose with width closest to target, else just first with href
        best, bestdiff = None, 10**9
        for i in cands:
            try:
                w = int(i.get("width") or 0)
            except Exception:
                w = 0
            diff = abs(w - want) if w else 10**8
            if diff < bestdiff and i.get("href"):
                best, bestdiff = i, diff
        return best.get("href") if best else None

    out["default_50"] = nearest(50, False)
    out["default_200"] = nearest(200, False)
    out["default_500"] = nearest(500, False)
    out["dark_50"] = nearest(50, True)
    out["dark_200"] = nearest(200, True)
    out["dark_500"] = nearest(500, True)

    return out

def cdn_fallback(team_id: str) -> Dict[str, Any]:
    # Pattern commonly used by ESPN’s CDN for college logos; we emit without HEAD checks to keep it fast.
    # If a particular size/variant doesn’t exist for a team, the URL may 404 at render time; your frontend can handle onError.
    sizes = [50, 200, 500]
    out = {"default": None, "dark": None}
    for s in sizes:
        out[f"default_{s}"] = f"https://a.espncdn.com/i/teamlogos/ncaa/{s}/{team_id}.png"
        out[f"dark_{s}"] = f"https://a.espncdn.com/i/teamlogos/ncaa/{s}-dark/{team_id}.png"
    # prefer 500 as “default” if present
    out["default"] = out["default_500"]
    out["dark"] = out["dark_500"]
    return out

def fetch_team_logos(team_id: str) -> Dict[str, Any]:
    # Try Core first
    core = req_json(CORE_TEAM_URL.format(id=team_id))
    if core:
        logos_ref = None
        # Core typically includes an object or link to /logos
        if isinstance(core.get("logos"), dict) and core["logos"].get("$ref"):
            logos_ref = core["logos"]["$ref"]
        elif core.get("$ref"):  # very defensive; usually not needed
            logos_ref = core["$ref"].rstrip("/") + "/logos"
        else:
            logos_ref = CORE_TEAM_URL.format(id=team_id).replace(f"/teams/{team_id}", f"/teams/{team_id}/logos")
        items = []
        if logos_ref:
            coll = req_json(logos_ref + "?limit=50")
            if coll:
                # Core collections usually have "items": [{"$ref": ...}, ...]
                items = coll.get("items") or []
        pick = best_from_core_logos(items)
        # If Core produced anything, use it; otherwise fallback to CDN
        if any(pick.values()):
            return pick
    # Fallback
    return cdn_fallback(team_id)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", required=True, help="Path to teams.csv produced earlier")
    ap.add_argument("--outdir", default="./out")
    ap.add_argument("--delay", type=float, default=0.15, help="Sleep between requests (seconds)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    rows = []
    with open(args.teams, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append(r)

    out_rows = []
    n = len(rows)
    print(f"[*] Fetching logos for {n} teams...")
    for i, r in enumerate(rows, 1):
        team_id = str(r.get("team_id") or "").strip()
        slug = (r.get("slug") or "").strip()
        disp = (r.get("display_name") or "").strip()
        if not team_id:
            continue
        print(f"  [{i}/{n}] {disp} (id={team_id}, slug={slug})")
        logos = fetch_team_logos(team_id)
        out_rows.append({
            "team_id": team_id,
            "slug": slug,
            "display_name": disp,
            **logos
        })
        time.sleep(args.delay)

    # CSV
    csv_path = os.path.join(args.outdir, "team_logos.csv")
    fieldnames = ["team_id","slug","display_name",
                  "default","dark",
                  "default_50","default_200","default_500",
                  "dark_50","dark_200","dark_500"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows: w.writerow(r)
    print(f"[✓] Wrote {csv_path}")

    # JSON
    json_path = os.path.join(args.outdir, "team_logos.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out_rows, f, ensure_ascii=False, indent=2)
    print(f"[✓] Wrote {json_path}")

if __name__ == "__main__":
    main()
