"""
Probability / edge math:
- Pythagorean expectation: converts a team's runs scored/allowed into an
  expected win percentage (Bill James formula, using the modern ~1.83 exponent).
- Log5: combines two teams' win percentages into a head-to-head win probability.
- Home field advantage: simple additive adjustment (MLB home teams win ~53-54%
  of the time historically, so ~0.03-0.04 above a neutral-field expectation).
- Moneyline -> implied probability, with vig removal (devigging) so the
  "market probability" reflects the true consensus, not the bookmaker's margin.
"""

PYTHAG_EXPONENT = 1.83
HOME_FIELD_BOOST = 0.04  # additive; MLB home win rate is historically ~53-54%


def pythagorean_win_pct(runs_scored, runs_allowed, exponent=PYTHAG_EXPONENT):
    """Expected win percentage from season run totals."""
    if runs_scored <= 0 and runs_allowed <= 0:
        return 0.5
    rs_e = runs_scored ** exponent
    ra_e = runs_allowed ** exponent
    if rs_e + ra_e == 0:
        return 0.5
    return rs_e / (rs_e + ra_e)


def log5(pct_a, pct_b):
    """Probability team A beats team B on a neutral field, given each team's
    season win percentage (Bill James' log5 method)."""
    # clip to avoid divide-by-zero at the extremes
    pct_a = min(max(pct_a, 0.001), 0.999)
    pct_b = min(max(pct_b, 0.001), 0.999)
    num = pct_a - pct_a * pct_b
    den = pct_a + pct_b - 2 * pct_a * pct_b
    if den == 0:
        return 0.5
    return num / den


def model_win_probability(home_stats, away_stats, home_boost=HOME_FIELD_BOOST):
    """
    Full model probability for the home team winning:
    1. Pythagorean win% for each team from runs scored/allowed.
    2. Log5 to get a neutral-field head-to-head probability.
    3. Add home field advantage.
    Returns (home_win_prob, away_win_prob).
    """
    home_pct = pythagorean_win_pct(home_stats["runs_scored"], home_stats["runs_allowed"])
    away_pct = pythagorean_win_pct(away_stats["runs_scored"], away_stats["runs_allowed"])
    neutral_home_prob = log5(home_pct, away_pct)
    home_prob = min(max(neutral_home_prob + home_boost, 0.01), 0.99)
    return home_prob, 1 - home_prob


def adjusted_win_probability(home_offense_rpg, away_offense_rpg,
                              home_pitching_ra9, away_pitching_ra9,
                              park_factor=100, home_boost=HOME_FIELD_BOOST):
    """
    Upgraded model: instead of season-aggregate Pythagorean expectation,
    projects each team's expected runs FOR THIS SPECIFIC GAME by blending
    their own season offense rate with the specific opposing pitching
    they're facing today (starter FIP blended with bullpen ERA - see
    pitching.py), then park-adjusts both sides, then applies Pythagorean
    expectation directly to the two projected run totals (valid: Bill
    James' formula works on any pair of run totals, not just season sums -
    using it here just means "in a game with these projected run levels,
    who wins more often").

    home_offense_rpg / away_offense_rpg: season runs scored per game.
    home_pitching_ra9 / away_pitching_ra9: today's starter-adjusted runs
        allowed per 9 for each team's pitching staff (from
        pitching.starter_adjusted_runs_allowed_per9).
    park_factor: today's venue's run factor (100 = neutral, see park_factors.py).

    Returns (home_win_prob, away_win_prob, home_projected_runs, away_projected_runs).
    """
    home_proj = (home_offense_rpg + away_pitching_ra9) / 2 * (park_factor / 100)
    away_proj = (away_offense_rpg + home_pitching_ra9) / 2 * (park_factor / 100)

    neutral_home_prob = pythagorean_win_pct(home_proj, away_proj)
    home_prob = min(max(neutral_home_prob + home_boost, 0.01), 0.99)
    return home_prob, 1 - home_prob, home_proj, away_proj


def moneyline_to_implied_prob(moneyline):
    """Raw implied probability from an American moneyline (includes vig)."""
    if moneyline > 0:
        return 100 / (moneyline + 100)
    else:
        return -moneyline / (-moneyline + 100)


def devig_two_way(prob_a, prob_b):
    """Remove the vig by normalizing two implied probabilities to sum to 1."""
    total = prob_a + prob_b
    if total == 0:
        return 0.5, 0.5
    return prob_a / total, prob_b / total


def moneyline_to_decimal(moneyline):
    if moneyline > 0:
        return moneyline / 100 + 1
    else:
        return 100 / -moneyline + 1


def decimal_to_moneyline(decimal_odds):
    """Inverse of moneyline_to_decimal - decimal odds back to American format."""
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    else:
        return round(-100 / (decimal_odds - 1))


def probability_to_moneyline(prob):
    """
    A win probability expressed as a 'fair' (no-vig) American moneyline -
    i.e. what the odds would be if a probability were priced with zero
    bookmaker margin. Used to show the model's probability in the same
    +150/-130 format as a real sportsbook line, so it's directly
    comparable to what the book is actually offering.
    """
    prob = min(max(prob, 0.001), 0.999)
    if prob >= 0.5:
        return round(-100 * prob / (1 - prob))
    else:
        return round(100 * (1 - prob) / prob)


def expected_value_pct(model_prob, moneyline):
    """Expected value per $1 staked, using the model's probability against a
    given moneyline. Positive = the bet is +EV according to the model."""
    decimal_odds = moneyline_to_decimal(moneyline)
    return model_prob * decimal_odds - 1


def edge(model_prob, market_prob):
    """Difference between the model's win probability and the (devigged)
    market-implied probability, in percentage points."""
    return model_prob - market_prob
