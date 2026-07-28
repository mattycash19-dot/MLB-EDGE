"""
Park run factors: a static, hand-maintained reference table, not a live API
pull.

Why static: park factors are conventionally computed as multi-year regressed
averages (Fangraphs typically blends 3-5 years of data) precisely because a
single season of home/road run data is too noisy to trust on its own -
recomputing this "live" from this season's games alone would actually be
LESS reliable than a well-established static table, not more. Refresh this
table periodically (once a year is plenty) from a public source such as
Fangraphs' park factors page (https://www.fangraphs.com/guts.aspx?type=pf).

Values: 100 = league-average run environment. 112 = park inflates run
scoring ~12% versus average; 92 = suppresses it ~8%. These are directional
estimates based on each park's well-known, publicly-reported run-scoring
reputation (Coors Field plays as an extreme hitter's park, Oracle Park and
loanDepot park as pitcher's parks, etc.) - not scraped from a live source,
so treat as approximate. Venue IDs below were pulled directly from
/api/v1/teams on 2026-07-27 and are correct as of that date; teams
occasionally rename/relocate stadiums (e.g. Astros' park was "Daikin Park"
as of this pull, previously "Minute Maid Park") so re-verify if a lookup
seems to be missing.
"""

# venue_id (MLB Stats API, confirmed via /api/v1/teams) -> (team, run factor)
PARK_RUN_FACTORS = {
    2529: ("Athletics", 100),               # Sutter Health Park (temp home)
    31:   ("Pirates", 95),                  # PNC Park
    2680: ("Padres", 96),                   # Petco Park
    680:  ("Mariners", 93),                 # T-Mobile Park
    2395: ("Giants", 90),                   # Oracle Park
    2889: ("Cardinals", 97),                # Busch Stadium
    12:   ("Rays", 97),                     # Tropicana Field
    5325: ("Rangers", 104),                 # Globe Life Field
    14:   ("Blue Jays", 100),               # Rogers Centre
    3312: ("Twins", 97),                    # Target Field
    2681: ("Phillies", 102),                # Citizens Bank Park
    4705: ("Braves", 100),                  # Truist Park
    4:    ("White Sox", 99),                # Rate Field
    4169: ("Marlins", 94),                  # loanDepot park
    3313: ("Yankees", 104),                 # Yankee Stadium
    32:   ("Brewers", 103),                 # American Family Field
    1:    ("Angels", 97),                   # Angel Stadium
    15:   ("Diamondbacks", 103),            # Chase Field (roof closed favors offense)
    2:    ("Orioles", 97),                  # Oriole Park at Camden Yards
    3:    ("Red Sox", 104),                 # Fenway Park
    17:   ("Cubs", 101),                    # Wrigley Field (wind-dependent, high variance)
    2602: ("Reds", 106),                    # Great American Ball Park
    5:    ("Guardians", 96),                # Progressive Field
    19:   ("Rockies", 114),                 # Coors Field - famously extreme, altitude
    2394: ("Tigers", 100),                  # Comerica Park
    2392: ("Astros", 102),                  # Daikin Park (was Minute Maid Park)
    7:    ("Royals", 97),                   # Kauffman Stadium
    22:   ("Dodgers", 97),                  # UNIQLO Field at Dodger Stadium
    3309: ("Nationals", 99),                # Nationals Park
    3289: ("Mets", 93),                     # Citi Field
}

LEAGUE_AVERAGE = 100  # fallback if a venue id isn't in the table above


def get_park_factor(venue_id):
    entry = PARK_RUN_FACTORS.get(venue_id)
    return entry[1] if entry else LEAGUE_AVERAGE
