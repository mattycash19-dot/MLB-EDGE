"""
Fetches MLB schedule and season stats from MLB's free, public Stats API
(statsapi.mlb.com). No API key required.

NOTE on data source: runs scored/allowed come from the /standings endpoint,
not /teams/{id}/stats. During testing, /teams/{id}/stats returned inconsistent
"gamesPlayed" totals that didn't reconcile with the team's actual win-loss
record (e.g. it returned 71 games played for a team with a 96-game record in
one query, and 105 games in another, depending on params) - it appears to
aggregate from individual player logs rather than true team totals, which
makes it unreliable for this purpose. /standings gives wins/losses/
runsScored/runsAllowed/runDifferential directly, and they reconcile internally
(runsScored - runsAllowed == runDifferential every time this was checked) -
so that's the source of truth used here.
"""
import json
import urllib.request
from datetime import date

BASE = "https://statsapi.mlb.com/api/v1"
AL_LEAGUE_ID = 103
NL_LEAGUE_ID = 104


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mlb-edge-calculator/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_schedule(game_date=None):
    """Returns today's (or a given date's) MLB games."""
    game_date = game_date or date.today().isoformat()
    url = f"{BASE}/schedule?sportId=1&date={game_date}"
    data = _get(url)
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("gameType") != "R":
                continue  # skip spring training / exhibition / postseason for now
            games.append({
                "game_pk": g["gamePk"],
                "date": g["officialDate"],
                "status": g["status"]["detailedState"],
                # abstractGameState is one of "Preview" / "Live" / "Final" -
                # the coarse bucket dashboard.py needs to decide whether a
                # game still belongs on "today's slate" or has already
                # happened (detailedState has finer values like "Postponed"
                # or "Warmup" that aren't useful for that decision).
                "abstract_state": g["status"]["abstractGameState"],
                "away_id": g["teams"]["away"]["team"]["id"],
                "away_name": g["teams"]["away"]["team"]["name"],
                "away_record": g["teams"]["away"].get("leagueRecord", {}),
                "away_score": g["teams"]["away"].get("score"),
                "home_id": g["teams"]["home"]["team"]["id"],
                "home_name": g["teams"]["home"]["team"]["name"],
                "home_record": g["teams"]["home"].get("leagueRecord", {}),
                "home_score": g["teams"]["home"].get("score"),
                "venue_id": g.get("venue", {}).get("id"),
                "venue_name": g.get("venue", {}).get("name"),
            })
    return games


def get_all_teams_stats(team_ids=None, season=None):
    """
    Returns dict of team_id -> {wins, losses, runs_scored, runs_allowed,
    streak_code, last_ten} for every team in both leagues, pulled from the
    standings endpoint in a single request (much cheaper than one call per
    team). streak_code/last_ten power the "recent form" note in writeup.py
    - see get_team_recent_form() below for a standalone accessor.

    team_ids is accepted for API compatibility but ignored - we just fetch
    everyone, since it's one request either way.

    IMPORTANT: this single request is also relied on for recent-form data.
    If you call this once per report build (as build_report.py does) both
    season totals and streak/last-10 come from the same snapshot, so they
    can't contradict each other the way they would if fetched separately at
    different times (a real inconsistency observed once in this project's
    dev sandbox - see README - not expected against the real live API, but
    this single-call design avoids the risk either way).
    """
    season = season or date.today().year
    fields = ("records,teamRecords,team,id,name,wins,losses,runsAllowed,runsScored,"
              "runDifferential,streak,streakCode,streakType,streakNumber,"
              "records,splitRecords,type,pct")
    url = (f"{BASE}/standings?leagueId={AL_LEAGUE_ID},{NL_LEAGUE_ID}&season={season}"
           f"&standingsTypes=regularSeason&fields={fields}")
    data = _get(url)

    stats = {}
    for division in data.get("records", []):
        for tr in division.get("teamRecords", []):
            team = tr.get("team", {})
            tid = team.get("id")
            if tid is None:
                continue
            last_ten = None
            for split in tr.get("records", {}).get("splitRecords", []):
                if split.get("type") == "lastTen":
                    last_ten = f"{split.get('wins', '-')}-{split.get('losses', '-')}"
                    break
            stats[tid] = {
                "team_id": tid,
                "team_name": team.get("name"),
                "wins": tr.get("wins", 0),
                "losses": tr.get("losses", 0),
                "runs_scored": tr.get("runsScored", 0),
                "runs_allowed": tr.get("runsAllowed", 0),
                "streak_code": tr.get("streak", {}).get("streakCode"),
                "last_ten": last_ten,
            }
    return stats


def get_team_recent_form(team_id, all_teams_stats=None, season=None):
    """
    Returns {"streak_code": "W3"/"L2"/etc, "last_ten": "7-3"} for one team,
    or None if unavailable. Pass in an already-fetched all_teams_stats dict
    (from get_all_teams_stats) to avoid a redundant request when building a
    full report; otherwise this fetches its own copy.
    """
    stats = all_teams_stats or get_all_teams_stats(season=season)
    entry = stats.get(team_id)
    if not entry:
        return None
    return {"streak_code": entry.get("streak_code"), "last_ten": entry.get("last_ten")}
