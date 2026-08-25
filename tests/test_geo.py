"""US location gate. Run with:  python3 -m tests.test_geo"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.geo import is_us, passes  # noqa: E402

failures = []

US = [
    ("New York, NY, United States", ""),
    ("Charlotte, NC", ""),
    ("Dallas, TX, USA", ""),
    ("San Francisco, California", ""),
    ("Chicago", ""),
    ("Menlo Park", ""),
    ("Washington, District of Columbia", ""),
    ("Jersey City, NJ", ""),
    ("2 Locations", "Summer Analyst - New York"),
    ("", "2027 Investment Banking Summer Analyst - Chicago"),
    # US cities that also exist abroad -- the US marker must win.
    ("Birmingham, AL, United States", ""),
    ("Manchester, NH", ""),
    ("Bristol, CT, United States", ""),
    ("Athens, GA", ""),
    ("Dublin, OH, United States", ""),
]

NOT_US = [
    ("LONDON, United Kingdom", ""),
    ("Frankfurt, Germany", ""),
    ("Hong Kong, China", ""),
    ("Singapore, Singapore", ""),
    ("Sao Paulo, Brazil", ""),
    ("Tel Aviv - Jaffa, Israel", ""),
    ("Mexico City, Mexico", ""),
    ("San Jose, Costa Rica", ""),
    ("Toronto, Canada", ""),
    ("Milano, Milano, Italy", ""),
    ("", "OLIVER WYMAN - INTERN CONSULTANT - 2026 - NETHERLANDS"),
    ("", "Consulting Intern, Italy"),
    ("Penang, Malaysia", ""),
]

UNKNOWN = [
    ("", ""),
    ("Remote", ""),
    ("Multiple Locations", ""),
]

for loc, title in US:
    if is_us(loc, title) is not True:
        failures.append("should be US:     %-40r title=%r -> %r" % (loc, title, is_us(loc, title)))

for loc, title in NOT_US:
    if is_us(loc, title) is not False:
        failures.append("should NOT be US: %-40r title=%r -> %r" % (loc, title, is_us(loc, title)))

for loc, title in UNKNOWN:
    if is_us(loc, title) is not None:
        failures.append("should be unknown:%-40r title=%r -> %r" % (loc, title, is_us(loc, title)))

# Two-letter codes that are also English words must not fire on their own.
for text in ["Working IN a team", "Sales OR marketing", "Learn ME first"]:
    if is_us(text, "") is True:
        failures.append("bare word matched a state code: %r" % text)

# The gate itself.
if passes("London, United Kingdom", "", us_only=True):
    failures.append("gate let a London role through")
if not passes("London, United Kingdom", "", us_only=False):
    failures.append("gate filtered when us_only was off")
if passes("", "", us_only=True, keep_unknown=False):
    failures.append("gate kept an unknown location when keep_unknown=False")
if not passes("", "", us_only=True, keep_unknown=True):
    failures.append("gate dropped an unknown location when keep_unknown=True")

total = len(US) + len(NOT_US) + len(UNKNOWN) + 3 + 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
