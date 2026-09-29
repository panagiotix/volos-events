"""Builds the public site into _site/: index.html + events.ics (the log stays out of the site)."""
import json, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregator
aggregator.run()
from aggregator import VENUES
data = json.load(open(f"{HERE}/output.json", encoding="utf-8"))
real = [e for e in data["events"] if not e.get("running")]          # films don't count
if len(real) < 10:
    print(f"Μόνο {len(real)} εκδηλώσεις (χωρίς τις ταινίες): πιθανή αποτυχία λήψεων. "
          "Δεν δημοσιεύεται, μένει η προηγούμενη σελίδα.")
    sys.exit(1)
from datetime import datetime
try:
    from zoneinfo import ZoneInfo                    # Python 3.9+
    now = datetime.now(ZoneInfo("Europe/Athens"))
except ImportError:                                   # Python 3.8: local time (the workflow sets TZ=Europe/Athens)
    now = datetime.now()
data["updated"] = now.strftime("%Y-%m-%dT%H:%M")
venues = [{"name": n, "aliases": a} for n, a in VENUES.values()]
html = open(f"{HERE}/page_template.html", encoding="utf-8").read()
html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__VENUES__", json.dumps(venues, ensure_ascii=False))
os.makedirs(f"{HERE}/_site", exist_ok=True)
open(f"{HERE}/_site/index.html", "w", encoding="utf-8").write(html)
shutil.copy(f"{HERE}/events.ics", f"{HERE}/_site/events.ics")
print(f"_site/ έτοιμο: {len(data['events'])} εκδηλώσεις")
