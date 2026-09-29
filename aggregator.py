"""
Volos & Pelion events aggregator — structured sources only (no LLM).

    collect (one small parser per source) -> classify area (Βόλος / Πήλιο / εκτός)
    -> filter -> deduplicate -> publish (JSON + iCal)

Snapshots are the pages as fetched on 29 Sept 2026; in production fetch() downloads the URLs.
"""
import json, re, os, hashlib, unicodedata, urllib.request
from feeds import parse_ics, parse_rss
import casing
from datetime import date
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
# LIVE=1 → read pages downloaded today by fetch.py (folder live/); otherwise the saved snapshots
SNAP = f"{HERE}/live" if os.environ.get("LIVE") == "1" else f"{HERE}/snapshots"
LIVE = os.environ.get("LIVE") == "1"
TODAY = date.fromisoformat(os.environ["SNAPSHOT_DATE"]) if os.environ.get("SNAPSHOT_DATE") else date.today()

# ------------------------------------------------------------------ sources report
SOURCES = [
    # tier: Κορμός
    {"tier": "Κορμός", "name": "Art&Life, Βόλος", "url": "https://www.artandlife.gr/volos/events", "status": "blocked",
     "note": "Απαντά 403 στα bots: δεν διαβάζεται αυτόματα. Χρειάζεται άδεια ή feed."},
    {"tier": "Κορμός", "name": "CinePortal, Βόλος", "url": "https://cineportal.gr/bolos/", "status": "ok",
     "note": "Ώρες προβολής ανά ημέρα και αίθουσα (Village, Εξωραϊστική)."},
    {"tier": "Κορμός", "name": "Περιφέρεια Θεσσαλίας, εφαρμογή εκδηλώσεων", "url": "https://app.thessaly.gov.gr/TourismEventsApp", "status": "ok",
     "note": "Φίλτρο ΠΕ Μαγνησίας. Η βασική πηγή για το Πήλιο."},
    {"tier": "Κορμός", "name": "Πανεπιστήμιο Θεσσαλίας, /events", "url": "https://www.uth.gr/events", "status": "ok",
     "note": "Κεντρική λίστα μόνο, χωρίς τα τμήματα. Δίνει ημερομηνία έναρξης· η λήξη βγαίνει από την περίληψη με κανόνα."},
    # tier: Εισιτήρια
    {"tier": "Εισιτήρια", "name": "TicketServices", "url": "https://www.ticketservices.gr/", "status": "ok",
     "note": "Ενιαία λίστα όλης της Ελλάδας με χώρο δίπλα σε κάθε εκδήλωση. Φίλτρο «ΒΟΛΟΣ/ΒΟΛΟΥ» στον χώρο."},
    {"tier": "Εισιτήρια", "name": "More.com (και Ticket365)", "url": "https://www.more.com/gr-el/tickets/", "status": "sparse",
     "note": "Το robots.txt δεν απαντά. Ο ίδιος κατάλογος διαβάζεται από το tickets.public.gr."},
    {"tier": "Εισιτήρια", "name": "Public.gr Tickets (κατάλογος More.com)", "url": "https://tickets.public.gr/gr-el/tickets/", "status": "ok",
     "note": "Ίδιος κατάλογος με το More.com. Εδώ βρέθηκαν οι προβολές στο Αχίλλειον (CineDoc Caravan)."},
    {"tier": "Εισιτήρια", "name": "Public.gr, σελίδες περιοδειών", "url": "https://tickets.public.gr/gr-el/tickets/standupcomedy/lampros-fisfis-poly-kalytera-tora-on-tour/", "status": "ok",
     "note": "Για κάθε «Πολλαπλοί χώροι» της λίστας ο crawler ανοίγει τη σελίδα της περιοδείας, όπου κάθε σταθμός έχει πόλη, χώρο, ώρα και τιμή. Στο More.com οι ίδιες σελίδες απαγορεύουν τα bots, στο public.gr επιτρέπονται."},
    {"tier": "Εισιτήρια", "name": "Mood (musicofourdesire)", "url": "https://events.musicofourdesire.com/events/Volos", "status": "blocked",
     "note": "Η σελίδα απαντά 403 στα bots. Δεν διαβάζεται αυτόματα."},
    {"tier": "Εισιτήρια", "name": "TicketServices, μεμονωμένες σελίδες", "url": "https://www.ticketservices.gr/event/dimotiko-theatro-volou-vira-tis-agkires/?lang=el", "status": "ok",
     "note": "Περασμένες εκδηλώσεις φεύγουν από την κεντρική λίστα αλλά η σελίδα τους μένει: εδώ κρατιούνται στο αρχείο. Η «Βίρα τις... άγκυρες!» ήταν στις 3/10/2025."},
    {"tier": "Εισιτήρια", "name": "Fever", "url": "https://feverup.com/el/volos-ellada", "status": "ok",
     "note": "Candlelight στο Domotel Xenia. Η σελίδα της πόλης αναμειγνύει και Θεσσαλονίκη: φίλτρο στον χώρο."},
    {"tier": "Εισιτήρια", "name": "Ticketmaster.gr", "url": "https://www.ticketmaster.gr/", "status": "blocked",
     "note": "Μπλοκάρει τα bots."},
    {"tier": "Εισιτήρια", "name": "Ticketportal.gr, Ticketseller.gr", "url": "", "status": "robots",
     "note": "Απαγορεύουν ρητά την αυτόματη πρόσβαση (robots.txt)."},
    {"tier": "Εισιτήρια", "name": "TicketBOX, TicketPlus", "url": "https://www.ticketbox.gr/", "status": "irrelevant",
     "note": "Λειτουργούν, αλλά καλύπτουν Κέρκυρα, Κρήτη, Αθήνα, Μυτιλήνη. Τίποτα για Βόλο ή Πήλιο."},
    {"tier": "Εισιτήρια", "name": "Eventbrite", "url": "https://www.eventbrite.com/d/greece--volos/events/", "status": "blocked",
     "note": "Σφάλμα 405 στα bots. Για την Ελλάδα κυρίως τουριστικά πακέτα· ελάχιστα για Βόλο και Πήλιο."},
    {"tier": "Εισιτήρια", "name": "Ticketpro.gr", "url": "", "status": "dead",
     "note": "Ληγμένο domain που ανακατευθύνει σε σελίδα καζίνο. Αποκλείεται."},
    {"tier": "Αρχεία", "name": "Όλη η Ελλάδα ένας Πολιτισμός, αναζήτηση «volos»", "url": "https://allofgreeceone.culture.gov.gr/en/?s=volos", "status": "ok",
     "note": "Αρχείο 2022–2026 για Αρχαίο Θέατρο Δημητριάδας και Αθανασάκειο. Η αναζήτηση φέρνει και άλλες πόλεις, που κόβει το φίλτρο."},
    {"tier": "Πήλιο", "name": "Δήμος Ζαγοράς-Μουρεσίου, Ατζέντα Εκδηλώσεων", "url": "https://www.dimos-zagoras-mouresiou.gr/fullcalendar", "status": "sparse",
     "note": "Δομημένο ημερολόγιο 2015–2025 με ώρες και RSS (/ekdilwseis_feed). Αραιή ενημέρωση: τελευταία καταχώριση Ιούλιος 2025."},
    {"tier": "Πήλιο", "name": "Δήμος Νοτίου Πηλίου", "url": "https://dnpiliou.gov.gr/", "status": "robots",
     "note": "Ενεργό site, με λίστα πανηγυριών του καλοκαιριού, αλλά το robots.txt απαγορεύει τα άρθρα. Χρειάζεται άδεια ή αποστολή feed."},
    {"tier": "Υποβολές", "name": "Φόρμα υποβολής (εκδήλωση, iCal, RSS, ιστοσελίδα)", "url": "", "status": "ok",
     "note": "Ό,τι εγκρίνει ο διαχειριστής εξάγεται ως submissions.json και διαβάζεται εδώ. Τα feeds iCal/RSS ανανεώνονται σε κάθε εκτέλεση."},
    # tier: removed
    {"tier": "Εκτός", "name": "Ειδησεογραφικά, RSS Δήμου, ραδιόφωνα, τμήματα ΠΘ", "url": "", "status": "removed",
     "note": "Αφαιρέθηκαν: τα άρθρα θέλουν LLM για ημερομηνία και χώρο, τα τμήματα βγήκαν από το scope."},
]

# ------------------------------------------------------------------ text helpers
def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("&", " και "))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def norm(s): return " ".join(re.findall(r"\w{4,}", fold(s)))

def shouty(t):
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.7

MONTHS = {"ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5, "ιουνιου": 6,
          "ιουλιου": 7, "αυγουστου": 8, "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12,
          "ιαν": 1, "φεβ": 2, "μαρ": 3, "απρ": 4, "μαι": 5, "ιουν": 6, "ιουλ": 7, "αυγ": 8, "σεπ": 9,
          "οκτ": 10, "νοε": 11, "δεκ": 12}

def mk_date(day, month_word, year=None):
    m = MONTHS[fold(month_word)]
    if year is None:                         # no year on the page: nearest future date
        year = TODAY.year if (date(TODAY.year, m, int(day)) - TODAY).days > -60 else TODAY.year + 1
    return date(int(year), m, int(day)).isoformat()

# ------------------------------------------------------------------ venues & areas
VENUES = {
    "theatro": ("Δημοτικό Θέατρο Βόλου «Βαγγέλης Παπαθανασίου»", ["βαγγελης παπαθανασιου", "δημοτικο θεατρο βολου", "vangelis papathanasiou"]),
    "achilleion": ("Κινηματοθέατρο Αχίλλειον", ["αχιλλειον", "achilleion"]),
    "ekthesiako": ("Εκθεσιακό Κέντρο Βόλου", ["εκθεσιακο κεντρο βολου"]),
    "demetrias": ("Αρχαίο Θέατρο Δημητριάδας", ["demetrias", "δημητριαδ"]),
    "athanasakeio": ("Αθανασάκειο Αρχαιολογικό Μουσείο", ["athanasakio", "αθανασακει"]),
    "theatrini": ("Κέντρο Πολιτισμού και Τεχνών «Θεατρίνη»", ["θεατρινη"]),
    "santan": ("Cafe Santan", ["cafe santan"]),
    "xenia": ("Domotel Xenia Volos", ["domotel xenia"]),
    "village": ("Village Cinemas Βόλος", ["village cinemas"]),
}
def match_venue(t):
    t = fold(t)
    for vid, (_, aliases) in VENUES.items():
        if any(a in t for a in aliases): return vid
    return None

PELION = ["παου", "pelion", "ξορυχτι", "ξουριχτι", "μουρεσι", "ανηλι", "πουρι", "πηλιο", "πηλιου", "ζαγορ", "μακρυραχ", "μακρινιτσ", "πορταρι", "χορτο", "αργαλαστ", "τσαγκαραδ",
          "μηλιες", "μηλινα", "αφετες", "χανια πηλ", "χιονοδρομικ", "αγιος λαυρεντιος", "νηλειας", "κισσος", "καλα νερα"]
VOLOS = ["βολο", "βολου", "volos", "αγρια", "γοριτσ", "νεα ιωνια", "αγχιαλο"]
OUT = ["tiryns", "oiniades", "dion,", "πατρων", "skiathos", "λαρισ", "λαμια", "τρικαλ", "καρδιτσ", "αλμυρ", "σκιαθ", "σκοπελ", "αλοννησ", "θεσσαλονικ", "πατρα", "αθηνα", "online"]

def classify(text):
    t = fold(text)
    if any(k in t for k in PELION): return "pelion"
    if any(k in t for k in VOLOS): return "volos"
    if any(k in t for k in OUT): return "out"
    return "unknown"

# ------------------------------------------------------------------ record
def rec(source, url, title, start, end=None, time=None, venue_text="", price=None, category="Άλλο", context="", running=False, note=None):
    return dict(source=source, url=url, title=title.strip(), start=start, end=end, time=time, venue_text=venue_text,
                price=price, category=category, context=context or f"{title} {venue_text}", running=running, note=note)

# ------------------------------------------------------------------ collectors
AL_CAT = {"Θέατρο": "Θέατρο", "Σινεμά": "Σινεμά", "Μουσική": "Μουσική", "Παιδί": "Παιδικά", "Εκθέσεις": "Εκθέσεις", "Χορός": "Χορός"}
def collect_artandlife():
    body, urls = open(f"{SNAP}/artandlife_volos.md", encoding="utf-8").read().split("URLS:")
    url_of = dict(l.split("|", 1) for l in urls.strip().splitlines())
    pat = re.compile(r"(\S+)\n\nA\n\nΠροσεχώς\n\n(.+?)\n\n(Από )?\[(\d+) (\S+) (\d{4})\]\([^)]*\)(?: - \[(\d+) (\S+) (\d{4})\]\([^)]*\))?\s*\n(.+?)\s*\n")
    out = []
    for cat, title, running, d, m, y, d2, m2, y2, venue in pat.findall(body):
        out.append(rec("Art&Life", url_of.get(title.strip(), "https://www.artandlife.gr/volos/events"), title,
                       mk_date(d, m, y), mk_date(d2, m2, y2) if d2 else None, None, venue.replace('""', '"'),
                       category=AL_CAT.get(cat, cat), context=f"{title} {venue} Βόλος", running=bool(running)))
    return out

def collect_cineportal():
    films, day, title = {}, None, None
    for line in open(f"{SNAP}/cineportal_volos.md", encoding="utf-8"):
        line = line.strip()
        dm = re.match(r"## .*?(\d{2})/(\d{2})/(\d{4})$", line)
        if dm: day = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"; continue
        if line.startswith("## "): title = line[3:]; films.setdefault(title, {}); continue
        for venue, times in re.findall(r"\[(VILLAGE CINEMAS VOLOS|ΕΞΩΡΑΙΣΤΙΚΗ ΘΕΡΙΝΟΣ) ((?:\d{2}:\d{2} Αίθουσα: \d+ ?)+)\]", line):
            v = "Village" if venue.startswith("VILLAGE") else "Εξωραϊστική (θερινός)"
            for t in re.findall(r"(\d{2}:\d{2})", times):
                films[title].setdefault(day, []).append(f"{t} {v}")
    out = []
    for title, show in films.items():
        r = rec("CinePortal", "https://cineportal.gr/bolos/", title, min(show), venue_text="Village Cinemas",
                category="Σινεμά", context="Βόλος", running=True)
        r["showtimes"] = {d: sorted(v) for d, v in sorted(show.items())}
        out.append(r)
    return out

CONFLICTS = {"https://app.thessaly.gov.gr/TourismEventsApp/Events/Details/338":
             "Αντίφαση πηγών: η Περιφέρεια γράφει «στο Βόλο», άλλη πηγή γράφει Καρδίτσα. Χρειάζεται επιβεβαίωση."}
def region_category(t):
    t = fold(t)
    for k, c in [("αγωνες", "Αθλητισμός"), ("trail", "Αθλητισμός"), ("rally", "Αθλητισμός"), ("χορωδ", "Μουσική"),
                 ("μουσικη", "Μουσική"), ("εκθεση", "Εκθέσεις"), ("σινεμα", "Σινεμά"), ("ανασυγκροτηση", "Συνέδρια"),
                 ("γαστρονομ", "Γαστρονομία"), ("γιορτη", "Γαστρονομία")]:
        if k in t: return c
    return "Άλλο"

REGION_BASE = "https://app.thessaly.gov.gr"

def collect_region():
    text = open(f"{SNAP}/thessaly_app.md", encoding="utf-8").read()
    rows = []
    live = re.compile(r"(\d{2})/(\d{2})/(\d{4}) - (\d{2})/(\d{2})/(\d{4})\s*\n(ΠΕ [^\n]+?)\s*\n([^\n]*)\n\s*\n([^\n]+)\n(.*?)Προβολή Εκδήλωσης\]\((\S+?)\)", re.S)
    for d1, m1, y1, d2, m2, y2, pe, cat, title, desc, url in live.findall(text):
        desc = re.sub(r"\s+", " ", desc)
        rows.append((title.strip(), d1, m1, y1, d2, m2, y2, pe.strip(), cat + " " + desc, url))
    old = re.compile(r"\[(.+?) (\d{2})/(\d{2})/(\d{4}) - (\d{2})/(\d{2})/(\d{4}) (ΠΕ \S+) (.+?) Προβολή Εκδήλωσης\]\((\S+)\)")
    if not rows:
        rows = [m.groups() for m in old.finditer(text)]
    out, rejected, seen = [], [], set()
    for title, d1, m1, y1, d2, m2, y2, pe, rest, url in rows:
        url = url if url.startswith("http") else REGION_BASE + url
        if url in seen: continue
        seen.add(url)
        if pe != "ΠΕ Μαγνησίας":
            continue                                       # other regional units: not ours (kept out of the log noise)
        s0, e0 = f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"
        low = fold(rest)
        place = ("Αγριά" if "αγρια" in low else "Λόφος Γορίτσας, Βόλος" if "γοριτσ" in low else
                 "Μακρυράχη, Πήλιο" if "μακρυραχ" in low else "Χιονοδρομικό Κέντρο Πηλίου" if "χιονοδρομ" in low else
                 "Βόλος" if "βολο" in low else "")
        out.append(rec("Περιφέρεια", url, title, s0, e0 if e0 != s0 else None, None, place,
                       category=region_category(title + " " + rest), context=f"{title} {rest}", note=CONFLICTS.get(url)))
    return out, rejected

def collect_uth():
    text = open(f"{SNAP}/uth_events.md", encoding="utf-8").read()
    pat = re.compile(r"Ημ\. Έναρξης\s+(\d{2})/(\d{2})\s+\[(.+?)\]\((\S+?)\)\s+(.+?)(?=\n\s*Ημ\. Έναρξης|\Z)", re.S)
    out = []
    for d, m, title, url, snippet in pat.findall(text):
        y = TODAY.year
        start = date(y, int(m), int(d)).isoformat()
        end = None                                        # rule: "από τις X [Μήνα] έως τις Y Μήνα ΕΤΟΣ"
        r = re.search(r"από τις (\d+)(?: (\S+))? έως τις (\d+) (\S+) (\d{4})", snippet)
        if r: end = mk_date(r.group(3), r.group(4), r.group(5))
        venue = "Τμήμα Αρχιτεκτόνων Μηχανικών ΠΘ" if "Συνέδριο στον Βόλο" in title else ""
        cat = "Συνέδρια" if "Συνέδρι" in title else "Περίπατοι & τέχνη" if "διαδρομή" in title else "Πανεπιστημιακά"
        out.append(rec("ΠΘ /events", url, title, start, end, None, venue, category=cat, context=f"{title} {snippet}"))
    return out

TS_BASE = "https://www.ticketservices.gr"
DATE_RX = r"(\d{1,2}) (\S+) (\d{4})"

def collect_ticketservices():
    text = open(f"{SNAP}/ticketservices.md", encoding="utf-8").read()
    cards = []
    if "#####" in text:                                   # live page: one card per "* [![" block
        for block in re.split(r"\n\* \[!\[", text):
            m = re.search(r"#####\s*(.+?)\*(.+?)\*\]\((\S+?)\)", block)
            if not m: continue
            head = block[:m.start()]
            cards.append((head, m.group(1), m.group(2), m.group(3)))
    else:                                                 # saved snapshot: "[dates TITLE*VENUE*](url)"
        for line in text.splitlines():
            m = re.search(r"\[(.+?)\*(.+?)\*\]\((\S+)\)", line)
            if not m: continue
            dates = list(re.finditer(DATE_RX, m.group(1)))
            if not dates: continue
            cards.append((m.group(1)[:dates[-1].end()], m.group(1)[dates[-1].end():], m.group(2), m.group(3)))
    out = []
    for head, title, venue, url in cards:
        dates = [d for d in re.finditer(DATE_RX, head) if fold(d.group(2)) in MONTHS]
        if not dates: continue
        running = "απο " in fold(head[:dates[0].start()+5]) or fold(head).strip().startswith("απο")
        s0 = mk_date(*dates[0].groups()); e0 = mk_date(*dates[-1].groups()) if len(dates) > 1 else None
        venue = venue.replace("<br>", " ")
        if not (match_venue(venue) or classify(venue) in ("volos", "pelion")):
            continue                                       # other cities: silently skipped
        url = url if url.startswith("http") else TS_BASE + url
        title = title.strip(" -")
        cat = "Μουσική" if re.search(r"VIVALDI|STRAUSS|συναυλ|ορχήστρ", title, re.I) else "Θέατρο"
        r = rec("TicketServices", url, title, s0, e0, None, venue, category=cat, context=f"{title} {venue}")
        out.append(r)
    return out

def collect_more():
    return collect_more_file("more_tickets.txt", "More.com")

def collect_more_file(fname, source):
    out = []
    for line in open(f"{SNAP}/{fname}", encoding="utf-8"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3: continue
        when, venue, title = parts[0], parts[-1], " | ".join(p for p in parts[1:-1] if fold(p) not in ("volos", "βολος"))
        dm = re.match(r"(\d{1,2}) (\S+)(?: - (\d{1,2}) (\S+))?", when)
        s = mk_date(dm.group(1), dm.group(2)); e = mk_date(dm.group(3), dm.group(4)) if dm.group(3) else None
        cat = "Μουσική" if re.search(r"live|τραγουδ|πλεσσας|spell", title, re.I) else "Άλλο"
        out.append(rec(source, "https://tickets.public.gr/gr-el/tickets/" if source != "More.com" else "https://www.more.com/gr-el/tickets/", title, s, e, None, venue,
                       category=cat, context=f"{title} {venue}"))
    return out

def collect_fever():
    out = []
    for line in open(f"{SNAP}/fever_volos.md", encoding="utf-8"):
        m = re.search(r"\[(Candlelight: .+?)(?:[\d,]+·)?(Domotel Xenia Volos City Resort|Θεσσαλονίκη) .+?(\d{1,2}) (\S{3}) Από ([\d,]+) €\]\((\S+)\)", line)
        if not m: continue
        title, venue, d, mon, price, url = m.groups()
        out.append(rec("Fever", url, title, mk_date(d, mon), None, None, venue, f"από {price}",
                       category="Μουσική", context=f"{title} {venue}"))
    return out

def collect_rows(fname, source, ncols):
    for line in open(f"{SNAP}/{fname}", encoding="utf-8"):
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) >= ncols: yield parts

def collect_public_listing():
    out = []
    for r in collect_more_file("public_tickets.txt", "Public.gr"):
        if "αχιλλειον" in fold(r["venue_text"]): r["category"] = "Σινεμά"
        out.append(r)
    return out

def collect_public_tour(fname):
    lines = open(f"{SNAP}/{fname}", encoding="utf-8").read().splitlines()
    url = lines[0].split("|", 1)[1]
    out = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(" | ")]
        d, m = re.search(r"(\d{1,2})/(\d{1,2})", parts[0]).groups()
        time, venue, price = parts[1], parts[-2], parts[-1]
        title = re.sub(r"\|\s*[^|]+$", "", " | ".join(parts[2:-2])).strip(" |").replace(" | ", " – ")
        start = date(TODAY.year, int(m), int(d)).isoformat()
        out.append(rec("Public.gr (περιοδεία)", url, title, start, None, time, venue.split(" - ")[0],
                       price.replace("€", ""), "Stand-up", context=f"{title} {venue}"))
    return out

def collect_mood():
    out = []
    for d, t, title, venue, url in collect_rows("mood_volos.txt", "Mood", 5):
        cat = "Φεστιβάλ" if "festival" in title.lower() else "Μουσική"
        out.append(rec("Mood", url, title, d, None, t, venue, None, cat, context=f"{title} {venue}"))
    return out

def collect_ts_pages():
    out = []
    for d, t, title, venue, price, url in collect_rows("ts_event_vira.txt", "TicketServices", 6):
        out.append(rec("TicketServices", url, title, d, None, t, venue, "0" if "ελευθερ" in fold(price) else price,
                       "Μουσική", context=f"{title} {venue}"))
    return out

def collect_aogoc():
    out = []
    for d1, d2, title, venue, url in collect_rows("aogoc_volos.txt", "Όλη η Ελλάδα", 5):
        out.append(rec("Όλη η Ελλάδα ένας Πολιτισμός", url, title, d1, d2, None, venue, None, "Θέατρο",
                       context=f"{title} {venue}"))
    return out

def collect_zagora():
    text = open(f"{SNAP}/zagora_calendar.md", encoding="utf-8").read()
    pat = re.compile(r"### (.+?)\n\s*\[\S+ (\d{2})/(\d{2})/(\d{4}) - (\d{2}:\d{2})(?: έως (?:\S+ (\d{2})/(\d{2})/(\d{4}) - )?\d{2}:\d{2})?\]\((\S+?)(?: \"[^\"]*\")?\)")
    out = []
    for title, d, m, y, t, d2, m2, y2, url in pat.findall(text):
        end = f"{y2}-{m2}-{d2}" if d2 else None
        low = fold(title)
        cat = ("Φεστιβάλ" if "φεστιβαλ" in low or "festival" in low else "Γαστρονομία" if "γιορτη" in low or "προιοντ" in low
               else "Εκθέσεις" if "εκθεση" in low else "Άλλο")
        url = url if url.startswith("http") else "https://www.dimos-zagoras-mouresiou.gr" + url
        out.append(rec("Δήμος Ζαγοράς", url, title, f"{y}-{m}-{d}", end if end != f"{y}-{m}-{d}" else None,
                       None if t == "00:00" else t, "Ζαγορά-Μούρεσι, Πήλιο", category=cat, context=f"{title} Πήλιο"))
    return out

# ================================================================ live-format parsers
PUBLIC_BASE = "https://tickets.public.gr"
SHORT_M = {"ιαν":1,"φεβ":2,"μαρ":3,"απρ":4,"μαι":5,"ιουν":6,"ιουλ":7,"αυγ":8,"σεπ":9,"οκτ":10,"νοε":11,"δεκ":12}

def month_num(word):
    w = fold(word).strip(".,")
    if w in MONTHS: return MONTHS[w]
    for k, v in SHORT_M.items():
        if w.startswith(k): return v
    return None

def dm_to_iso(d, m_word):
    m = month_num(m_word)
    if not m: return None
    d = int(d)
    y = TODAY.year if (date(TODAY.year, m, d) - TODAY).days > -60 else TODAY.year + 1
    return date(y, m, d).isoformat()

def parse_public_when(when):
    """'31 Οκτωβριου' | '1 - 11 Οκτωβριου' | '14 Νοε - 2 Ιαν' → (start, end)"""
    w = when.strip()
    m = re.match(r"(\d{1,2}) (\S+) - (\d{1,2}) (\S+)$", w)
    if m: return dm_to_iso(m.group(1), m.group(2)), dm_to_iso(m.group(3), m.group(4))
    m = re.match(r"(\d{1,2}) - (\d{1,2}) (\S+)$", w)
    if m: return dm_to_iso(m.group(1), m.group(3)), dm_to_iso(m.group(2), m.group(3))
    m = re.match(r"(\d{1,2}) (\S+)$", w)
    if m: return dm_to_iso(m.group(1), m.group(2)), None
    return None, None

PUBLIC_ITEM = re.compile(r"\n\n([^\n]+)\n\n### ([^\n]+)\n\n([^\n]+)\]\((/gr-el/tickets/[^)\s]+)\)")

def collect_public_live():
    text = open(f"{SNAP}/public_tickets.md", encoding="utf-8").read()
    out, seen = [], set()
    for when, title, venue, path in PUBLIC_ITEM.findall(text):
        if path in seen: continue
        seen.add(path)
        if "πολλαπλοι χωροι" in fold(venue): continue        # tours: read from their own pages
        if not (match_venue(venue) or classify(venue) in ("volos", "pelion")): continue
        start, end = parse_public_when(when)
        if not start: continue
        cat = "Σινεμά" if "/cinema/" in path else "Θέατρο" if "/theater/" in path else "Μουσική" if "/music/" in path else "Άλλο"
        title = re.sub(r"\s+\d{1,2}/\d{1,2}$", "", title.strip())
        parts = [p.strip() for p in title.split("|")]
        title = " | ".join(p for p in parts if fold(p) not in ("volos", "βολος") and fold(p) != fold(venue)) or parts[0]
        out.append(rec("Public.gr", PUBLIC_BASE + path, title, start, end if end != start else None, None, venue,
                       category=cat, context=f"{title} {venue}"))
    return out

TOUR_ROW = re.compile(r"\n\S+, (\d{1,2})/(\d{1,2})\n\n(\d{1,2}:\d{2})\n\n([^\n]+)\n\n(?:\[[^\n]*\)\n\n)?([^\n]+)\n\n([\d.,]+)\s*€")

def collect_tours_live():
    out = []
    tdir = f"{SNAP}/tours"
    if not os.path.isdir(tdir): raise FileNotFoundError(tdir)
    for fn in sorted(os.listdir(tdir)):
        text = open(f"{tdir}/{fn}", encoding="utf-8").read()
        m = re.search(r"^URL: (\S+)", text, re.M)
        url = m.group(1) if m else PUBLIC_BASE
        for d, mo, t, title, venue, price in TOUR_ROW.findall(text):
            if not (match_venue(venue) or classify(venue) in ("volos", "pelion")): continue
            mo, d = int(mo), int(d)
            y = TODAY.year if (date(TODAY.year, mo, d) - TODAY).days > -60 else TODAY.year + 1
            title = re.sub(r"\s*\|\s*[^|]*$", "", title).replace("|", "–").strip(" –")
            venue_name = venue.split(" - ")[0].strip()
            cat = "Stand-up" if "standup" in url else "Θέατρο" if "theat" in url else "Μουσική" if "music" in url else "Άλλο"
            out.append(rec("Public.gr (περιοδεία)", url, title, date(y, mo, d).isoformat(), None, t, venue_name,
                           price.replace(",", "."), cat, context=f"{title} {venue}"))
    return out

FEVER_ITEM = re.compile(r"\n\s*([^\n]+)\n\n\s*### ([^\n]+)\n\n\s*(\d{1,2}) (\S+)[^\n]*\n\n\s*Από ([\d,.]+)\s*€\]\((/m/\d+)")

def collect_fever_live():
    text = open(f"{SNAP}/fever_volos.md", encoding="utf-8").read()
    out, seen = [], set()
    for venue, title, d, mon, price, path in FEVER_ITEM.findall(text):
        if path in seen or "volos" not in fold(venue) and not match_venue(venue): continue
        seen.add(path)
        start = dm_to_iso(d, mon)
        if not start: continue
        out.append(rec("Fever", "https://feverup.com" + path, title.strip(), start, None, None, venue.strip(),
                       f"από {price}", "Μουσική", context=f"{title} {venue}"))
    return out

AOGOC_ITEM = re.compile(r"(?:(\d{2})\.(\d{2}) — )?(\d{2})\.(\d{2})\.(\d{4})\n\n([^\n]+)\n\n### ([^\n]+)\n\n(.*?)\]\((https://allofgreeceone\.culture\.gov\.gr/[^\s)]+)", re.S)

def collect_aogoc_live():
    text = open(f"{SNAP}/aogoc_volos.md", encoding="utf-8").read()
    out, seen = [], set()
    for d1, m1, d2, m2, y, cat, title, venue, url in AOGOC_ITEM.findall(text):
        if url in seen: continue
        seen.add(url)
        venue = re.sub(r"\s+", " ", venue).strip()
        end = f"{y}-{m2}-{d2}"
        start = f"{y}-{m1}-{d1}" if d1 else end
        out.append(rec("Όλη η Ελλάδα ένας Πολιτισμός", url, title.strip(), start, end if end != start else None,
                       None, venue, None, "Μουσική" if "music" in fold(cat) else "Θέατρο", context=f"{title} {venue}"))
    return out

# ------------------------------------------------------------------ dedup
def film_key(t): return norm(t.split(" - ")[0].replace("Encore", ""))

def same_event(a, b):
    if a["running"] or b["running"]:
        if not (a["running"] and b["running"]): return False
        ka, kb = film_key(a["title"]), film_key(b["title"])
        return ka.startswith(kb) or kb.startswith(ka)
    if not a["start"] or a["start"] != b["start"]: return False
    va, vb = match_venue(a["venue_text"]), match_venue(b["venue_text"])
    shared = set(norm(a["title"]).split()) & set(norm(b["title"]).split())
    sim = SequenceMatcher(None, norm(a["title"]), norm(b["title"])).ratio()
    if va and va == vb and (len(shared) >= 2 or (a["end"] and a["end"] == b["end"])): return True
    if a["end"] and a["end"] == b["end"] and len(shared) >= 3: return True
    if (va is None or vb is None) and (len(shared) >= 3 or sim > 0.6): return True
    return False

def dedupe(rows):
    merged = []
    for r in rows:
        for m in merged:
            if same_event(m, r):
                m["sources"].append({"source": r["source"], "url": r["url"]})
                for k in ("time", "price", "end", "note"): m[k] = m[k] or r[k]
                if r.get("showtimes"): m["showtimes"] = r["showtimes"]
                if len(r["venue_text"]) > len(m["venue_text"]) and not m["running"]: m["venue_text"] = r["venue_text"]
                if shouty(m["title"]) and not shouty(r["title"]): m["title"] = r["title"]
                break
        else:
            merged.append({**r, "sources": [{"source": r["source"], "url": r["url"]}]})
    return merged

# ------------------------------------------------------------------ run
def write_log(raw, events, rejected):
    """Personal run log (Markdown): sources, per-source yield, rejections, past events."""
    from collections import Counter
    per_src = Counter(r["source"] for r in raw)
    kept_src = Counter(s["source"] for e in events for s in e["sources"])
    L = [f"# Log συλλογής — {TODAY.isoformat()}", "",
         f"- Εγγραφές που μαζεύτηκαν: **{len(raw)}**",
         f"- Εκδηλώσεις στη σελίδα: **{sum(not e['past'] and not e['running'] for e in events)}** "
         f"(Βόλος {sum(e['area']=='volos' and not e['past'] and not e['running'] for e in events)}, "
         f"Πήλιο {sum(e['area']=='pelion' and not e['past'] and not e['running'] for e in events)}) "
         f"+ {sum(e['running'] for e in events)} ταινίες",
         f"- Βρέθηκαν σε πολλές πηγές: **{sum(len(e['sources'])>1 for e in events)}**",
         f"- Περασμένες (δεν εμφανίζονται): **{sum(e['past'] for e in events)}**",
         f"- Απορρίφθηκαν: **{len(rejected)}**", "",
         "## Απόδοση ανά πηγή σε αυτή την εκτέλεση", "",
         "| Πηγή | Εγγραφές | Στη σελίδα ή στις περασμένες |", "|---|---:|---:|"]
    for src, n in per_src.most_common():
        L.append(f"| {src} | {n} | {kept_src.get(src, 0)} |")
    L += ["", "## Σφάλματα πηγών", ""] + (SOURCE_ERRORS or ["- Κανένα."])
    L += ["", "## Τίτλοι με κεφαλαία που έμειναν ως έχουν", "",
          "Πρόσθεσε τις λέξεις στο `accents.txt` με σωστό τονισμό (κεφαλαίο πρώτο γράμμα = κύριο όνομα).", ""]
    missing = sorted({w for _, ws in CASING_LOG for w in ws})
    L += [f"- {t} — λείπουν: {', '.join(ws)}" for t, ws in CASING_LOG] or ["- Κανένας."]
    if missing: L += ["", "Όλες μαζί: " + " ".join(missing)]
    L += ["", "## Υποβολές και feeds διοργανωτών", ""] + (FEED_LOG or ["- Καμία εγκεκριμένη υποβολή feed σε αυτή την εκτέλεση."])
    L += ["", "## Κατάσταση πηγών", "", "| Κατάσταση | Πηγή | Σημείωση |", "|---|---|---|"]
    for x in SOURCES:
        name = f"[{x['name']}]({x['url']})" if x["url"] else x["name"]
        L.append(f"| {x['status']} | {name} | {x['note']} |")
    L += ["", "## Απορρίψεις", "",
          "Για να αλλάξεις μια απόφαση, πρόσθεσε στο `overrides.json`: "
          '`"<key>": {"match_url": "<url>", "area": "volos|pelion|reject"}`', ""]
    by_reason = {}
    for r in rejected: by_reason.setdefault(r["reason"], []).append(r)
    for reason, rows in by_reason.items():
        L += [f"### {reason} ({len(rows)})", ""]
        for r in rows:
            when = r.get("start") or "χωρίς ημερομηνία"
            L.append(f"- `{r['key']}` {when} — **{r['title']}** — {r.get('venue') or ''} — {r['source']}"
                     + (f" — {r['url']}" if r.get("url") else ""))
        L.append("")
    L += ["## Περασμένες εκδηλώσεις (δεν εμφανίζονται στη σελίδα)", ""]
    for e in sorted((e for e in events if e["past"]), key=lambda e: e["start"], reverse=True):
        L.append(f"- {e['start']} — {e['title']} — {e['venue']} — {', '.join(s['source'] for s in e['sources'])}")
    open(f"{HERE}/log.md", "w", encoding="utf-8").write("\n".join(L) + "\n")

FEED_LOG = []
CASING_LOG = []
SOURCE_ERRORS = []

def safe(fn, *a):
    name = getattr(fn, "__name__", str(fn))
    try:
        res = fn(*a)
        return res
    except FileNotFoundError:
        SOURCE_ERRORS.append(f"- `{name}`: δεν υπάρχει σημερινή λήψη (δεν έχει ζωντανή λήψη ή απέτυχε)")
    except Exception as ex:
        SOURCE_ERRORS.append(f"- `{name}`: σφάλμα {type(ex).__name__}: {ex}")
    return ([], []) if name == "collect_region" else []

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "VolosEventsBot/1.0 (+contact in site footer)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")

def collect_submissions(path=None):
    """Approved submissions exported from the admin page (submissions.json):
    single events go straight in; approved iCal/RSS feeds are fetched and parsed."""
    path = path or f"{HERE}/submissions.json"
    if not os.path.exists(path): return []
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for e in data.get("events", []):
        out.append(rec("Υποβολή", e.get("link") or "#", e["title"], e["start"], e.get("end") or None, e.get("time") or None,
                       e.get("venue", ""), "0" if e.get("free") else (e.get("price") or None), e.get("category", "Άλλο"),
                       context=f"{e['title']} {e.get('venue','')} {'Πήλιο' if e.get('area')=='pelion' else 'Βόλος'}"))
    for f in data.get("feeds", []):
        name = f"Feed: {f.get('organizer') or f['url']}"
        area_hint = "Πήλιο" if f.get("area") == "pelion" else "Βόλος"
        try:
            text = fetch_text(f["url"])
        except Exception as ex:
            FEED_LOG.append(f"- **{name}** ({f['kind']}): δεν ήταν δυνατή η λήψη — {type(ex).__name__}"); continue
        if f["kind"] == "ical":
            items, undated = parse_ics(text), []
        elif f["kind"] == "rss":
            items, undated = parse_rss(text, TODAY)
        else:
            FEED_LOG.append(f"- **{name}**: ιστοσελίδα — χρειάζεται δικός της parser"); continue
        for it in items:
            out.append(rec(name, it["url"] or f["url"], it["title"], it["start"], it["end"], it["time"], it["venue"],
                           None, f.get("category") or "Άλλο", context=f"{it['title']} {it['venue']} {area_hint}"))
        FEED_LOG.append(f"- **{name}** ({f['kind']}): {len(items)} εκδηλώσεις"
                        + (f", {len(undated)} χωρίς ημερομηνία εκδήλωσης: " + "; ".join(undated[:5]) if undated else ""))
    return out

def load_overrides():
    try:
        o = json.load(open(f"{HERE}/overrides.json", encoding="utf-8"))
        return {v["match_url"]: v for k, v in o.items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}

def run():
    raw, rejected = [], []
    raw += safe(collect_cineportal) + safe(collect_uth) + safe(collect_ticketservices) + safe(collect_zagora)
    reg, rej = safe(collect_region); raw += reg
    if LIVE:
        raw += safe(collect_public_live) + safe(collect_tours_live) + safe(collect_fever_live) + safe(collect_aogoc_live)
        for fn, f in ((collect_artandlife, "artandlife_volos.md"), (collect_mood, "mood_volos.md")):
            if os.path.exists(f"{SNAP}/{f}"):
                got = safe(fn); raw += got
                if not got: SOURCE_ERRORS.append(f"- `{fn.__name__}`: η σελίδα κατέβηκε αλλά ο parser δεν βρήκε τίποτα — χρειάζεται προσαρμογή στη ζωντανή μορφή")
    else:                                                 # saved snapshots (offline test)
        raw += safe(collect_artandlife) + safe(collect_more) + safe(collect_fever) + safe(collect_public_listing)
        raw += safe(collect_public_tour, "public_tour_fisfis.txt") + safe(collect_mood)
        raw += safe(collect_ts_pages) + safe(collect_aogoc)
    raw += safe(collect_submissions)
    overrides = load_overrides()

    kept = []
    for r in raw:
        ov = overrides.get(r["url"])
        area = ov["area"] if ov else ("volos" if match_venue(r["venue_text"]) else classify(r["context"]))
        if ov: r["note"] = ov.get("note"); r["manual"] = True
        why = None
        if area == "reject": why = "Απορρίφθηκε χειροκίνητα"
        elif area == "out": why = "Εκτός Βόλου και Πηλίου"
        elif "πολλαπλοι χωροι" in fold(r["venue_text"]): why = "Περιοδεία: οι σταθμοί έρχονται από τη σελίδα της"
        elif area == "unknown": why = "Άγνωστη τοποθεσία"
        elif "προθεσμια" in fold(r["title"]): why = "Προθεσμία, όχι εκδήλωση"
        if why:
            key = hashlib.md5(f"{r['url']}|{r['title']}".encode()).hexdigest()[:10]
            if not any(x["key"] == key for x in rejected):
                rejected.append({"key": key, "title": r["title"], "source": r["source"], "reason": why,
                                 "start": r["start"], "end": r["end"], "time": r["time"], "url": r["url"],
                                 "venue": r["venue_text"], "category": r["category"]})
            continue
        r["area"] = area
        r["past"] = (not r["running"]) and bool(r["start"]) and (r["end"] or r["start"]) < TODAY.isoformat()
        kept.append(r)

    events = dedupe(kept)
    # ALL-CAPS titles → normal Greek, only where every word's accent is known
    lex = casing.build_lexicon([SNAP, f"{HERE}/snapshots"], ["/usr/share/hunspell/el_GR.dic"], f"{HERE}/accents.txt")
    for e in events:
        new, unknown = casing.recase(e["title"], lex)
        if unknown and not e["past"]:
            CASING_LOG.append((e["title"], unknown))
        e["title"] = new
    for e in events:
        vid = match_venue(e["venue_text"])
        if vid == "achilleion":
            e["hall"] = "Αχίλλειον"; e["category"] = "Σινεμά"
        e["venue"] = VENUES[vid][0] if vid else e["venue_text"]
        e["id"] = hashlib.md5(f"{e['title']}{e['start']}".encode()).hexdigest()[:10]
        e["method"] = "parser"
        e.pop("context", None); e.pop("source", None)
    events.sort(key=lambda e: (e["area"], e["start"] or "9999", e["time"] or ""))

    print(f"archive: {sum(e['past'] for e in events)} past events kept")
    print(f"{len(raw)} records -> {len(events)} kept ({sum(e['area']=='volos' for e in events)} Βόλος, "
          f"{sum(e['area']=='pelion' for e in events)} Πήλιο), {len(rejected)} rejected\n")
    for e in events:
        if e["past"]: continue
        print(f"[{e['area'][:3]}] {e['start']} {e['title'][:52]:52} [{len(e['sources'])}] {', '.join(s['source'] for s in e['sources'])}")
    print("\nRejected:"); [print(f"  - {r['title'][:55]:55} -> {r['reason']}") for r in rejected]

    current = [e for e in events if not e["past"]]
    json.dump({"generated": TODAY.isoformat(), "events": current},
              open(f"{HERE}/output.json", "w"), ensure_ascii=False, indent=1)
    write_log(raw, events, rejected)
    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Volos Events//EL"]
    for e in events:
        if e["running"] or e["past"]: continue
        d = e["start"].replace("-", "")
        dt = f"DTSTART;TZID=Europe/Athens:{d}T{e['time'].replace(':','')}00" if e["time"] else f"DTSTART;VALUE=DATE:{d}"
        ics += ["BEGIN:VEVENT", f"UID:{e['id']}@volos-events", dt, f"SUMMARY:{e['title']}",
                f"LOCATION:{e['venue']}", f"URL:{e['sources'][0]['url']}", "END:VEVENT"]
    open(f"{HERE}/events.ics", "w").write("\r\n".join(ics + ["END:VCALENDAR"]))

if __name__ == "__main__":
    run()
