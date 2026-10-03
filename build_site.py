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
# ---- Supabase: your decisions (hide, corrections, approved submissions) shape the page
import supa
from datetime import date
supa_note = "Supabase: δεν έχει ρυθμιστεί (η σελίδα χτίζεται μόνο από τη συλλογή)"
if supa.enabled():
    try:
        today = date.fromisoformat(data["generated"])
        n = supa.push_events(data["events"])
        published = supa.pull_public(today)
        films = [e for e in data["events"] if e.get("running")]
        if n and len(published) < n * 0.5:             # far fewer than we sent: something is wrong, don't empty the page
            supa_note = (f"Supabase: ΠΡΟΣΟΧΗ — στάλθηκαν {n} αλλά διαβάστηκαν πίσω μόνο {len(published)}. "
                         "Η σελίδα χτίστηκε από τη συλλογή· έλεγξε το view public_events.")
        else:
            data["events"] = films + published
            st = supa.PULL_STATS
            supa_note = (f"Supabase: {n} εκδηλώσεις στάλθηκαν, {len(published)} δημοσιευμένες διαβάστηκαν πίσω "
                         f"(από αυτές {st['submitted']} από εγκεκριμένες υποβολές, {st['own']} δικές σου)")
    except Exception as ex:                            # Supabase down/paused: keep the collected events
        supa_note = f"Supabase: σφάλμα ({type(ex).__name__}: {ex}) — η σελίδα χτίστηκε από τη συλλογή"
if supa.enabled(): supa_note += f" · κλειδί workflow: {supa.key_role()}"
print(supa_note)
try:
    with open(f"{HERE}/log.md", "a", encoding="utf-8") as lf: lf.write(f"\n## Supabase\n\n- {supa_note}\n")
except OSError:
    pass

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
# public config for the submission form: URL + anon key only (protected by Row Level Security)
SB_URL, SB_ANON = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_ANON_KEY", "")
html = html.replace("__SUPABASE_URL__", SB_URL).replace("__SUPABASE_ANON__", SB_ANON)
os.makedirs(f"{HERE}/_site", exist_ok=True)
open(f"{HERE}/_site/index.html", "w", encoding="utf-8").write(html)
shutil.copy(f"{HERE}/events.ics", f"{HERE}/_site/events.ics")
admin = open(f"{HERE}/admin_template.html", encoding="utf-8").read()
open(f"{HERE}/_site/admin.html", "w", encoding="utf-8").write(admin.replace("__SUPABASE_URL__", SB_URL).replace("__SUPABASE_ANON__", SB_ANON))
if os.path.isdir(f"{HERE}/assets"):                      # logo and other static files
    shutil.copytree(f"{HERE}/assets", f"{HERE}/_site/assets", dirs_exist_ok=True)
print(f"_site/ έτοιμο: {len(data['events'])} εκδηλώσεις")
