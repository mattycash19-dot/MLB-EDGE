"""
Starting pitcher + bullpen quality, from MLB's free public Stats API only.

Why not /teams/{id}/stats for bullpen: tested during development and found
unreliable (returns inconsistent gamesPlayed/gamesStarted that don't
reconcile with the team's actual record, even when explicitly requesting
the relief-pitching split via sitCodes=rp - see mlb_data.py notes). Instead,
this pulls the active roster and aggregates each individual pitcher's
season stats, which IS reliable (verified: individual /people/{id}/stats
numbers are internally consistent - earnedRuns/IP*9 matches reported ERA).

FIP note: uses a fixed FIP constant (3.10) rather than deriving the exact
year's constant from league-wide HR/BB/K/IP totals. The constant is just an
additive offset to make FIP land on an ERA-like scale - it doesn't change
pitcher-vs-pitcher comparisons, which is all this model uses it for.
"""
import json
import urllib.request
from datetime import date

BASE = "https://statsapi.mlb.com/api/v1"
FIP_CONSTANT = 3.10
LEAGUE_AVG_ERA = 4.20  # rough modern-era MLB league average, used as a fallback


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mlb-edge-calculator/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_probable_pitchers(game_date=None):
    """
    Returns {game_pk: {"home": {...} or None, "away": {...} or None}}
    where each pitcher dict is {"id":, "name":}. None if not yet announced
    (common more than a couple days out).
    """
    game_date = game_date or date.today().isoformat()
    url = f"{BASE}/schedule?sportId=1&date={game_date}&hydrate=probablePitcher"
    data = _get(url)
    result = {}
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("gameType") != "R":
                continue
            entry = {}
            for side in ("home", "away"):
                pp = g["teams"][side].get("probablePitcher")
                entry[side] = {"id": pp["id"], "name": pp["fullName"]} if pp else None
            result[g["gamePk"]] = entry
    return result


def get_pitcher_season_stats(pitcher_id, season=None):
    """Raw season pitching line for one pitcher. Returns None if no data (e.g. hasn't pitched)."""
    season = season or date.today().year
    data = _get(f"{BASE}/people/{pitcher_id}/stats?stats=season&group=pitching&season={season}")
    # .get("stats", [{}]) only supplies the default when the key is absent -
    # the API returns {"stats": []} (present but empty) for a pitcher with no
    # season data yet, and [][0] would raise IndexError instead of hitting
    # the "no data" case this function is supposed to degrade to gracefully.
    stats_list = data.get("stats") or [{}]
    splits = stats_list[0].get("splits", [])
    if not splits:
        return None
    s = splits[0]["stat"]
    ip = float(s.get("inningsPitched", "0") or 0)
    return {
        "innings_pitched": ip,
        "era": float(s.get("era", "0") or 0),
        "whip": float(s.get("whip", "0") or 0),
        "strikeouts": s.get("strikeOuts", 0),
        "walks": s.get("baseOnBalls", 0),
        "hbp": s.get("hitByPitch", 0),
        "home_runs": s.get("homeRuns", 0),
        "earned_runs": s.get("earnedRuns", 0),
        "games_started": s.get("gamesStarted", 0),
        "games_pitched": s.get("gamesPitched", 0),
    }


def fip(stats):
    """Fielding Independent Pitching from a raw stat line (see get_pitcher_season_stats)."""
    ip = stats["innings_pitched"]
    if ip <= 0:
        return None
    numerator = (13 * stats["home_runs"]) + (3 * (stats["walks"] + stats["hbp"])) - (2 * stats["strikeouts"])
    return numerator / ip + FIP_CONSTANT


def get_recent_starts(pitcher_id, n=3, season=None):
    """
    Returns {"n_starts": int, "era": float, "innings_pitched": float} summarizing
    a pitcher's last n starts (game log), or None if unavailable. This is
    the "hot/cold lately" complement to the season-long FIP/ERA numbers -
    useful for spotting a pitcher trending very differently from his season
    line (e.g. an ace who's scuffled his last 3 outings, or a back-end
    starter who's been dealing lately).
    """
    season = season or date.today().year
    data = _get(f"{BASE}/people/{pitcher_id}/stats?stats=gameLog&group=pitching&season={season}")
    # same empty-vs-absent-key gap as get_pitcher_season_stats above
    stats_list = data.get("stats") or [{}]
    splits = stats_list[0].get("splits", [])
    # only count actual starts (gamesStarted == 1 in that game's log entry)
    starts = [s for s in splits if s.get("stat", {}).get("gamesStarted", 0) == 1]
    if not starts:
        return None
    recent = starts[-n:]
    total_ip = sum(float(s["stat"].get("inningsPitched", "0") or 0) for s in recent)
    total_er = sum(s["stat"].get("earnedRuns", 0) for s in recent)
    if total_ip <= 0:
        return None
    return {
        "n_starts": len(recent),
        "era": round((total_er / total_ip) * 9, 2),
        "innings_pitched": round(total_ip, 1),
    }


def get_active_pitching_staff(team_id):
    """Active roster pitchers: [{"id":, "name":}]."""
    data = _get(f"{BASE}/teams/{team_id}/roster?rosterType=active")
    return [
        {"id": p["person"]["id"], "name": p["person"]["fullName"]}
        for p in data.get("roster", [])
        if p.get("position", {}).get("type") == "Pitcher"
    ]


def get_bullpen_era(team_id, season=None, exclude_pitcher_id=None):
    """
    Aggregates innings-weighted ERA across relief pitchers on the active
    roster (gamesStarted == 0, or mostly relief work). exclude_pitcher_id
    lets you exclude today's probable starter if he also has relief
    appearances logged (rare, but avoids double counting).
    Returns None if no reliever innings found (falls back to LEAGUE_AVG_ERA
    should be applied by the caller).
    """
    season = season or date.today().year
    staff = get_active_pitching_staff(team_id)
    total_er = 0.0
    total_ip = 0.0
    for p in staff:
        if p["id"] == exclude_pitcher_id:
            continue
        stats = get_pitcher_season_stats(p["id"], season=season)
        if not stats or stats["innings_pitched"] <= 0:
            continue
        gs, gp = stats["games_started"], stats["games_pitched"]
        is_reliever = gs == 0 or (gp > 0 and gs / gp < 0.4)
        if not is_reliever:
            continue
        total_er += stats["earned_runs"]
        total_ip += stats["innings_pitched"]
    if total_ip <= 0:
        return None
    return (total_er / total_ip) * 9


def starter_adjusted_runs_allowed_per9(starter_stats, bullpen_era, starter_innings_fraction=0.57):
    """
    Blends today's starter's FIP with the team's bullpen ERA, weighted by
    how much of a typical game each covers (~5.1 of 9 innings for a starter
    in the modern game, rest to the bullpen). Falls back to league average
    for whichever half is missing data.
    """
    starter_fip = fip(starter_stats) if starter_stats else None
    if starter_fip is None:
        starter_fip = LEAGUE_AVG_ERA
    if bullpen_era is None:
        bullpen_era = LEAGUE_AVG_ERA
    return (starter_innings_fraction * starter_fip) + ((1 - starter_innings_fraction) * bullpen_era)
