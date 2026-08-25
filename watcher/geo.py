"""Is this posting in the United States?

Career feeds write locations every possible way: "New York, NY, United States",
"Charlotte, NC", "LONDON, United Kingdom", "2 Locations", or nothing at all.

Order matters. US evidence is checked first, because plenty of US cities share a
name with a foreign one -- Birmingham AL, Manchester NH, Bristol CT, Athens GA,
Dublin OH. Checking foreign names first would throw those away.

Two-letter state codes are only honoured in a "City, ST" shape and only in
upper case, because IN, OR, DE, OK, HI and ME are all ordinary English words.
"""
import re

STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR",
}

STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "puerto rico",
}

# Unambiguous US metros, for feeds that give a bare city.
US_CITIES = {
    "new york city", "nyc", "san francisco", "los angeles", "chicago",
    "boston", "philadelphia", "washington dc", "atlanta", "dallas", "houston",
    "austin", "seattle", "denver", "phoenix", "miami", "minneapolis",
    "charlotte", "detroit", "san jose", "san diego", "st. louis", "st louis",
    "pittsburgh", "cleveland", "cincinnati", "baltimore", "milwaukee",
    "kansas city", "salt lake city", "las vegas", "orlando", "tampa",
    "nashville", "indianapolis", "columbus", "sacramento", "portland oregon",
    "menlo park", "palo alto", "mountain view", "sunnyvale", "santa clara",
    "cupertino", "redmond", "bentonville", "purchase ny", "jersey city",
    "stamford", "greenwich connecticut", "wilmington delaware", "hoboken",
}

US_MARKERS = (
    "united states", "u.s.a", "u.s.", "usa", " us)", "(us", "us -", "- us",
    "america",
)

# Checked only when nothing above says "US".
FOREIGN = {
    "united kingdom", "england", "scotland", "wales", "northern ireland",
    "london", "edinburgh", "glasgow", "cardiff", "belfast", "bournemouth",
    "dorset", "leeds", "reading uk", "canary wharf",
    "ireland", "dublin, ireland", "cork",
    "germany", "frankfurt", "munich", "münchen", "berlin", "hamburg",
    "düsseldorf", "dusseldorf", "stuttgart", "cologne",
    "france", "paris", "lyon", "toulouse", "spain", "madrid", "barcelona",
    "iberia", "portugal", "lisbon", "lisboa", "porto",
    "italy", "italia", "milan", "milano", "rome", "roma", "turin",
    "netherlands", "amsterdam", "rotterdam", "eindhoven", "utrecht",
    "belgium", "brussels", "antwerp", "luxembourg",
    "switzerland", "zurich", "zürich", "geneva", "basel", "lausanne",
    "austria", "vienna", "wien", "sweden", "stockholm", "gothenburg",
    "denmark", "copenhagen", "norway", "oslo", "finland", "helsinki",
    "poland", "warsaw", "warszawa", "krakow", "kraków", "wroclaw", "gdansk",
    "czech", "prague", "hungary", "budapest", "romania", "bucharest",
    "bulgaria", "sofia", "greece", "athens, greece", "cyprus", "nicosia",
    "malta", "croatia", "serbia", "slovakia", "slovenia", "estonia",
    "latvia", "lithuania", "ukraine", "russia", "moscow",
    "turkey", "istanbul", "israel", "tel aviv", "jaffa",
    "united arab emirates", "uae", "dubai", "abu dhabi", "saudi", "riyadh",
    "jeddah", "qatar", "doha", "kuwait", "bahrain", "egypt", "cairo",
    "south africa", "johannesburg", "cape town", "nigeria", "lagos",
    "kenya", "nairobi", "morocco", "casablanca", "kazakhstan", "almaty",
    "india", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad",
    "chennai", "gurgaon", "gurugram", "noida", "kolkata", "new delhi",
    "china", "beijing", "shanghai", "shenzhen", "guangzhou", "hong kong",
    "taiwan", "taipei", "japan", "tokyo", "osaka", "korea", "seoul",
    "singapore", "malaysia", "kuala lumpur", "penang", "indonesia",
    "jakarta", "thailand", "bangkok", "vietnam", "hanoi", "philippines",
    "manila", "australia", "sydney", "melbourne", "brisbane", "perth",
    "new zealand", "auckland", "wellington",
    "canada", "toronto", "vancouver", "montreal", "montréal", "calgary",
    "ottawa", "mississauga", "waterloo, on",
    "mexico", "guadalajara", "monterrey", "brazil", "brasil", "sao paulo",
    "são paulo", "rio de janeiro", "argentina", "buenos aires",
    "chile", "santiago", "colombia", "bogota", "bogotá", "peru", "lima",
    "costa rica", "san jose, costa rica", "panama", "uruguay", "montevideo",
    "cayman", "bermuda", "jersey, channel", "guernsey",
}

_STATE_CODE_RE = re.compile(r",\s*([A-Z]{2})(?:\s|,|$|\s*[-/])")
_WORD = re.compile(r"[a-z]+")


def _has_phrase(low, phrases):
    for phrase in phrases:
        if phrase in low:
            return phrase
    return None


def _verdict(hay_low, hay_raw):
    """Decide from one piece of text. None means 'no evidence either way'."""
    if hay_low:
        # 1. Explicit country.
        if _has_phrase(hay_low, US_MARKERS):
            return True
    if hay_raw:
        # 2a. A "City, ST" state code.
        for code in _STATE_CODE_RE.findall(hay_raw):
            if code in STATE_CODES:
                return True
    if hay_low:
        # 2b. A spelled-out state.
        for name in STATE_NAMES:
            if re.search(r"\b%s\b" % re.escape(name), hay_low):
                return True
        # 3. Explicit foreign marker -- before bare city names, so that
        #    "San Jose, Costa Rica" doesn't read as San Jose, California.
        if _has_phrase(hay_low, FOREIGN):
            return False
        # 4. An unambiguous US metro on its own.
        if _has_phrase(hay_low, US_CITIES):
            return True
    return None


def is_us(location, title=""):
    """True (US), False (definitely not US), or None (can't tell).

    The location field decides whenever it says anything at all. The title is
    only consulted when the location is missing or useless -- otherwise a role
    called "(US Tax) Internship" sitting in Singapore reads as American.
    """
    text = " ".join(str(location or "").split())
    low = text.lower()

    if low in ("multiple locations", "various", "remote", "2 locations"):
        text, low = "", ""

    if low:
        verdict = _verdict(low, text)
        if verdict is not None:
            return verdict
        # A location we couldn't place is still a location; don't guess from
        # the title, which is far more likely to mislead.
        return None

    title_text = str(title or "")
    return _verdict(title_text.lower(), title_text)


def passes(location, title, us_only, keep_unknown=True):
    """Apply the US gate. `keep_unknown` decides undecidable cases."""
    if not us_only:
        return True
    verdict = is_us(location, title)
    if verdict is None:
        return keep_unknown
    return verdict
