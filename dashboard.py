"""Renders report.json into a self-contained, styled dashboard.html."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest

OUT_DIR = os.path.dirname(__file__)
CHANGELOG_PATH = os.path.join(OUT_DIR, "model_changelog.json")

# (abbr, background hex, text hex) per team, for the small color-monogram
# badge next to each team name — real logo artwork isn't pulled in since
# this is an offline, self-contained HTML file with no external image/CDN
# access. Keyed on the full team name as returned by MLB Stats API standings.
TEAM_COLORS = {
    "Baltimore Orioles": ("BAL", "#DF4601", "#000000"),
    "Boston Red Sox": ("BOS", "#BD3039", "#FFFFFF"),
    "New York Yankees": ("NYY", "#003087", "#FFFFFF"),
    "Tampa Bay Rays": ("TB", "#092C5C", "#FFFFFF"),
    "Toronto Blue Jays": ("TOR", "#134A8E", "#FFFFFF"),
    "Chicago White Sox": ("CWS", "#27251F", "#FFFFFF"),
    "Cleveland Guardians": ("CLE", "#00385D", "#FFFFFF"),
    "Detroit Tigers": ("DET", "#0C2340", "#FA4616"),
    "Kansas City Royals": ("KC", "#004687", "#FFFFFF"),
    "Minnesota Twins": ("MIN", "#002B5C", "#FFFFFF"),
    "Houston Astros": ("HOU", "#EB6E1F", "#002D62"),
    "Los Angeles Angels": ("LAA", "#BA0021", "#FFFFFF"),
    "Oakland Athletics": ("OAK", "#003831", "#EFB21E"),
    "Athletics": ("ATH", "#003831", "#EFB21E"),
    "Seattle Mariners": ("SEA", "#0C2C56", "#FFFFFF"),
    "Texas Rangers": ("TEX", "#003278", "#FFFFFF"),
    "Atlanta Braves": ("ATL", "#CE1141", "#FFFFFF"),
    "Miami Marlins": ("MIA", "#00A3E0", "#000000"),
    "New York Mets": ("NYM", "#002D72", "#FF5910"),
    "Philadelphia Phillies": ("PHI", "#E81828", "#FFFFFF"),
    "Washington Nationals": ("WSH", "#14225A", "#FFFFFF"),
    "Chicago Cubs": ("CHC", "#0E3386", "#FFFFFF"),
    "Cincinnati Reds": ("CIN", "#C6011F", "#FFFFFF"),
    "Milwaukee Brewers": ("MIL", "#12284B", "#FFC52F"),
    "Pittsburgh Pirates": ("PIT", "#FDB827", "#27251F"),
    "St. Louis Cardinals": ("STL", "#C41E3A", "#FFFFFF"),
    "Arizona Diamondbacks": ("ARI", "#A71930", "#FFFFFF"),
    "Colorado Rockies": ("COL", "#333366", "#FFFFFF"),
    "Los Angeles Dodgers": ("LAD", "#005A9C", "#FFFFFF"),
    "San Diego Padres": ("SD", "#2F241D", "#FFC425"),
    "San Francisco Giants": ("SF", "#FD5A1E", "#27251F"),
}


def _team_badge(team_name):
    info = TEAM_COLORS.get(team_name)
    if info:
        abbr, bg, fg = info
    else:
        words = team_name.split()
        abbr = (words[0][:1] + words[-1][:2]).upper() if len(words) > 1 else team_name[:3].upper()
        bg, fg = "#2a2d33", "#f3ede0"
    return f'<span class="badge" style="--bc:{bg};--bt:{fg};">{abbr}</span>'


def _tile(number_str, label):
    return f'<div class="tile"><div class="n">{number_str}</div><div class="l">{label}</div></div>'


def _track_record_html():
    """
    A collapsible 'how has this actually done' section, driven by
    backtest.compute_track_record() - every logged pick (see
    backtest.log_predictions) graded against the final score once resolved,
    bucketed by how confident the pick was (edge size vs. the market). The
    point: a model is only useful if its bigger disagreements with the
    market actually win more often, not just whichever teams it disagreed
    with today - this is what lets that get checked over time instead of
    taken on faith.
    """
    try:
        tr = backtest.compute_track_record()
    except Exception as e:
        return f'<div class="legend">Track record unavailable: {e}</div>'

    o = tr["overall"]
    n = tr["n"]

    def _rec_str(stats):
        w, l = stats["wins"], stats["losses"]
        if w + l == 0:
            return "—"
        pct = f" ({stats['win_pct']*100:.0f}%)" if stats["win_pct"] is not None else ""
        return f"{w}-{l}{pct}"

    tiles = _tile(_rec_str(o), "Overall")
    for t in tr["by_tier"]:
        tiles += _tile(_rec_str(t), t["tier"])

    if n == 0:
        summary = ('Model track record '
                    '<span class="muted" style="font-weight:400; text-transform:none; letter-spacing:normal;">'
                    '— no resolved picks yet</span>')
        note = """No resolved predictions logged yet. Each day you run this, today's picks get
        logged, and once those games finish, a re-run resolves them against the final score.
        Check back after a few days of daily runs to see a real record build up."""
    else:
        overall_pct = f"{o['win_pct']*100:.0f}%" if o["win_pct"] is not None else "-"
        summary = f"Model track record: <b>{o['wins']}-{o['losses']}</b> overall ({overall_pct}) across {n} resolved picks"
        note = """"Record" = how often the team the model favored over the market (see "Model likes" column)
        actually won, once that game is final. Tiers are bucketed by how big that edge was - the
        idea is to check whether bigger disagreements with the market are actually more reliable,
        not just louder. Early on these will be small samples; treat any tier with well under 20
        picks as not yet meaningful. Deeper probability calibration (not just pick record) is in
        <code>backtest.py</code>."""

    return f"""
    <details class="track">
      <summary>{summary}</summary>
      <div class="track-body">
        <div class="tiles">{tiles}</div>
        <div class="track-note">{note}</div>
      </div>
    </details>
    """


def _pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def _ml(x):
    """American moneyline for display, e.g. -132 or +112."""
    if x is None:
        return "-"
    return f"+{x}" if x > 0 else f"{x}"


def _edge_tier(g):
    """
    Bucket a game's edge magnitude into strong/moderate/light, or None if
    there's no usable edge (missing data, or the model is ~flat with the
    market). Drives both the card's left accent stripe and the "Model
    likes" chip styling, so the two always agree.
    """
    he, ae = g.get("home_edge"), g.get("away_edge")
    if he is None or ae is None or abs(he) < 0.005:
        return None
    val = he if he > 0 else ae
    pts = abs(val) * 100
    if pts >= 10:
        return "strong"
    if pts >= 5:
        return "moderate"
    return "light"


def _favored_edge_str(g):
    """
    Single-line version of edge: home_edge and away_edge are always exact
    mirror images of each other (one team's win prob minus market prob is
    the negative of the other's), so showing both as separate +/- numbers
    just doubles the same information and reads like two findings instead
    of one. This picks whichever team the model likes more than the market
    price does, and names them directly.
    """
    tier = _edge_tier(g)
    if tier is None:
        he, ae = g.get("home_edge"), g.get("away_edge")
        if he is None or ae is None:
            return "<span class='muted'>-</span>"
        return "<span class='muted'>~even with market</span>"
    he, ae = g["home_edge"], g["away_edge"]
    if he > 0:
        team, val = g["home_team"], he
    else:
        team, val = g["away_team"], ae
    short = team.split()[-1]
    pts = val * 100
    aria = f"Model favors the {short} by {abs(pts):.1f} points more than the market price — a {tier}-tier edge."
    return f"<span class=\"chip tier-{tier}\" tabindex=\"0\" aria-label=\"{aria}\">▲ {short} {'+' if pts >= 0 else ''}{pts:.1f} pts</span>"


def _run_diff_str(g):
    """Today's projected run differential (from the adjusted model), naming
    whichever team is projected to outscore the other."""
    diff = g.get("projected_run_diff")
    if diff is None:
        return "<span class='muted'>-</span>"
    if abs(diff) < 0.05:
        return "<span class='muted'>~even</span>"
    team = g["home_team"] if diff > 0 else g["away_team"]
    short = team.split()[-1]
    cls = "pos" if diff > 0 else "neg"
    return f"<span class='{cls}'>{short} +{abs(diff):.1f}</span>"


def _movement_str(g):
    """
    How much the market has actually moved: the opening price we first
    logged today for this game versus the current one, per side, plus the
    net point shift (home-probability terms) as a quick-scan summary.
    Requires at least two snapshots today (line_movement.py) - on the
    first run of the day there's nothing to compare against yet.
    """
    x = g.get("home_movement")
    if x is None:
        return "<span class='muted'>no history yet</span>"

    away_open, home_open = g.get("away_opening_ml"), g.get("home_opening_ml")
    away_now, home_now = g.get("away_market_ml"), g.get("home_market_ml")
    prices = ""
    if away_open is not None and home_open is not None:
        prices = (f"<span class=\"price-label tip\" tabindex=\"0\" "
                  f"aria-label=\"Each side's price the first time this tool logged odds today, versus right now.\">"
                  f"Opened → now<span class=\"bubble\" aria-hidden=\"true\">Each side's price the first time this "
                  f"tool logged odds today, versus right now.</span></span><br>"
                  f"{_ml(away_open)} → {_ml(away_now)}<br>{_ml(home_open)} → {_ml(home_now)}<br>")

    if abs(x) < 0.005:
        delta = "<span class='muted'>flat</span>"
    else:
        sign = "+" if x >= 0 else ""
        cls = "pos" if x > 0 else "neg"
        delta = f"<span class='{cls}'>{sign}{x*100:.1f} pts (home)</span>"

    return f"{prices}{delta}"


def _probbar(g):
    away_p, home_p = g.get("away_model_prob"), g.get("home_model_prob")
    if away_p is None or home_p is None:
        return ""
    return (f'<div class="probbar"><div class="seg-away" style="width:{away_p*100:.1f}%"></div>'
            f'<div class="seg-home" style="width:{home_p*100:.1f}%"></div></div>')


def _starter_str(starter):
    if not starter or not starter.get("name"):
        return "<span class='muted'>TBD</span>"
    fip_str = f"FIP {starter['fip']:.2f}" if starter.get("fip") is not None else "FIP n/a"
    bp_str = f"bullpen {starter['bullpen_era']:.2f}" if starter.get("bullpen_era") is not None else ""
    return f"{starter['name']} <span class='muted'>({fip_str}{', ' + bp_str if bp_str else ''})</span>"


def _rd(x):
    if x is None:
        return "-"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x}"


def _final_result_str(g):
    """
    For a game whose abstract_state is 'Final': names the winner and,
    when the game was gradeable (a market line existed when it was
    logged), says whether the model's pick was right. Games that never
    had a market line before they started (line pulled once betting
    closes, no odds ever fetched) are honestly labeled ungraded rather
    than silently omitted or scored as a miss.
    """
    hs, aws = g.get("home_score"), g.get("away_score")
    if hs is None or aws is None:
        return "<span class='muted'>Final — score unavailable</span>"

    he, ae = g.get("home_edge"), g.get("away_edge")
    if he is None or ae is None:
        grade = "<span class='muted'>no market line was posted before this game started — not a graded pick</span>"
    else:
        picked_home = he >= ae
        picked_team = (g["home_team"] if picked_home else g["away_team"]).split()[-1]
        correct = (picked_home and hs > aws) or (not picked_home and aws > hs)
        cls = "pos" if correct else "neg"
        mark = "correct" if correct else "incorrect"
        grade = f"<span class='{cls}'>model favored {picked_team} — {mark}</span>"

    return f"Final: {g['away_team'].split()[-1]} {aws} – {g['home_team'].split()[-1]} {hs} · {grade}"


def _final_card(g):
    return f"""
    <div class="finalcard">
      <div class="fteams">
        <span class="fteam">{_team_badge(g['away_team'])}{g['away_team']}</span>
        <span class="fteam"><span class="at">@</span>{_team_badge(g['home_team'])}{g['home_team']}</span>
      </div>
      <div class="fresult">{_final_result_str(g)}</div>
    </div>
    """


def _live_score(g, is_home):
    """Current score for an in-progress game, shown inline next to that
    team's name so it reads as one line per team rather than a lone
    ambiguous number. Only for 'Live' games - Preview games are always
    0-0 (meaningless) and Final games are rendered separately."""
    if g.get("abstract_state") != "Live":
        return ""
    score = g.get("home_score") if is_home else g.get("away_score")
    if score is None:
        return ""
    return f'<span class="live-score">{score}</span>'


def _row(g, is_top=False):
    books_note = f'{g["num_books"]} books' if g["num_books"] else ""
    park = f"{g.get('park_factor', 100)}" if g.get("park_factor") is not None else "-"
    writeup_html = ""
    if g.get("writeup"):
        writeup_html = f"""
        <details class="gamewriteup">
          <summary>Why this prediction?</summary>
          <div class="writeuptext">{g['writeup']}</div>
        </details>
        """

    tier = _edge_tier(g)
    game_class = f"game {tier}" if tier else "game"
    badge_html = '<span class="top-badge">Top edge today</span>' if is_top and tier else ""
    if g.get("abstract_state") == "Live":
        badge_html += '<span class="live-pill">● Live</span>'

    away_rec = g["away_record"]
    home_rec = g["home_record"]

    return f"""
    <div class="{game_class}">
      <div class="col matchup">
        {badge_html}
        <div class="team">{_team_badge(g['away_team'])}{g['away_team']}{_live_score(g, False)}<span class="rec">{away_rec.get('wins','-')}–{away_rec.get('losses','-')} · rd {_rd(g.get('away_run_diff'))}</span></div>
        <div class="team"><span class="at">@</span>{_team_badge(g['home_team'])}{g['home_team']}{_live_score(g, True)}<span class="rec">{home_rec.get('wins','-')}–{home_rec.get('losses','-')} · rd {_rd(g.get('home_run_diff'))}</span></div>
        <div class="pitchers">
          <div>{_starter_str(g.get('away_starter'))}</div>
          <div>{_starter_str(g.get('home_starter'))}</div>
        </div>
        <div class="parknote">{g.get('venue_name','')} · park factor {park}</div>
        {writeup_html}
      </div>

      <div class="col num">
        <span class="price-label tip" tabindex="0" aria-label="Real bookmaker price, averaged across every book tracked, vig included.">Book<span class="bubble" aria-hidden="true">Real bookmaker price, averaged across every book tracked, vig included.</span></span>
        {_ml(g.get('away_market_ml'))}<br>{_ml(g.get('home_market_ml'))}
      </div>

      <div class="col num">
        <span class="price-label tip" tabindex="0" aria-label="Model's fair price with no vig, converted from its win probability.">Model<span class="bubble" aria-hidden="true">Model's fair price with no vig, converted from its win probability.</span></span>
        {_ml(g.get('away_model_ml'))}<br>{_ml(g.get('home_model_ml'))}
        {_probbar(g)}
        <span class="winpct">{_pct(g.get('away_model_prob'))} / {_pct(g.get('home_model_prob'))}</span>
      </div>

      <div class="col num">
        <span class="mobile-label">Model likes</span>
        {_favored_edge_str(g)}
      </div>

      <div class="col num">
        <span class="mobile-label">Proj. run diff</span>
        {_run_diff_str(g)}
      </div>

      <div class="col num">
        <span class="mobile-label">Line move</span>
        {_movement_str(g)}
      </div>

      <div class="col num books"><span class="mobile-label">Books</span>{books_note}</div>
    </div>
    """


def _load_changelog():
    try:
        with open(CHANGELOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _changelog_html():
    entries = sorted(_load_changelog(), key=lambda e: e.get("date", ""), reverse=True)
    if not entries:
        return '<p class="an-empty">No changelog entries yet.</p>'
    rows = "".join(f"""
      <div class="chlog-entry">
        <div class="chlog-date">{e.get('date', '')}</div>
        <div class="chlog-body">
          <div class="chlog-summary">{e.get('summary', '')}</div>
          <div class="chlog-why"><span class="chlog-why-label">Why:</span> {e.get('why', '')}</div>
        </div>
      </div>
    """ for e in entries)
    return f'<div class="chlog">{rows}</div>'


def _patterns_html():
    try:
        notes = backtest.detect_patterns()
    except Exception:
        notes = []
    if not notes:
        return ""
    items = "".join(f"<li>{n}</li>" for n in notes)
    return f'<div class="patterns"><div class="an-subhead">Patterns worth watching</div><ul>{items}</ul></div>'


def _postmortems_html():
    try:
        posts = backtest.generate_postmortems()
    except Exception as e:
        return f'<p class="an-empty">Postmortems unavailable: {e}</p>'
    if not posts:
        return ('<p class="an-empty">No resolved, graded picks yet — check back once today\'s '
                'games are final and a later run has reconciled them.</p>')
    rows = "".join(f"""
      <div class="pm-row {'pm-correct' if p['correct'] else 'pm-incorrect'}">
        <div class="pm-head">
          <span class="pm-date">{p['date']}</span>
          <span class="pm-matchup">{p['matchup']}</span>
          <span class="pm-mark">{'correct' if p['correct'] else 'incorrect'}</span>
        </div>
        <div class="pm-pick">Picked <b>{p['picked_team']}</b>{f" ({p['edge_pts']} pt edge)" if p.get('edge_pts') is not None else ''}</div>
        <div class="pm-explain">{p['explanation']}</div>
      </div>
    """ for p in posts)
    return f'<div class="postmortems">{rows}</div>'


def _improvements_html():
    items = "".join(f"""
      <div class="idea">
        <div class="idea-what">{i['idea']}</div>
        <div class="idea-why"><span class="chlog-why-label">Why:</span> {i['why']}</div>
      </div>
    """ for i in backtest.FUTURE_ADJUSTMENTS)
    return f'<div class="ideas">{items}</div>'


def _analysis_tab_html():
    return f"""
    <div class="an-section">
      <div class="legend-title">What changed, and when</div>
      <p class="an-note">A running log of adjustments made to the model itself — use this to
      line up a shift in the track record with the change that might have caused it.</p>
      {_changelog_html()}
    </div>

    <div class="an-section">
      <div class="legend-title">Pick by pick: what happened, and why</div>
      <p class="an-note">Every graded pick once its game is final — correct or not, and for
      misses, a best-effort read on whether something specific pointed the wrong way or it
      was just normal variance (any team can beat any team on a given day).</p>
      {_patterns_html()}
      {_postmortems_html()}
    </div>

    <div class="an-section">
      <div class="legend-title">Ideas for improving pick accuracy</div>
      <p class="an-note">Not yet implemented — candidates worth trying once there's enough
      resolved history to tell whether they'd actually help.</p>
      {_improvements_html()}
    </div>
    """


def render(report, out_path=None):
    out_path = out_path or os.path.join(OUT_DIR, "dashboard.html")

    banner = ""
    if not report.get("odds_available"):
        banner = f"""
        <div class="banner">
          No odds data: {report.get('odds_error', 'unknown error')}
          <br>Model probabilities below are still valid; market/edge columns need a free key from
          <a href="https://the-odds-api.com/" target="_blank">the-odds-api.com</a> set in <code>config.json</code>
          or the <code>ODDS_API_KEY</code> environment variable.
        </div>
        """

    all_games = report["games"]
    finished = [g for g in all_games if g.get("abstract_state") == "Final"]
    games = [g for g in all_games if g.get("abstract_state") != "Final"]

    rows = "\n".join(_row(g, is_top=(i == 0)) for i, g in enumerate(games)) or \
        '<div class="game"><div class="col matchup">No games left today.</div></div>'

    finished_section = ""
    if finished:
        finished_section = f"""
        <div class="slate-head" style="margin-top: var(--sp-6);">
          <div class="slate-label">Completed today</div>
          <div class="slate-count">{len(finished)} game{'s' if len(finished) != 1 else ''}</div>
        </div>
        <div class="finalcards">
          {''.join(_final_card(g) for g in finished)}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MLB Edge Dashboard — {report['date']}</title>
<style>
  /* ============================================================
     "Ledger under the lights" — a box-score / scorecard aesthetic:
     solid black ground, chalk-ivory ink, brass foul-pole accent.
     Pine green / brick rust carry meaning (value found / fade),
     kept distinct from the brass accent so semantic color never
     competes with the interactive accent hue.
     ============================================================ */
  :root {{
    --bg: #000000;
    --panel: #17181b;
    --panel-2: #212226;
    --border: #34363b;
    --text: #f3ede0;
    --muted: #9a9ea3;
    --accent: #c99a3f;      --accent-rgb: 201,154,63;
    --pos: #5fae6c;         --pos-rgb: 95,174,108;
    --neg: #c15d49;         --neg-rgb: 193,93,73;
    --ring: #d9b567;

    --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Noto Serif", serif;
    --font-label: "Bahnschrift", "SF Compact Condensed", "Arial Narrow", "Helvetica Neue", Arial, sans-serif;
    --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    --font-data: "SF Mono", "Cascadia Code", Consolas, Menlo, "Roboto Mono", monospace;

    --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;
  }}
  :root[data-theme="light"] {{
    --bg: #f6f1e3;
    --panel: #ffffff;
    --panel-2: #efe6cf;
    --border: #ddd0ac;
    --text: #211c14;
    --muted: #6f6552;
    --accent: #8a6a1f;      --accent-rgb: 138,106,31;
    --pos: #2f6b3d;         --pos-rgb: 47,107,61;
    --neg: #92402c;         --neg-rgb: 146,64,44;
    --ring: #8a6a1f;
  }}
  @media (prefers-color-scheme: light) {{
    :root:not([data-theme="dark"]) {{
      --bg: #f6f1e3;
      --panel: #ffffff;
      --panel-2: #efe6cf;
      --border: #ddd0ac;
      --text: #211c14;
      --muted: #6f6552;
      --accent: #8a6a1f;      --accent-rgb: 138,106,31;
      --pos: #2f6b3d;         --pos-rgb: 47,107,61;
      --neg: #92402c;         --neg-rgb: 146,64,44;
      --ring: #8a6a1f;
    }}
  }}

  * {{ box-sizing: border-box; }}
  html, body {{ background: var(--bg); }}
  body {{
    margin: 0; padding: 48px 28px 64px; color: var(--text);
    font-family: var(--font-body); position: relative;
  }}

  .page {{ max-width: 1180px; margin: 0 auto; }}

  a:focus-visible, summary:focus-visible, details:focus-visible {{
    outline: 2px solid var(--ring); outline-offset: 3px; border-radius: 2px;
  }}

  /* ---------- masthead ---------- */
  .masthead {{ margin-bottom: 28px; }}
  .wordmark {{
    font-family: var(--font-display); font-size: 34px; font-weight: 600;
    letter-spacing: 0.01em; display: flex; align-items: baseline; gap: 10px;
    text-wrap: balance;
  }}
  .wordmark em {{ font-style: italic; font-weight: 400; color: var(--accent); }}
  .masthead-rule {{ height: 3px; margin: 10px 0 3px; background: var(--border); border-radius: 1px; }}
  .masthead-rule.thin {{ height: 1px; opacity: 0.6; }}
  .meta {{
    margin-top: 10px; font-family: var(--font-label); font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted);
  }}
  .meta .dot {{ margin: 0 8px; opacity: 0.5; }}

  .banner {{
    background: var(--panel-2); border: 1px solid rgba(var(--accent-rgb),0.4); color: var(--accent);
    padding: 12px 16px; border-radius: 8px; font-size: 13px; margin-bottom: 20px; line-height: 1.5;
  }}
  .banner a {{ color: var(--accent); }}
  .banner code {{ font-family: var(--font-data); }}

  /* ---------- tabs ---------- */
  .tab-input {{ position: absolute; opacity: 0; pointer-events: none; }}
  .tab-panel {{ display: none; }}
  #tab-today:checked ~ .panel-today {{ display: block; }}
  #tab-analysis:checked ~ .panel-analysis {{ display: block; }}
  .tabnav {{
    display: flex; gap: 4px; margin-bottom: 24px; border-bottom: 1px solid var(--border);
  }}
  .tab-label {{
    cursor: pointer; padding: 10px 18px; font-family: var(--font-label); font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
    border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 150ms ease;
  }}
  .tab-label:hover {{ color: var(--text); }}
  #tab-today:checked ~ .tabnav label[for="tab-today"],
  #tab-analysis:checked ~ .tabnav label[for="tab-analysis"] {{
    color: var(--text); border-bottom-color: var(--accent);
  }}
  .tab-input:focus-visible ~ .tabnav label {{ outline: 2px solid var(--ring); outline-offset: 2px; }}

  /* ---------- analysis tab ---------- */
  .an-section {{ margin-bottom: var(--sp-7); }}
  .an-note {{ font-size: 13px; line-height: 1.6; color: var(--muted); max-width: 70ch; margin: 6px 0 18px; }}
  .an-subhead {{
    font-family: var(--font-label); font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--accent); font-weight: 600; margin-bottom: 8px;
  }}
  .an-empty {{ color: var(--muted); font-size: 13px; }}

  .patterns {{
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px 16px; margin-bottom: 18px;
  }}
  .patterns ul {{ margin: 0; padding-left: 18px; }}
  .patterns li {{ font-size: 13px; line-height: 1.6; color: var(--text); margin-bottom: 6px; }}

  .chlog-entry {{
    display: flex; gap: 18px; padding: 14px 0; border-top: 1px solid var(--border);
  }}
  .chlog-entry:first-child {{ border-top: none; }}
  .chlog-date {{
    flex: none; width: 90px; font-family: var(--font-data); font-size: 12px; color: var(--muted);
    padding-top: 2px;
  }}
  .chlog-summary {{ font-size: 13.5px; line-height: 1.6; color: var(--text); }}
  .chlog-why {{ font-size: 12.5px; line-height: 1.6; color: var(--muted); margin-top: 5px; }}
  .chlog-why-label {{ color: var(--accent); font-weight: 600; }}

  .pm-row {{
    background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--border);
    border-radius: 6px; padding: 12px 16px; margin-bottom: 10px;
  }}
  .pm-row.pm-correct {{ border-left-color: rgba(var(--pos-rgb), 0.7); }}
  .pm-row.pm-incorrect {{ border-left-color: rgba(var(--neg-rgb), 0.7); }}
  .pm-head {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
  .pm-date {{ font-family: var(--font-data); font-size: 11.5px; color: var(--muted); }}
  .pm-matchup {{ font-family: var(--font-display); font-size: 14px; color: var(--text); flex: 1 1 auto; }}
  .pm-mark {{
    font-family: var(--font-label); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em;
    font-weight: 700;
  }}
  .pm-row.pm-correct .pm-mark {{ color: var(--pos); }}
  .pm-row.pm-incorrect .pm-mark {{ color: var(--neg); }}
  .pm-pick {{ font-size: 12.5px; color: var(--muted); margin-top: 6px; }}
  .pm-explain {{ font-size: 13px; line-height: 1.6; color: var(--text); margin-top: 6px; max-width: 76ch; }}

  .idea {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 12px 16px; margin-bottom: 10px;
  }}
  .idea-what {{ font-size: 13.5px; color: var(--text); font-weight: 600; }}
  .idea-why {{ font-size: 12.5px; line-height: 1.6; color: var(--muted); margin-top: 5px; }}

  /* ---------- track record ---------- */
  .track {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    margin-bottom: 24px; overflow: hidden;
  }}
  .track summary {{
    cursor: pointer; list-style: none; padding: 14px 18px;
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    font-family: var(--font-label); font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--text); font-weight: 600;
  }}
  .track summary::-webkit-details-marker {{ display: none; }}
  .track summary::after {{
    content: "＋"; color: var(--accent); font-family: var(--font-body); font-size: 15px;
    transition: transform 160ms ease;
  }}
  .track[open] summary::after {{ content: "－"; }}
  .track-body {{ padding: 4px 18px 18px; border-top: 1px solid var(--border); }}
  .tiles {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1px;
    background: var(--border); border-radius: 6px; overflow: hidden; margin-top: 14px;
  }}
  .tile {{ background: var(--panel-2); padding: 14px 16px; }}
  .tile .n {{ font-family: var(--font-data); font-size: 20px; font-variant-numeric: tabular-nums; color: var(--muted); }}
  .tile .l {{ font-family: var(--font-label); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin-top: 4px; }}
  .track-note {{ margin-top: 14px; font-size: 13px; line-height: 1.55; color: var(--muted); max-width: 60ch; }}
  .track-note code {{ font-family: var(--font-data); }}

  /* ---------- slate ---------- */
  .slate-head {{
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }}
  .slate-label {{ font-family: var(--font-display); font-style: italic; font-size: 17px; color: var(--text); }}
  .slate-count {{ font-family: var(--font-label); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}

  .games-scroll {{ overflow-x: auto; }}
  .games {{ min-width: 900px; display: flex; flex-direction: column; gap: 10px; padding: 6px 2px 4px; }}

  .game {{
    display: grid;
    grid-template-columns: 2.1fr 0.85fr 1.05fr 1.15fr 0.95fr 0.95fr 0.55fr;
    align-items: start; gap: 0; position: relative;
    background: var(--panel); border: 1px solid var(--border); border-left: 4px solid var(--edge-color, var(--border));
    border-radius: 6px; padding: var(--sp-4) var(--sp-5);
    transition: background 150ms ease, border-color 150ms ease, transform 150ms ease, box-shadow 150ms ease;
  }}
  .game:hover {{ background: var(--panel-2); transform: translateY(-2px); box-shadow: 0 10px 28px rgba(0,0,0,0.22); }}
  @media (prefers-reduced-motion: reduce) {{ .game {{ transition: none; }} .game:hover {{ transform: none; }} }}

  .game.strong {{ --edge-color: rgba(var(--pos-rgb), 0.9); }}
  .game.moderate {{ --edge-color: rgba(var(--pos-rgb), 0.55); }}
  .game.light {{ --edge-color: rgba(var(--pos-rgb), 0.3); }}

  .top-badge {{
    display: inline-block; margin-bottom: var(--sp-2);
    background: var(--accent); color: #000; font-family: var(--font-label);
    font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    padding: 3px 9px; border-radius: 3px;
  }}

  .live-pill {{
    display: inline-flex; align-items: center; gap: 5px; margin-left: var(--sp-2);
    color: var(--neg); font-family: var(--font-label); font-size: 9.5px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em;
  }}
  .live-score {{
    font-family: var(--font-data); font-size: 13px; font-weight: 700; color: var(--text);
    background: rgba(var(--neg-rgb), 0.14); border: 1px solid rgba(var(--neg-rgb), 0.35);
    padding: 1px 8px; border-radius: 4px; font-variant-numeric: tabular-nums;
  }}

  .probbar {{
    display: flex; height: 5px; border-radius: 3px; overflow: hidden;
    margin-top: 5px; width: 100%; max-width: 150px; background: var(--border);
  }}
  .probbar .seg-away {{ background: var(--accent); }}
  .probbar .seg-home {{ background: var(--muted); opacity: 0.55; }}

  /* ---------- completed games ---------- */
  .finalcards {{ display: flex; flex-direction: column; gap: 8px; }}
  .finalcard {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 12px 16px; opacity: 0.82;
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px;
  }}
  .fteams {{ display: flex; flex-direction: column; gap: 3px; }}
  .fteam {{
    display: flex; align-items: center; gap: 8px;
    font-family: var(--font-display); font-size: 14px; color: var(--text);
  }}
  .fteam .at {{ color: var(--muted); font-style: italic; }}
  .fresult {{
    font-family: var(--font-data); font-size: 12px; color: var(--muted);
    text-align: right; flex: 1 1 auto; min-width: 220px;
  }}

  .col {{ padding-right: 14px; }}
  .col.num {{ text-align: right; padding-right: 0; }}

  .matchup .team {{
    font-family: var(--font-display); font-size: 16px; font-weight: 600; line-height: 1.5;
    display: flex; align-items: center; gap: 9px;
  }}
  .matchup .at {{ color: var(--muted); font-style: italic; font-weight: 400; }}
  .badge {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; flex: none; border-radius: 50%;
    background: var(--bc); color: var(--bt);
    font-family: var(--font-label); font-size: 8.5px; font-weight: 700; letter-spacing: 0.02em;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.15), 0 1px 3px rgba(0,0,0,0.4);
  }}
  .matchup .rec {{
    font-family: var(--font-data); font-size: 11.5px; color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .matchup .pitchers {{ margin-top: 8px; font-family: var(--font-data); font-size: 12px; color: var(--text); line-height: 1.7; }}
  .matchup .parknote {{ margin-top: 6px; font-size: 11.5px; color: var(--muted); font-style: italic; }}

  .gamewriteup {{ margin-top: 9px; }}
  .gamewriteup summary {{
    cursor: pointer; list-style: none; color: var(--accent); font-family: var(--font-label);
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
  }}
  .gamewriteup summary::-webkit-details-marker {{ display: none; }}
  .gamewriteup summary::before {{ content: "▸ "; }}
  .gamewriteup[open] summary::before {{ content: "▾ "; }}
  .writeuptext {{ margin-top: 8px; font-size: 12.5px; line-height: 1.65; color: var(--muted); max-width: 46ch; }}

  .num {{ font-family: var(--font-data); font-size: 13.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .price-label {{
    display: block; width: fit-content; margin-left: auto; font-family: var(--font-label); font-size: 9.5px;
    text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 3px;
  }}
  .winpct {{ display: block; margin-top: 3px; font-size: 10.5px; color: var(--muted); }}

  .chip {{
    display: inline-flex; align-items: baseline; gap: 4px; font-family: var(--font-data);
    font-size: 12.5px; font-weight: 600; padding: 4px 9px; border-radius: 999px;
    background: rgba(var(--pos-rgb), 0.12); border: 1px solid rgba(var(--pos-rgb), 0.32); color: var(--pos);
    white-space: nowrap;
  }}
  .chip.tier-strong {{ background: rgba(var(--pos-rgb), 0.18); border-color: rgba(var(--pos-rgb), 0.55); }}
  .chip.tier-moderate {{ background: rgba(var(--pos-rgb), 0.1); border-color: rgba(var(--pos-rgb), 0.28); }}
  .chip.tier-light {{ background: rgba(var(--pos-rgb), 0.07); border-color: rgba(var(--pos-rgb), 0.2); }}

  .pos {{ color: var(--pos); font-weight: 600; }}
  .neg {{ color: var(--neg); font-weight: 600; }}
  .muted {{ color: var(--muted); }}
  .books {{ font-family: var(--font-data); font-size: 12px; color: var(--muted); }}

  /* ---------- tooltips ---------- */
  .tip {{ position: relative; border-bottom: 1px dotted rgba(var(--accent-rgb), 0.55); cursor: help; }}
  .tip:focus-visible {{ outline: none; border-bottom-color: var(--ring); }}
  .tip .bubble {{
    position: absolute; bottom: calc(100% + 9px); left: 50%; transform: translateX(-50%) translateY(4px);
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px;
    padding: 9px 11px; font-size: 11.5px; line-height: 1.5; font-family: var(--font-body); font-weight: 400;
    text-transform: none; letter-spacing: normal; white-space: normal; width: max-content; max-width: 230px;
    box-shadow: 0 10px 28px rgba(0,0,0,0.35);
    opacity: 0; pointer-events: none; transition: opacity 120ms ease, transform 120ms ease; z-index: 30;
  }}
  .tip .bubble::after {{
    content: ""; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    border: 5px solid transparent; border-top-color: var(--panel-2);
  }}
  .tip:hover .bubble, .tip:focus-visible .bubble {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
  @media (prefers-reduced-motion: reduce) {{ .tip .bubble {{ transition: none; }} }}

  .mobile-label {{ display: none; }}

  /* ---------- legend ---------- */
  .legend {{ margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--border); }}
  .legend-title {{ font-family: var(--font-display); font-style: italic; font-size: 15px; margin-bottom: 12px; color: var(--text); }}
  dl.legend-list {{ display: grid; grid-template-columns: 180px 1fr; row-gap: 10px; column-gap: 18px; margin: 0; }}
  dl.legend-list dt {{
    font-family: var(--font-label); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--accent); font-weight: 600; padding-top: 1px;
  }}
  dl.legend-list dd {{ margin: 0; font-size: 13px; line-height: 1.6; color: var(--muted); }}
  .disclaimer {{ margin: 16px 0 0; font-size: 12px; line-height: 1.6; color: var(--muted); font-style: italic; max-width: 78ch; }}

  @media (max-width: 780px) {{
    .games-scroll {{ overflow-x: visible; }}
    .games {{ min-width: 0; }}
    .game {{ grid-template-columns: 1fr 1fr; row-gap: var(--sp-4); column-gap: var(--sp-3); padding: var(--sp-4); }}
    .matchup {{ grid-column: 1 / -1; }}
    .col.num {{ text-align: left; }}
    .price-label {{ margin-left: 0; }}
    .mobile-label {{
      display: block; font-family: var(--font-label); font-size: 9.5px; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--muted); margin-bottom: 3px;
    }}
  }}

  @media (max-width: 640px) {{
    body {{ padding: 32px 16px 48px; }}
    .wordmark {{ font-size: 27px; }}
    .game {{ grid-template-columns: 1fr; }}
    dl.legend-list {{ grid-template-columns: 1fr; row-gap: 4px; }}
    dl.legend-list dd {{ margin-bottom: 8px; }}
  }}
</style>
</head>
<body>
  <div class="page">

    <div class="masthead">
      <div class="wordmark">MLB <em>Edge</em></div>
      <div class="masthead-rule"></div>
      <div class="masthead-rule thin"></div>
      <div class="meta">{report['date']} <span class="dot">·</span> generated {report['generated_at']} <span class="dot">·</span> sorted by edge size</div>
    </div>

    <input type="radio" name="tabs" id="tab-today" class="tab-input" checked>
    <input type="radio" name="tabs" id="tab-analysis" class="tab-input">
    <div class="tabnav">
      <label for="tab-today" class="tab-label">Today's Slate</label>
      <label for="tab-analysis" class="tab-label">Analysis</label>
    </div>

    <div class="tab-panel panel-today">

      {_track_record_html()}
      {banner}

      <div class="slate-head">
        <div class="slate-label">Today's slate</div>
        <div class="slate-count">{len(games)} game{'s' if len(games) != 1 else ''}</div>
      </div>

      <div class="games-scroll">
        <div class="games">
          {rows}
        </div>
      </div>

      {finished_section}

      <div class="legend">
        <div class="legend-title">How to read this</div>
        <dl class="legend-list">
          <dt>Sportsbook odds</dt>
          <dd>The actual moneyline you'd see at a book — each side's price averaged across every bookmaker tracked, vig included. A real, bettable price, not a theoretical one.</dd>
          <dt>Model odds</dt>
          <dd>The model's win probability for this specific game (season offense blended with today's starter FIP + bullpen ERA, park-adjusted, Pythagorean expectation + home field) converted to the same +150/−130 format, with no vig. Win% shown underneath for reference.</dd>
          <dt>Model likes</dt>
          <dd>Whichever team's model odds are more favorable than the sportsbook's price, and by how many points of win probability — the one number that matters if you're scanning for value.</dd>
          <dt>Proj. run diff</dt>
          <dd>Today's game-specific projected run differential — not season run differential (see each team's record above for that) — given today's park and pitching matchups.</dd>
          <dt>Line move</dt>
          <dd>Each side's price the first time this tool logged odds today ("opened") versus right now, plus the net shift in home-team win probability. Needs at least two runs today to show anything - a self-collected proxy, not a paid "sharp money" feed.</dd>
        </dl>
        <p class="disclaimer">This is a probability/edge estimate for research purposes, not a guarantee — treat it as one input, not an answer. Starting pitcher FIP is season-to-date, not adjusted for the specific matchup or recent form.</p>
      </div>

    </div>

    <div class="tab-panel panel-analysis">
      {_analysis_tab_html()}
    </div>

  </div>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    report_path = os.path.join(OUT_DIR, "report.json")
    with open(report_path) as f:
        report = json.load(f)
    path = render(report)
    print(f"Wrote {path}")
