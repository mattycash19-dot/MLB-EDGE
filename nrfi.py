"""
NRFI ("No Run First Inning") model - built from the same discipline as the
three prompt templates in the vault note this was framed from
(70-learning/sports-betting/001-nrfi-ai-prompt-templates.md): don't trust a
season-aggregate number for something as situation-specific as "does either
team score in the first inning" - isolate the first-inning-specific slice
of real data, check whether today's specific matchup (today's lineup, days
of rest) points the same way or differently, and say plainly when a piece
of that isn't available rather than guessing.

Three factors, each backed by real, free MLB Stats API data - no fabricated
inputs:

1. INNING SPLIT - each starter's actual first-inning run rate this season
   (MLB's official "First Inning" stat split, sitCodes=i01), not his season
   ERA. This is the core signal: a Poisson model of runs allowed in one
   inning, using each starter's real first-inning-specific rate.
2. ORDER CHECK - today's actual posted batting order (when available - MLB
   typically posts lineups 1-3 hours before first pitch, so this is often
   still unavailable at the time a morning report runs) for the top ~4
   hitters each starter will actually face in a clean first inning, nudging
   the pitcher's base rate up/down by how their real season OBP compares to
   a league-average leadoff-quality hitter. Skipped (net neutral, and
   labeled as such) when the lineup isn't posted yet - no fallback guess.
3. RUST FACTOR - real, calculable situational risk: days since each
   starter's last outing (from his game log), flagging short rest (<=3
   days, unusual and often a bullpen/emergency start) or long rest (>=8
   days, IL return or extra rest) with a small, capped nudge. Day/night is
   surfaced as information in the write-up but not given a numeric weight -
   there's no well-established, honestly-sized effect for that alone to
   apply. Weather is NOT included: no free, reliable per-game weather data
   source is wired into this pipeline, and fabricating a "cold game" effect
   without real temperature data would be exactly the kind of invented
   precision this whole project's "Scope note" (see README) already
   declines to do elsewhere.

Market comparison: The Odds API's free tier support for a first-inning-
specific market is unverified (no live key was available to test against
while building this) - get_nrfi_odds() is written defensively and simply
returns None if the market isn't present in the response, in which case
the NRFI tab shows the model probability only, same graceful pattern the
main dashboard already uses when no odds key is configured at all.
"""
import math
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))
import pitching

LEAGUE_AVG_OBP = 0.320  # rough modern-era MLB league-average OBP, used as the Order Check baseline
ORDER_CHECK_WEIGHT = 0.35  # caps how much lineup OBP can move the base rate (see order_check_adjustment)
SHORT_REST_DAYS = 3
LONG_REST_DAYS = 8
REST_NUDGE = 0.08  # capped +/-8% multiplicative nudge to lambda for extreme rest, either direction
BATTERS_IN_CLEAN_INNING = 4  # top ~4 hitters is what "guarantees to bat in the first" (Order Check template)


def get_first_inning_split(pitcher_id, season=None):
    """
    Real, official first-inning-only stat line for one pitcher (MLB Stats
    API sitCodes=i01 - confirmed to exist and return real per-pitcher data,
    not season totals, via a live query during development). Uses total
    runs (not just earned runs) since an unearned run still breaks NRFI.
    Returns {"starts": n, "runs": r, "runs_per_start": rate} or None if this
    pitcher has no first-inning data logged yet this season (e.g. hasn't
    started a game).
    """
    season = season or date.today().year
    data = pitching._get(
        f"{pitching.BASE}/people/{pitcher_id}/stats?stats=statSplits&group=pitching"
        f"&sitCodes=i01&season={season}"
    )
    stats_list = data.get("stats") or [{}]
    splits = stats_list[0].get("splits", [])
    if not splits:
        return None
    s = splits[0]["stat"]
    starts = s.get("gamesPlayed", 0)
    if starts <= 0:
        return None
    runs = s.get("runs", 0)
    return {"starts": starts, "runs": runs, "runs_per_start": runs / starts}


def get_days_rest(pitcher_id, before_date, season=None):
    """
    Days between a pitcher's most recent start strictly before `before_date`
    (ISO date string) and that date, from his real game log. Returns None
    if no prior start is found this season (e.g. his season debut today).
    """
    season = season or date.today().year
    data = pitching._get(
        f"{pitching.BASE}/people/{pitcher_id}/stats?stats=gameLog&group=pitching&season={season}"
    )
    stats_list = data.get("stats") or [{}]
    splits = stats_list[0].get("splits", [])
    starts = [s for s in splits if s.get("stat", {}).get("gamesStarted", 0) == 1 and s.get("date")]
    prior = [s for s in starts if s["date"] < before_date]
    if not prior:
        return None
    prior.sort(key=lambda s: s["date"])
    last_start = datetime.strptime(prior[-1]["date"], "%Y-%m-%d").date()
    game_day = datetime.strptime(before_date, "%Y-%m-%d").date()
    return (game_day - last_start).days


def get_lineup_top_order_obp(lineup_players, n=BATTERS_IN_CLEAN_INNING, season=None):
    """
    Given the ordered list of hitter dicts from a schedule's lineups hydrate
    (already batting-order-sequential per MLB's API), fetches each of the
    top `n` hitters' real season OBP and averages them. Returns
    (avg_obp, n_used) or (None, 0) if no lineup was posted (empty list) -
    the caller should skip the Order Check adjustment entirely in that
    case, not guess at a fallback.
    """
    if not lineup_players:
        return None, 0
    season = season or date.today().year
    obps = []
    for p in lineup_players[:n]:
        try:
            data = pitching._get(
                f"{pitching.BASE}/people/{p['id']}/stats?stats=season&group=hitting&season={season}"
            )
            stats_list = data.get("stats") or [{}]
            splits = stats_list[0].get("splits", [])
            if not splits:
                continue
            obp = splits[0]["stat"].get("obp")
            if obp:
                obps.append(float(obp))
        except Exception:
            continue
    if not obps:
        return None, 0
    return sum(obps) / len(obps), len(obps)


def order_check_adjustment(avg_obp, weight=ORDER_CHECK_WEIGHT, baseline=LEAGUE_AVG_OBP):
    """
    Converts a lineup's top-of-order average OBP into a multiplicative
    adjustment on the opposing pitcher's first-inning run rate: an
    above-average top of the order (more real baserunners) raises it, a
    weak one lowers it. Capped by `weight` so an extreme lineup can shift
    the rate by at most +/-`weight` (35% default) rather than dominating
    the pitcher's own real first-inning track record. Returns 1.0 (no
    adjustment) if avg_obp is None (lineup not posted yet).
    """
    if avg_obp is None:
        return 1.0
    relative = (avg_obp - baseline) / baseline
    return 1.0 + max(-weight, min(weight, relative))


def rest_adjustment(days_rest, short=SHORT_REST_DAYS, long_=LONG_REST_DAYS, nudge=REST_NUDGE):
    """
    Small, capped multiplicative nudge for extreme rest situations - short
    rest (bullpen game / emergency start, unusual command risk) or long
    rest (returning from IL or an extra-long break, rust risk). Normal
    4-6 day rest (the standard rotation) gets no adjustment at all. Returns
    1.0 if days_rest is None (no prior start found, e.g. season debut).
    """
    if days_rest is None:
        return 1.0
    if days_rest <= short:
        return 1.0 + nudge
    if days_rest >= long_:
        return 1.0 + nudge
    return 1.0


def combined_nrfi_probability(home_starter_1st, away_starter_1st,
                               home_lineup_obp=None, away_lineup_obp=None,
                               home_starter_rest=None, away_starter_rest=None):
    """
    Full NRFI model for one game. The home starter faces the away lineup in
    the top of the 1st; the away starter faces the home lineup in the
    bottom of the 1st - each half treated as independent (standard
    simplifying assumption for a first-inning-only model like this).

    home_starter_1st / away_starter_1st: dicts from get_first_inning_split()
    (or None if unavailable - falls back to a league-average first-inning
    rate rather than skipping the game entirely).
    home_lineup_obp / away_lineup_obp: avg OBP from get_lineup_top_order_obp()
    for the OPPOSING lineup each starter is about to face (i.e. pass
    away_lineup_obp when evaluating the home starter's half).

    Returns a dict with the combined probability and enough of the pieces
    to show a real breakdown, not just a final number.
    """
    league_avg_1st_rate = 0.12  # MLB has historically run ~50-52% NRFI league-wide; solving
    # e^(-2*lam) = 0.51 for a symmetric lam gives ~0.336 per half - but that's the OUTCOME to
    # match, not an input assumption. Using each pitcher's own real rate (with this as a
    # graceful fallback only when his data is missing) is what actually drives the model;
    # this constant is deliberately close to a typical individual full-season first-inning
    # run rate (roughly 0.10-0.15 earned+unearned runs per first inning for a average starter)
    # rather than reverse-engineered from the league NRFI rate.

    home_rate = home_starter_1st["runs_per_start"] if home_starter_1st else league_avg_1st_rate
    away_rate = away_starter_1st["runs_per_start"] if away_starter_1st else league_avg_1st_rate

    home_order_adj = order_check_adjustment(away_lineup_obp)  # home starter faces away lineup
    away_order_adj = order_check_adjustment(home_lineup_obp)  # away starter faces home lineup

    home_rest_adj = rest_adjustment(home_starter_rest)
    away_rest_adj = rest_adjustment(away_starter_rest)

    lam_top = max(home_rate * home_order_adj * home_rest_adj, 0.0)   # away scores off home starter
    lam_bot = max(away_rate * away_order_adj * away_rest_adj, 0.0)   # home scores off away starter

    p_top_scoreless = math.exp(-lam_top)
    p_bot_scoreless = math.exp(-lam_bot)
    p_nrfi = p_top_scoreless * p_bot_scoreless

    return {
        "nrfi_prob": round(p_nrfi, 4),
        "yrfi_prob": round(1 - p_nrfi, 4),
        "home_starter_1st_rate": round(home_rate, 3),
        "away_starter_1st_rate": round(away_rate, 3),
        "home_starter_1st_starts": (home_starter_1st or {}).get("starts"),
        "away_starter_1st_starts": (away_starter_1st or {}).get("starts"),
        "home_order_adj": round(home_order_adj, 3),
        "away_order_adj": round(away_order_adj, 3),
        "away_lineup_obp": round(away_lineup_obp, 3) if away_lineup_obp is not None else None,
        "home_lineup_obp": round(home_lineup_obp, 3) if home_lineup_obp is not None else None,
        "home_starter_rest_days": home_starter_rest,
        "away_starter_rest_days": away_starter_rest,
        "lineup_posted": away_lineup_obp is not None or home_lineup_obp is not None,
    }


def get_nrfi_odds(event):
    """
    Attempts to find a first-inning-specific market ('h2h_1st_1_innings' or
    'totals_1st_1_innings' are the market keys some odds providers use for
    this) in an already-fetched Odds API event. Returns None if not
    present - this market's availability on The Odds API's free tier was
    unverified while building this (no live key to test against), so
    callers must treat None as "show model-only," the same graceful
    fallback the rest of this site already uses for missing odds data.
    """
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") in ("h2h_1st_1_innings", "totals_1st_1_innings"):
                return market
    return None
