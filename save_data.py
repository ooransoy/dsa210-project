#!/usr/bin/env python3

# I generated this script using Claude (chat history/prompts: https://claude.ai/share/c6e4306a-4b9d-4575-b51a-71a6ee6103a8) because I think data scraping and using APIs is outside the scope of DSA210. All code other than in this file is my own.

"""
jstris_fetcher.py — Parse saved Jstris leaderboard HTML pages into JSON.

How to use:
  1. Go to your sprint games page in your browser:
     https://jstris.jezevec10.com/sprint?display=5&user=YOURNAME&lines=40L&rule=default
  2. Save each page as HTML (Ctrl+S → "Webpage, Complete" or "HTML Only")
  3. Click "next" in the browser, save the next page, repeat for all pages
  4. Do the same for ultra:
     https://jstris.jezevec10.com/ultra?display=5&user=YOURNAME&rule=default
  5. Run this script:

     python jstris_fetcher.py USERNAME --sprint s1.html s2.html ... --ultra u1.html

Per-game fields extracted:
  id          unique game ID
  gametime    seconds (sprint) or score (ultra)
  timestamp   ISO-8601 UTC
  blocks      pieces placed
  pps         pieces per second
  finesse     finesse fault count
  has_replay  whether a replay was saved
  replay_url  link to replay viewer

Requirements:
  pip install beautifulsoup4 requests
"""

import argparse
import json
import os
import sys
import time as time_mod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup
import requests

BASE = "https://jstris.jezevec10.com"


@dataclass
class Game:
    id: int
    gametime: float                       # seconds (sprint) or score (ultra)
    timestamp: str
    blocks: Optional[int] = None
    pps: Optional[float] = None
    finesse: Optional[int] = None
    ppb: Optional[float] = None           # points per block (ultra only)
    has_replay: bool = False
    replay_url: Optional[str] = None


def _detect_mode(soup: BeautifulSoup) -> str:
    """Detect sprint vs ultra from table headers."""
    headers = [th.get_text(strip=True) for th in soup.select("thead th")]
    if "Score" in headers:
        return "ultra"
    return "sprint"


def parse_html_file(filepath: str, mode: str = "auto") -> list[Game]:
    """
    Parse a saved Jstris leaderboard HTML page.

    Sprint columns: Time | Blocks | PPS | Finesse
    Ultra columns:  Score | Blocks | PPB | PPS | Finesse

    Mode is auto-detected from table headers if not specified.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    if mode == "auto":
        mode = _detect_mode(soup)

    games = []

    for tr in soup.select("tr[data-record-id]"):
        gid = int(tr["data-record-id"])

        # gametime/score from <strong>
        gametime = None
        strong = tr.select_one("strong")
        if strong:
            try:
                gametime = float(strong.get_text(strip=True).replace(",", ""))
            except ValueError:
                pass
        if gametime is None:
            continue

        # numeric cells after <strong>
        cells = tr.find_all("td")
        numeric_cells = []
        found_strong = False
        for td in cells:
            if td.find("strong"):
                found_strong = True
                continue
            if not found_strong:
                continue
            if td.get("data-tsu") is not None or td.get("data-replay-val") is not None:
                continue
            text = td.get_text(strip=True)
            if text and not td.find("a"):
                try:
                    numeric_cells.append(float(text.replace(",", "")))
                except ValueError:
                    pass

        # Sprint: [blocks, pps, finesse]
        # Ultra:  [blocks, ppb, pps, finesse]
        if mode == "ultra":
            blocks = int(numeric_cells[0]) if len(numeric_cells) > 0 else None
            ppb = numeric_cells[1] if len(numeric_cells) > 1 else None
            pps = numeric_cells[2] if len(numeric_cells) > 2 else None
            finesse = int(numeric_cells[3]) if len(numeric_cells) > 3 else None
        else:
            blocks = int(numeric_cells[0]) if len(numeric_cells) > 0 else None
            ppb = None
            pps = numeric_cells[1] if len(numeric_cells) > 1 else None
            finesse = int(numeric_cells[2]) if len(numeric_cells) > 2 else None

        # timestamp from data-tsu
        timestamp = ""
        ts_td = tr.select_one("td[data-tsu]")
        if ts_td:
            try:
                unix_ts = int(ts_td["data-tsu"])
                timestamp = datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
            except (ValueError, OSError):
                pass

        # replay from data-replay-val
        has_replay = False
        replay_td = tr.select_one("td[data-replay-val]")
        if replay_td:
            try:
                has_replay = int(replay_td["data-replay-val"]) > 0
            except ValueError:
                pass

        replay_url = f"{BASE}/replay/{gid}" if has_replay else None

        games.append(Game(
            id=gid, gametime=gametime, timestamp=timestamp,
            blocks=blocks, pps=pps, finesse=finesse, ppb=ppb,
            has_replay=has_replay, replay_url=replay_url,
        ))

    return games


def fetch_stats(username: str, game_id: int) -> dict | None:
    """GET /api/u/{user}/records/{game}?mode=1 — public, no auth."""
    try:
        r = requests.get(
            f"{BASE}/api/u/{username}/records/{game_id}",
            params={"mode": 1},
            headers={"User-Agent": "JstrisFetcher/4.0"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  stats API error: {e}", file=sys.stderr)
        return None


def main():
    p = argparse.ArgumentParser(
        description="Parse saved Jstris HTML pages into a JSON dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
How to save pages:
  1. Open https://jstris.jezevec10.com/sprint?display=5&user=YOURNAME&lines=40L&rule=default
  2. Ctrl+S → save as HTML.  Click "next", save again.  Repeat for all pages.
  3. Same for ultra: .../ultra?display=5&user=YOURNAME&rule=default

Examples:
  %(prog)s dynam1c --sprint sprint1.html sprint2.html sprint3.html
  %(prog)s dynam1c --sprint s*.html --ultra u1.html
  %(prog)s dynam1c --sprint s*.html --ultra u1.html -o ./data
""",
    )
    p.add_argument("username", help="Jstris username (for stats API lookup)")
    p.add_argument("--sprint", nargs="+", default=[],
                   help="Saved HTML files for Sprint 40L pages (in order)")
    p.add_argument("--ultra", nargs="+", default=[],
                   help="Saved HTML files for Ultra pages (in order)")
    p.add_argument("--output-dir", "-o", default=".",
                   help="Directory for output JSON (default: cwd)")
    args = p.parse_args()

    if not args.sprint and not args.ultra:
        p.error("Provide at least one of --sprint or --ultra with HTML files.")

    os.makedirs(args.output_dir, exist_ok=True)

    result = {
        "username": args.username,
        "fetched_at": time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", time_mod.gmtime()),
        "sprint_40l": {"stats": None, "games": []},
        "ultra":      {"stats": None, "games": []},
    }

    # ── Sprint 40L ──
    if args.sprint:
        print(f"Sprint 40L: parsing {len(args.sprint)} file(s)...", file=sys.stderr)

        all_games = []
        seen_ids = set()
        for filepath in args.sprint:
            games = parse_html_file(filepath)
            new = [g for g in games if g.id not in seen_ids]
            for g in new:
                seen_ids.add(g.id)
            all_games.extend(new)
            print(f"  {filepath}: {len(games)} rows, {len(new)} new",
                  file=sys.stderr)

        print(f"  total: {len(all_games)} sprint games", file=sys.stderr)

        raw_stats = fetch_stats(args.username, 1)
        if raw_stats:
            expected = raw_stats.get("games", "?")
            print(f"  stats API says: {expected} games", file=sys.stderr)
            if isinstance(expected, int) and len(all_games) == expected:
                print(f"  OK: all games captured", file=sys.stderr)
            elif isinstance(expected, int):
                print(f"  WARNING: got {len(all_games)}/{expected}", file=sys.stderr)

            result["sprint_40l"]["stats"] = {
                "best":           raw_stats.get("min"),
                "worst":          raw_stats.get("max"),
                "average":        raw_stats.get("avg"),
                "total_sum":      raw_stats.get("sum"),
                "total_games":    raw_stats.get("games"),
                "days_since_pb":  raw_stats.get("days"),
                "stat_mode":      raw_stats.get("mode"),
            }

        result["sprint_40l"]["games"] = [asdict(g) for g in all_games]

    # ── Ultra ──
    if args.ultra:
        print(f"\nUltra: parsing {len(args.ultra)} file(s)...", file=sys.stderr)

        all_games = []
        seen_ids = set()
        for filepath in args.ultra:
            games = parse_html_file(filepath)
            new = [g for g in games if g.id not in seen_ids]
            for g in new:
                seen_ids.add(g.id)
            all_games.extend(new)
            print(f"  {filepath}: {len(games)} rows, {len(new)} new",
                  file=sys.stderr)

        print(f"  total: {len(all_games)} ultra games", file=sys.stderr)

        raw_stats = fetch_stats(args.username, 5)
        if raw_stats:
            expected = raw_stats.get("games", "?")
            print(f"  stats API says: {expected} games", file=sys.stderr)
            if isinstance(expected, int) and len(all_games) == expected:
                print(f"  OK: all games captured", file=sys.stderr)
            elif isinstance(expected, int):
                print(f"  WARNING: got {len(all_games)}/{expected}", file=sys.stderr)

            result["ultra"]["stats"] = {
                "best":           raw_stats.get("min"),
                "worst":          raw_stats.get("max"),
                "average":        raw_stats.get("avg"),
                "total_sum":      raw_stats.get("sum"),
                "total_games":    raw_stats.get("games"),
                "days_since_pb":  raw_stats.get("days"),
                "stat_mode":      raw_stats.get("mode"),
            }

        result["ultra"]["games"] = [asdict(g) for g in all_games]

    # ── Summary & save ──
    n_sprint = len(result["sprint_40l"]["games"])
    n_ultra = len(result["ultra"]["games"])
    print(f"\n{'─'*40}", file=sys.stderr)
    print(f"  Sprint 40L: {n_sprint} games", file=sys.stderr)
    print(f"  Ultra:      {n_ultra} games", file=sys.stderr)
    print(f"  Total:      {n_sprint + n_ultra} games", file=sys.stderr)
    print(f"{'─'*40}", file=sys.stderr)

    out_path = os.path.join(args.output_dir, f"jstris_{args.username}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  Saved -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
