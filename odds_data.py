"""
Fetches MLB moneyline odds from The Odds API (https://the-odds-api.com/).
Requires a free API key - sign up at the-odds-api.com and either:
  - set the ODDS_API_KEY environment variable, or
  - put it in config.json as {"odds_api_key": "..."}

Free tier covers MLB h2h (moneyline) markets - plenty for a once-a-day pull.
"""
import json
import os
import urllib.request
import urllib.parse

API_BASE = "https://api.the-odds-api.com/v4"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_key_from_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            return cfg.get("odds_api_key") or None
    return None


def get_api_key(api_key=None):
    return api_key or os.environ.get("ODDS_API_KEY") or _load_key_from_config()


class NoApiKeyError(RuntimeError):
    pass


def get_mlb_odds(api_key=None, regions="us", markets="h2h"):
    """
    Returns a list of events, each with bookmaker moneylines for home/away.
    Raises NoApiKeyError if no key is configured anywhere.
    """
    key = get_api_key(api_key)
    if not key:
        raise NoApiKeyError(
            "No Odds API key configured. Get a free key at https://the-odds-api.com/ "
            "then set it via the ODDS_API_KEY environment variable or in config.json."
        )
    params = urllib.parse.urlencode({
        "apiKey": key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
    })
    url = f"{API_BASE}/sports/baseball_mlb/odds/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "mlb-edge-calculator/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def consensus_moneylines(event):
    """
    Given one event from get_mlb_odds(), average the devigged implied
    probability for home/away across all bookmakers listed, returning
    (home_prob, away_prob, num_books_used).
    """
    from model import moneyline_to_implied_prob, devig_two_way

    home_name = event.get("home_team")
    away_name = event.get("away_team")
    home_probs, away_probs = [], []

    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if home_name not in outcomes or away_name not in outcomes:
                continue
            raw_home = moneyline_to_implied_prob(outcomes[home_name])
            raw_away = moneyline_to_implied_prob(outcomes[away_name])
            home_p, away_p = devig_two_way(raw_home, raw_away)
            home_probs.append(home_p)
            away_probs.append(away_p)

    if not home_probs:
        return None, None, 0
    return sum(home_probs) / len(home_probs), sum(away_probs) / len(away_probs), len(home_probs)


def consensus_market_moneylines(event):
    """
    Averages each side's price across bookmakers (in decimal-odds space,
    since American odds aren't linear and shouldn't be averaged directly)
    and converts back to American format. This is "what the sportsbooks
    say" - the actual vigged market price - as opposed to
    consensus_moneylines() above, which removes the vig to get a fair
    probability for edge math. Returns (home_ml, away_ml, num_books_used).
    """
    from model import moneyline_to_decimal, decimal_to_moneyline

    home_name = event.get("home_team")
    away_name = event.get("away_team")
    home_decimals, away_decimals = [], []

    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if home_name not in outcomes or away_name not in outcomes:
                continue
            home_decimals.append(moneyline_to_decimal(outcomes[home_name]))
            away_decimals.append(moneyline_to_decimal(outcomes[away_name]))

    if not home_decimals:
        return None, None, 0
    avg_home_dec = sum(home_decimals) / len(home_decimals)
    avg_away_dec = sum(away_decimals) / len(away_decimals)
    return decimal_to_moneyline(avg_home_dec), decimal_to_moneyline(avg_away_dec), len(home_decimals)
