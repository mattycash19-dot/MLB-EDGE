"""
Generates a short, plain-language write-up per game explaining why the
model landed where it did - which side it favors and by how much, how the
starters compare (including a flag when a FIP/ERA is built on a small
sample), what the bullpen and park are doing, how the two teams' season
run differential compares, and recent form (hot/cold streak, last 10
record, pitcher's last 3 starts) when that data is available.

This is a template, not an LLM call: every sentence is generated from
numbers already computed elsewhere in the pipeline (model.py, pitching.py,
park_factors.py). Nothing here is invented - if a data point isn't
available (no starter announced yet, no recent-form data this run), the
write-up says so directly instead of guessing or leaving a gap that reads
like an oversight.
"""


def _small_sample(games_started, innings_pitched):
    if games_started is not None and games_started < 8:
        return True
    if innings_pitched is not None and innings_pitched < 35:
        return True
    return False


def _starter_note(label, starter):
    if not starter or not starter.get("name"):
        return f"{label} hasn't been announced yet, so that side uses a league-average pitching fallback (~4.20 ERA/FIP) rather than a guess."

    name = starter["name"]
    fip = starter.get("fip")
    era = starter.get("era")
    gs = starter.get("games_started")
    ip = starter.get("innings_pitched")

    if fip is None:
        return f"{name} ({label}) doesn't have a usable season pitching line yet, so this side falls back to league-average pitching."

    parts = [f"{name} carries a {fip:.2f} FIP this season"]
    if era is not None:
        gap = era - fip
        if abs(gap) >= 0.75:
            direction = "underperforming" if gap > 0 else "overperforming"
            worse_better = "been unlucky (or hurt by defense/bullpen)" if gap > 0 else "gotten some help from luck, defense, or sequencing"
            parts.append(
                f"against a {era:.2f} ERA - a {abs(gap):.2f}-run gap suggests he's {worse_better} relative to what he actually controls (strikeouts, walks, homers)"
            )
        else:
            parts.append(f"with a {era:.2f} ERA that's basically in line with it - no real luck gap either way")
    sentence = " ".join(parts) + "."

    if _small_sample(gs, ip):
        gs_str = f"{gs} starts" if gs is not None else "few starts"
        ip_str = f"{ip:.0f} innings" if ip is not None else "not many innings"
        sentence += f" Worth flagging: only {gs_str} / {ip_str} this season - a small sample that can swing a lot with the next outing."
    return sentence


def _bullpen_note(home_bp, away_bp, bullpen_is_league_avg):
    if bullpen_is_league_avg:
        return ("Bullpen ERA for both sides is the league-average fallback (~4.20) for this run rather than each "
                "team's real relievers - see the note at the bottom of the page.")
    if home_bp is None or away_bp is None:
        return "Bullpen data wasn't available for one or both sides this run."
    diff = home_bp - away_bp
    if abs(diff) < 0.3:
        return f"Bullpens are close ({away_bp:.2f} vs {home_bp:.2f} ERA) - not a real separator here."
    better_side = "home" if diff > 0 else "away"
    return f"The {better_side} bullpen is the sharper of the two ({away_bp:.2f} away vs {home_bp:.2f} home ERA) - a real, if secondary, factor."


def _park_note(park_factor, venue_name):
    if park_factor is None:
        return ""
    if park_factor >= 103:
        return f"{venue_name} plays as a hitter-friendly park (factor {park_factor}), inflating scoring for both sides a bit."
    if park_factor <= 97:
        return f"{venue_name} plays as a pitcher-friendly park (factor {park_factor}), suppressing scoring for both sides a bit."
    return f"{venue_name} is close to a neutral run environment (factor {park_factor})."


def _run_diff_note(g):
    hrd = g.get("home_run_diff")
    ard = g.get("away_run_diff")
    if hrd is None or ard is None:
        return ""
    home_team, away_team = g["home_team"], g["away_team"]
    if abs(hrd - ard) < 10:
        return f"Season run differential is close between the two ({away_team} {ard:+d}, {home_team} {hrd:+d}) - this game looks more like a coin flip on the season-long picture alone."
    better = home_team if hrd > ard else away_team
    return f"On the season, {better} has clearly outscored its competition more ({away_team} {ard:+d} vs {home_team} {hrd:+d} run differential)."


def _recent_form_note(g):
    home_form = g.get("home_recent_form")
    away_form = g.get("away_recent_form")
    if not home_form and not away_form:
        return ("Recent hot/cold streak and last-10 record aren't available for this run (needs a live, "
                "consistent data pull - see project README) - only season-long numbers are reflected above.")
    bits = []
    for label, form in (("Away", away_form), ("Home", home_form)):
        if not form:
            continue
        streak = form.get("streak_code")
        last10 = form.get("last_ten")
        piece = label
        if streak:
            piece += f" is on a {streak}"
        if last10:
            piece += f" ({last10} last 10)"
        bits.append(piece)
    return "; ".join(bits) + "." if bits else ""


def generate_writeup(g, bullpen_is_league_avg=True):
    """Returns a short multi-sentence write-up string for one game entry."""
    sentences = []

    home_edge = g.get("home_edge")
    away_edge = g.get("away_edge")
    if home_edge is not None and away_edge is not None:
        if abs(home_edge) < 0.005:
            sentences.append("The model is essentially in agreement with the sportsbook price here - no meaningful edge either way.")
        else:
            favored = g["home_team"] if home_edge > 0 else g["away_team"]
            edge_val = abs(home_edge if home_edge > 0 else away_edge) * 100
            sentences.append(f"The model likes {favored} by about {edge_val:.1f} points more than the sportsbook price implies.")
    else:
        sentences.append("No market odds were available for this game yet, so there's no market comparison - just the model's own number.")

    sentences.append(_starter_note("away starter", g.get("away_starter")))
    sentences.append(_starter_note("home starter", g.get("home_starter")))

    bp_note = _bullpen_note(
        (g.get("home_starter") or {}).get("bullpen_era"),
        (g.get("away_starter") or {}).get("bullpen_era"),
        bullpen_is_league_avg,
    )
    if bp_note:
        sentences.append(bp_note)

    park_note = _park_note(g.get("park_factor"), g.get("venue_name"))
    if park_note:
        sentences.append(park_note)

    rd_note = _run_diff_note(g)
    if rd_note:
        sentences.append(rd_note)

    sentences.append(_recent_form_note(g))

    proj_diff = g.get("projected_run_diff")
    if proj_diff is not None and abs(proj_diff) >= 0.05:
        team = g["home_team"] if proj_diff > 0 else g["away_team"]
        sentences.append(f"Put together, today's specific matchup projects {team} to outscore its opponent by about {abs(proj_diff):.1f} runs.")

    return " ".join(s for s in sentences if s)
