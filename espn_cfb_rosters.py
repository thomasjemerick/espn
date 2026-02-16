#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, csv, os, time, typing as T
from dataclasses import dataclass, asdict
import requests

CORE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
CORE_SEASON_TEAMS = CORE_BASE + "/seasons/{season}/teams"
CORE_TEAM_ATHLETES = CORE_BASE + "/seasons/{season}/teams/{team_id}/athletes"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}

def fetch_json(url: str, params: dict | None = None, retries: int = 6, backoff: float = 0.6) -> dict:
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            # retry on rate limiting / server hiccups
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (2 ** i))
                continue
            # non-retryable
            return {}
        except requests.RequestException:
            time.sleep(backoff * (2 ** i))
    return {}

def iter_core_collection(url: str, params: dict | None, delay: float) -> T.Iterator[str]:
    """Yield $ref links from a paginated core API collection."""
    page = 1
    while True:
        q = {"limit": 3000, "page": page}
        if params: q.update(params)
        j = fetch_json(url, q)
        items = j.get("items") or []
        if not items:
            break
        for it in items:
            ref = it.get("$ref")
            if ref:
                yield ref
        page_index = j.get("pageIndex") or page
        page_count = j.get("pageCount") or page
        if page_index >= page_count:
            break
        page += 1
        if delay: time.sleep(delay)

@dataclass
class TeamRow:
    team_id: str | None
    slug: str | None
    display_name: str | None
    short_display_name: str | None
    abbreviation: str | None
    location: str | None
    nickname: str | None
    color: str | None
    alternate_color: str | None
    is_active: bool | None

@dataclass
class RosterRow:
    season: int | None
    team_id: str | None
    team_display_name: str | None
    athlete_id: str | None
    full_name: str | None
    display_name: str | None
    position: str | None
    jersey: str | None
    class_year: str | None
    height: str | None
    weight: str | None
    espn_player_page: str | None
    espn_headshot_url: str | None

def to_str(x): 
    return str(x) if x is not None else None

def headshot_url(athlete_id: str | None, w=350, h=254):
    if not athlete_id: return None
    return f"https://a.espncdn.com/combiner/i?img=/i/headshots/college-football/players/full/{athlete_id}.png&w={w}&h={h}"

def player_page_url(athlete_id: str | None):
    if not athlete_id: return None
    return f"https://www.espn.com/college-football/player/_/id/{athlete_id}"

def fetch_team_refs(season: int, delay: float) -> list[str]:
    url = CORE_SEASON_TEAMS.format(season=season)
    return list(iter_core_collection(url, params={"limit": 3000}, delay=delay))

def fetch_team(team_ref: str, delay: float) -> dict:
    j = fetch_json(team_ref)
    if delay: time.sleep(delay)
    return j

def parse_team(j: dict) -> TeamRow:
    return TeamRow(
        team_id=to_str(j.get("id")),
        slug=j.get("slug"),
        display_name=j.get("displayName") or j.get("name"),
        short_display_name=j.get("shortDisplayName"),
        abbreviation=j.get("abbreviation"),
        location=j.get("location"),
        nickname=j.get("nickname"),
        color=j.get("color"),
        alternate_color=j.get("alternateColor"),
        is_active=j.get("isActive"),
    )

def fetch_team_athlete_refs(team_id: str, season: int, delay: float) -> list[str]:
    url = CORE_TEAM_ATHLETES.format(season=season, team_id=team_id)
    return list(iter_core_collection(url, params={"limit": 3000}, delay=delay))

def fetch_athlete(ath_ref: str, delay: float) -> dict:
    j = fetch_json(ath_ref)
    if delay: time.sleep(delay)
    return j

def parse_position(a: dict) -> str | None:
    pos = a.get("position") or {}
    if isinstance(pos, dict):
        return pos.get("abbreviation") or pos.get("name")
    return None

def parse_athlete(a: dict, team: TeamRow, season: int) -> RosterRow:
    a_id = to_str(a.get("id") or a.get("athlete", {}).get("id"))
    full_name = a.get("fullName") or " ".join(filter(None, [a.get("firstName"), a.get("lastName")])) or a.get("displayName")
    display_name = a.get("displayName") or full_name
    return RosterRow(
        season=season,
        team_id=team.team_id,
        team_display_name=team.display_name,
        athlete_id=a_id,
        full_name=full_name,
        display_name=display_name,
        position=parse_position(a),
        jersey=to_str(a.get("jersey")),
        class_year=(a.get("class") or {}).get("name") if isinstance(a.get("class"), dict) else a.get("class"),
        height=to_str(a.get("height")),
        weight=to_str(a.get("weight")),
        espn_player_page=player_page_url(a_id),
        espn_headshot_url=headshot_url(a_id),
    )

def ensure_dir(path: str): os.makedirs(path, exist_ok=True)

def write_csv(path: str, rows: T.Iterable[dict], fieldnames: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows: w.writerow(r)

def main():
    ap = argparse.ArgumentParser(description="ESPN CFB teams + rosters via CORE API (season-scoped).")
    ap.add_argument("--out", type=str, default="./out")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--delay", type=float, default=0.15, help="Delay between requests (seconds)")
    ap.add_argument("--max-teams", type=int, default=0, help="Debug: cap number of teams processed (0 = all)")
    args = ap.parse_args()

    ensure_dir(args.out)

    print(f"[*] Listing teams for season {args.season}...")
    team_refs = fetch_team_refs(args.season, delay=args.delay)
    print(f"[*] Found {len(team_refs)} team refs")

    teams: list[TeamRow] = []
    for i, tref in enumerate(team_refs, 1):
        tj = fetch_team(tref, delay=args.delay)
        if not tj: 
            print(f"    ! skip empty team at index {i}")
            continue
        trow = parse_team(tj)
        teams.append(trow)
        print(f"    [{i}/{len(team_refs)}] {trow.display_name} (id={trow.team_id})")
        if args.max_teams and i >= args.max_teams:
            break

    # Write teams immediately (useful if we stop later)
    teams_csv = os.path.join(args.out, "teams.csv")
    write_csv(teams_csv, (asdict(t) for t in teams),
              fieldnames=[f.name for f in TeamRow.__dataclass_fields__.values()])
    print(f"[*] Wrote {teams_csv} (teams={len(teams)})")

    # Rosters
    roster_rows: list[RosterRow] = []
    print("[*] Fetching rosters...")
    for i, team in enumerate(teams, 1):
        if not team.team_id:
            print(f"    [{i}/{len(teams)}] {team.display_name}: missing team_id, skip")
            continue
        print(f"    [{i}/{len(teams)}] {team.display_name}: listing athletes…")
        try:
            refs = fetch_team_athlete_refs(team.team_id, args.season, delay=args.delay)
            print(f"        - {len(refs)} athlete refs")
            for j, aref in enumerate(refs, 1):
                a = fetch_athlete(aref, delay=args.delay)
                if not a: 
                    continue
                roster_rows.append(parse_athlete(a, team, args.season))
                if j % 100 == 0:
                    print(f"        - parsed {j}/{len(refs)}")
        except Exception as e:
            print(f"        ! error: {e}")

    roster_csv = os.path.join(args.out, "roster.csv")
    write_csv(roster_csv, (asdict(r) for r in roster_rows),
              fieldnames=[f.name for f in RosterRow.__dataclass_fields__.values()])
    print(f"[*] Done.\n    Teams CSV:   {teams_csv}\n    Roster CSV:  {roster_csv}\n    Athletes:    {len(roster_rows)}")

if __name__ == "__main__":
    main()
