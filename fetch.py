"""
Daily download of the structured sources → live/<file>, in the same text form
the parsers read (HTML converted to Markdown). Respects robots.txt.
Sources whose snapshots were normalised by hand (More/Public listings, Mood,
tour pages, AOGOC) still need a dedicated HTML parser: until then they report
0 records in the log, which is the signal to write it.
"""
import json, os, re, sys, time, urllib.error, urllib.request, urllib.robotparser
from urllib.parse import urlparse
from markdownify import markdownify

UA = "VolosEventsBot/1.0 (+https://panagiotix.github.io/volos-events/; ημερολόγιο εκδηλώσεων Βόλου)"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/live"

# file the parser expects  →  page to download
PAGES = {
    "cineportal_volos.md": "https://cineportal.gr/bolos/",
    "thessaly_app.md":     "https://app.thessaly.gov.gr/TourismEventsApp",
    "uth_events.md":       "https://www.uth.gr/events",
    "ticketservices.md":   "https://www.ticketservices.gr/",
    "fever_volos.md":      "https://feverup.com/el/volos-ellada",
    "zagora_calendar.md":  "https://www.dimos-zagoras-mouresiou.gr/fullcalendar",
    "public_tickets.md":   "https://tickets.public.gr/gr-el/tickets/",
    "aogoc_volos.md":      "https://allofgreeceone.culture.gov.gr/en/?s=volos",
    # previously 403 — retried with complete headers; the log says who refused and why
    "artandlife_volos.md": "https://www.artandlife.gr/volos/events",
    "mood_volos.md":       "https://events.musicofourdesire.com/events/Volos",
}
# alternative entry points (feeds / sitemaps) that are often not behind the same filter
PROBES = [
    "https://www.artandlife.gr/sitemap.xml",
    "https://www.artandlife.gr/rss",
    "https://www.artandlife.gr/feed",
    "https://events.musicofourdesire.com/sitemap.xml",
]
# Not fetched: artandlife.gr and musicofourdesire.com answer 403 to bots; more.com's robots.txt
# does not respond (same catalogue is read from tickets.public.gr).
TOUR_SKIP = ("/cinema/", "/museums", "/streaming", "/subscriptions", "/voucher")
MAX_TOURS = 120

_robots = {}

def robots_for(url):
    """Read robots.txt ourselves (timeout + our User-Agent). Returns (parser|None, note).
    404/410 → no rules (allowed). 401/403 → the site blocks bots at the door: we stop there.
    Timeout or other error → skip this run, never guess."""
    host = urlparse(url)._replace(path="", query="", fragment="").geturl()
    if host in _robots: return _robots[host]
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
        res = (rp, "robots.txt OK")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.parse([]); res = (rp, f"χωρίς robots.txt ({e.code})")
        else:
            res = (None, f"robots.txt απάντησε {e.code} (προστασία από bots)")
    except Exception as e:
        res = (None, f"robots.txt δεν απάντησε ({type(e).__name__})")
    _robots[host] = res
    return res

HEADERS = {                      # a complete, ordinary request — but we still say who we are (UA)
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.5",
    "Accept-Encoding": "identity",
    "Connection": "close",
}

def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")

def why_blocked(ex):
    """For HTTP errors: status + hints about who answered (Cloudflare, other WAF)."""
    if not isinstance(ex, urllib.error.HTTPError): return f"{type(ex).__name__}: {ex}"
    h = ex.headers or {}
    hints = []
    if h.get("cf-ray") or "cloudflare" in (h.get("Server") or "").lower(): hints.append("Cloudflare")
    if h.get("Server"): hints.append(f"Server={h.get('Server')}")
    if h.get("x-sucuri-id"): hints.append("Sucuri")
    return f"HTTP {ex.code}" + (f" ({', '.join(hints)})" if hints else "")

def to_text(html):
    md = markdownify(html, heading_style="ATX", strip=["script", "style"])
    # one line per link text, as the parsers expect "[text](url)"
    md = re.sub(r"\[([^\]]*)\]\(", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)).strip() + "](", md)
    return re.sub(r"\n{3,}", "\n\n", md)

def main():
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    log = open(f"{OUT}/_fetch.log", "w", encoding="utf-8")
    def note(msg):
        print(msg); log.write(msg + "\n")
    for fname, url in PAGES.items():
        rp, why = robots_for(url)
        if rp is None:
            note(f"SKIP   {fname:24} {why}  ← {url}"); continue
        if not rp.can_fetch(UA, url):
            note(f"ROBOTS {fname:24} το robots.txt απαγορεύει ρητά αυτή τη σελίδα  ← {url}"); continue
        try:
            text = to_text(get(url))
            open(f"{OUT}/{fname}", "w", encoding="utf-8").write(text)
            note(f"OK     {fname:24} {len(text):>7} χαρακτήρες  ← {url}"); ok += 1
        except Exception as ex:
            note(f"ERR    {fname:24} {why_blocked(ex)}  ← {url}")
        time.sleep(2)                                    # polite pause between sites
    for url in PROBES:                                  # just report what answers; nothing is parsed yet
        rp, why = robots_for(url)
        if rp is None or not rp.can_fetch(UA, url):
            note(f"PROBE  {url}: παραλείπεται ({why})"); continue
        try:
            text = get(url)
            fname = "probe_" + re.sub(r"[^a-z0-9]+", "_", url.split("//")[1].lower()).strip("_")[:60] + ".txt"
            open(f"{OUT}/{fname}", "w", encoding="utf-8").write(text[:400000])
            note(f"PROBE  {url}: OK, {len(text)} χαρακτήρες → {fname}")
        except Exception as ex:
            note(f"PROBE  {url}: {why_blocked(ex)}")
        time.sleep(2)
    # tours: every "Πολλαπλοι χωροι" item of the Public.gr listing has a page with one row per stop
    tours = []
    try:
        listing = open(f"{OUT}/public_tickets.md", encoding="utf-8").read()
        for venue, path in re.findall(r"\n\n([^\n]+)\]\((/gr-el/tickets/[^)\s]+)\)", listing):
            if "πολλαπλοι χωροι" in venue.lower().replace("ώ", "ω").replace("ί", "ι") and not any(k in path for k in TOUR_SKIP):
                if path not in tours: tours.append(path)
    except FileNotFoundError:
        pass
    os.makedirs(f"{OUT}/tours", exist_ok=True)
    tok = 0
    for n, path in enumerate(tours[:MAX_TOURS]):
        url = "https://tickets.public.gr" + path
        try:
            text = to_text(get(url))
            open(f"{OUT}/tours/{n:03d}.md", "w", encoding="utf-8").write(f"URL: {url}\n\n" + text); tok += 1
        except Exception as ex:
            note(f"ERR    περιοδεία {path}: {type(ex).__name__}")
        time.sleep(1.5)
    note(f"Περιοδείες: {tok}/{min(len(tours), MAX_TOURS)} σελίδες κατέβηκαν")
    note(f"{ok}/{len(PAGES)} σελίδες κατέβηκαν")
    fetch_tours(note)
    log.close()

def fetch_tours(note):
    """Every 'Πολλαπλοί χώροι' card of the Public.gr listing is a tour: its page embeds
    the full schedule as JSON (bookingPanel.data). Saved as live/tours/<slug>.json."""
    listing = f"{OUT}/public_tickets.md"
    if not os.path.exists(listing): return
    text = open(listing, encoding="utf-8").read()
    urls = sorted(set(re.findall(r"\n\s*Πολλαπλοι [Χχ]ωροι\]\((/gr-el/tickets/[^)\s]+)\)", text)))
    urls = [u for u in urls if "/cinema/" not in u]         # film releases are covered by CinePortal
    os.makedirs(f"{OUT}/tours", exist_ok=True)
    got = 0
    for u in urls:
        url = PUBLIC_BASE + u
        rp, why = robots_for(url)
        if rp is None or not rp.can_fetch(UA, url): continue
        try:
            html = get(url)
            m = re.search(r"bookingPanel\.data\s*=\s*(\{.*?\});\s*\$\(document\)", html, re.S)
            if m:
                data = json.loads(m.group(1))
                data["_url"] = url
                slug = re.sub(r"[^a-z0-9-]+", "-", u.strip("/").split("/")[-1].lower())[:80]
                json.dump(data, open(f"{OUT}/tours/{slug}.json", "w", encoding="utf-8"), ensure_ascii=False)
                got += 1
        except Exception as ex:
            note(f"ERR    περιοδεία {u}: {type(ex).__name__}")
        time.sleep(1)
    note(f"Περιοδείες: {got}/{len(urls)} σελίδες με πρόγραμμα")
    return 0

if __name__ == "__main__":
    sys.exit(main())
