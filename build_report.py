"""
Orchestrates the daily report:
  1. Pull today's MLB schedule + probable pitchers (free, no key).
  2. Pull season stats for every team playing today, from /standings (free, no key).
  3. Pull each probable starter's season line and compute FIP; aggregate
     each team's bullpen ERA from its active roster (free, no key, but
     several dozen requests - expect this step to take a bit of wall-clock
     time on a real run).
  4. Look up each venue's park run factor (static reference table).
  5. Compute an adjusted win probability blending team offense, today's
     specific starter/bullpen quality, and park - plus, for comparison, the
     simpler season-Pythagorean-only probability from the first version of
     this tool.
  6. Pull moneyline odds (needs a free Odds API key), devig to a consensus
     market probability, and log a snapshot for line-movement tracking.
  7. Compute edge = model probability - market probability.
  8. Write report.json and dashboard.html.

Missing data degrades gracefully: no probable pitcher announced yet (common
more than a couple days out) falls back to league-average pitching for that
side; no odds key shows model probabilities only.
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))

import mlb_data
import model
import odds_data
import pitching
import park_factors
import line_movement
import writeup

OUT_DIR = os.path.dirname(__file__)


def _team_offense_rpg(stats):
    games = stats.get("wins", 0) + stats.get("losses", 0)
    if games <= 0:
        return pitching.LEAGUE_AVG_ERA  # neutral fallback, ~league average runs/game
    return stats.get("runs_scored", 0) / games


def _team_pitching_ra9(team_id, starter_info, bullpen_cache):
    """Returns (ra9, starter_name, starter_fip, bullpen_era, starter_stats)."""
    starter_stats = None
    starter_name = None
    starter_fip = None
    if starter_info:
        starter_name = starter_info["name"]
        starter_stats = pitching.get_pitcher_season_stats(starter_info["id"])
        if starter_stats:
            starter_fip = pitching.fip(starter_stats)

    if team_id not in bullpen_cache:
        exclude_id = starter_info["id"] if starter_info else None
        bullpen_cache[team_id] = pitching.get_bullpen_era(team_id, exclude_pitcher_id=exclude_id)
    bullpen_era = bullpen_cache[team_id]

    ra9 = pitching.starter_adjusted_runs_allowed_per9(starter_stats, bullpen_era)
    return ra9, starter_name, starter_fip, bullpen_era, starter_stats


def build(game_date=None, include_pitching=True):
    game_date = game_date or date.today().isoformat()
    games = mlb_data.get_schedule(game_date)

    if not games:
        return {"date": game_date, "generated_at": datetime.now().isoformat(), "games": [],
                "odds_available": False, "odds_error": "No games scheduled."}

    team_ids = sorted({g["home_id"] for g in games} | {g["away_id"] for g in games})
    stats_by_team = mlb_data.get_all_teams_stats(team_ids)

    probable_pitchers = {}
    if include_pitching:
        try:
            probable_pitchers = pitching.get_probable_pitchers(game_date)
        except Exception:
            probable_pitchers = {}

    odds_events = []
    odds_error = None
    try:
        odds_events = odds_data.get_mlb_odds()
    except odds_data.NoApiKeyError as e:
        odds_error = str(e)
    except Exception as e:  # network/API errors shouldn't kill the whole report
        odds_error = f"Odds fetch failed: {e}"

    def norm(s):
        return s.lower().replace(".", "").strip()

    odds_by_teams = {}
    for ev in odds_events:
        key = (norm(ev.get("home_team", "")), norm(ev.get("away_team", "")))
        odds_by_teams[key] = ev

    bullpen_cache = {}
    report_games = []
    for g in games:
        home_stats = stats_by_team.get(g["home_id"], {"runs_scored": 0, "runs_allowed": 0, "wins": 0, "losses": 0})
        away_stats = stats_by_team.get(g["away_id"], {"runs_scored": 0, "runs_allowed": 0, "wins": 0, "losses": 0})

        # baseline: original season-Pythagorean-only model, kept for comparison
        season_home_prob, season_away_prob = model.model_win_probability(home_stats, away_stats)

        entry = {
            "game_pk": g["game_pk"],
            "status": g.get("status"),
            "abstract_state": g.get("abstract_state"),
            "away_team": g["away_name"],
            "home_team": g["home_name"],
            "away_score": g.get("away_score"),
            "home_score": g.get("home_score"),
            "away_record": g["away_record"],
            "home_record": g["home_record"],
            "venue_name": g.get("venue_name"),
            "park_factor": park_factors.get_park_factor(g.get("venue_id")),
            "home_starter": None,
            "away_starter": None,
            "home_model_prob_season_only": round(season_home_prob, 4),
            "away_model_prob_season_only": round(season_away_prob, 4),
            "home_model_prob": round(season_home_prob, 4),  # overwritten below if pitching data available
            "away_model_prob": round(season_away_prob, 4),
            "home_market_prob": None,
            "away_market_prob": None,
            "home_market_ml": None,
            "away_market_ml": None,
            "home_model_ml": model.probability_to_moneyline(season_home_prob),
            "away_model_ml": model.probability_to_moneyline(season_away_prob),
            "home_edge": None,
            "away_edge": None,
            "home_movement": None,
            "home_opening_ml": None,
            "away_opening_ml": None,
            "num_books": 0,
            "home_run_diff": home_stats.get("runs_scored", 0) - home_stats.get("runs_allowed", 0),
            "away_run_diff": away_stats.get("runs_scored", 0) - away_stats.get("runs_allowed", 0),
        }

        if include_pitching:
            try:
                home_pitcher_info = probable_pitchers.get(g["game_pk"], {}).get("home")
                away_pitcher_info = probable_pitchers.get(g["game_pk"], {}).get("away")

                home_ra9, home_starter_name, home_starter_fip, home_bp_era, home_starter_stats = _team_pitching_ra9(
                    g["home_id"], home_pitcher_info, bullpen_cache)
                away_ra9, away_starter_name, away_starter_fip, away_bp_era, away_starter_stats = _team_pitching_ra9(
                    g["away_id"], away_pitcher_info, bullpen_cache)

                home_off_rpg = _team_offense_rpg(home_stats)
                away_off_rpg = _team_offense_rpg(away_stats)

                home_prob, away_prob, home_proj_runs, away_proj_runs = model.adjusted_win_probability(
                    home_off_rpg, away_off_rpg, home_ra9, away_ra9,
                    park_factor=entry["park_factor"])

                entry["home_model_prob"] = round(home_prob, 4)
                entry["away_model_prob"] = round(away_prob, 4)
                entry["home_model_ml"] = model.probability_to_moneyline(home_prob)
                entry["away_model_ml"] = model.probability_to_moneyline(away_prob)
                entry["home_projected_runs"] = round(home_proj_runs, 2)
                entry["away_projected_runs"] = round(away_proj_runs, 2)
                entry["projected_run_diff"] = round(home_proj_runs - away_proj_runs, 2)
                entry["home_starter"] = {
                    "name": home_starter_name, "fip": round(home_starter_fip, 2) if home_starter_fip else None,
                    "era": home_starter_stats.get("era") if home_starter_stats else None,
                    "games_started": home_starter_stats.get("games_started") if home_starter_stats else None,
                    "innings_pitched": home_starter_stats.get("innings_pitched") if home_starter_stats else None,
                    "bullpen_era": round(home_bp_era, 2) if home_bp_era else None,
                }
                entry["away_starter"] = {
                    "name": away_starter_name, "fip": round(away_starter_fip, 2) if away_starter_fip else None,
                    "era": away_starter_stats.get("era") if away_starter_stats else None,
                    "games_started": away_starter_stats.get("games_started") if away_starter_stats else None,
                    "innings_pitched": away_starter_stats.get("innings_pitched") if away_starter_stats else None,
                    "bullpen_era": round(away_bp_era, 2) if away_bp_era else None,
                }
            except Exception as e:
                # if pitching data fails for this game, keep the season-only numbers already set
                entry["pitching_error"] = str(e)

        entry["home_recent_form"] = mlb_data.get_team_recent_form(g["home_id"], all_teams_stats=stats_by_team)
        entry["away_recent_form"] = mlb_data.get_team_recent_form(g["away_id"], all_teams_stats=stats_by_team)

        ev = odds_by_teams.get((norm(g["home_name"]), norm(g["away_name"])))
        if ev:
            home_mkt, away_mkt, n_books = odds_data.consensus_moneylines(ev)
            if home_mkt is not None:
                entry["home_market_prob"] = round(home_mkt, 4)
                entry["away_market_prob"] = round(away_mkt, 4)
                entry["home_edge"] = round(entry["home_model_prob"] - home_mkt, 4)
                entry["away_edge"] = round(entry["away_model_prob"] - away_mkt, 4)
                entry["num_books"] = n_books

                home_ml, away_ml, _ = odds_data.consensus_market_moneylines(ev)
                entry["home_market_ml"] = home_ml
                entry["away_market_ml"] = away_ml

                try:
                    line_movement.append_snapshot(game_date, g["game_pk"], g["home_name"], g["away_name"],
                                                   home_mkt, away_mkt)
                    movement, opening_home, opening_away, n_snap = line_movement.get_movement(
                        g["game_pk"], home_mkt, game_date)
                    entry["home_movement"] = movement
                    entry["num_snapshots_today"] = n_snap
                    if opening_home is not None:
                        entry["home_opening_ml"] = model.probability_to_moneyline(opening_home)
                        entry["away_opening_ml"] = model.probability_to_moneyline(opening_away)
                except Exception:
                    pass

        try:
            entry["writeup"] = writeup.generate_writeup(entry, bullpen_is_league_avg=False)
        except Exception as e:
            entry["writeup"] = None
            entry["writeup_error"] = str(e)

        report_games.append(entry)

    def sort_key(e):
        if e.get("abstract_state") == "Final":
            return (2, 0)  # already happened - not a pick for today, sort last
        if e["home_edge"] is None:
            return (1, 0)
        return (0, -abs(e["home_edge"]))

    report_games.sort(key=sort_key)

    return {
        "date": game_date,
        "generated_at": datetime.now().isoformat(),
        "games": report_games,
        "odds_available": odds_error is None,
        "odds_error": odds_error,
    }


def write_report(report, out_dir=OUT_DIR):
    json_path = os.path.join(out_dir, "report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    return json_path


if __name__ == "__main__":
    report = build()
    path = write_report(report)
    n = len(report["games"])
    print(f"Wrote {path} with {n} games for {report['date']}.")
    if not report["odds_available"]:
        print(f"NOTE: {report['odds_error']}")
