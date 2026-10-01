"""
Daily download of the structured sources → live/<file> (HTML converted to Markdown,
the form the parsers in aggregator.py read). Respects robots.txt; identifies itself.

Exit code 1 when most downloads fail, so the workflow stops and the previous page stays online.
"""
import http.cookiejar, os, re, shutil, sys, time, urllib.error, urllib.request, urllib.robotparser
from urllib.parse import urlparse
from markdownify import markdownify

UA = "VolosEventsBot/1.0 (+https://panagiotix.github.io/volos-events/; events calendar for Volos, Greece)"
UA.encode("latin-1")          # HTTP headers must be Latin-1: fail here, not on every request

HEADERS = {                   # a complete, ordinary request — while saying who we are (UA)
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.5",
    "Accept-Encoding": "identity",
    "Connection": "close",
}
for _v in HEADERS.values(): _v.encode("latin-1")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/live"
PUBLIC_BASE = "https://tickets.public.gr"

# file the parser expects → page to download
PAGES = {
    "cineportal_volos.md": "https://cineportal.gr/bolos/",
    "thessaly_app.md":     "https://app.thessaly.gov.gr/TourismEventsApp",
    "uth_events.md":       "https://www.uth.gr/events",
    "ticketservices.md":   "https://www.ticketservices.gr/",
    "fever_volos.md":      "https://feverup.com/el/volos-ellada",
    "zagora_calendar.md":  "https://www.dimos-zagoras-mouresiou.gr/fullcalendar",
    "public_tickets.md":   "https://tickets.public.gr/gr-el/tickets/",   # same catalogue as more.com
    "aogoc_volos.md":      "https://allofgreeceone.culture.gov.gr/en/?s=volos",
    "allevents_volos.md":  "https://allevents.in/volos",           # served as Markdown (see MARKDOWN_OK)
    # answered 403 before; retried with complete headers — the log says who refused
    "artandlife_volos.md": "https://www.artandlife.gr/volos/events",
    "mood_volos.md":       "https://events.musicofourdesire.com/events/Volos",
}
# alternative entry points (feeds / sitemaps): only reported, not parsed yet
PROBES = [
    "https://www.artandlife.gr/sitemap.xml",
    "https://www.artandlife.gr/rss",
    "https://www.artandlife.gr/feed",
    "https://events.musicofourdesire.com/sitemap.xml",
]
VMOC_SITEMAP = "https://vmoc.gr/index.php/Site_Map"
DIKI_SITEMAP = "http://www.diki.gr/index.php/Site_Map"
PEV_LIST = "https://events.public.gr/events.php?region=%CE%92%CF%8C%CE%BB%CE%BF%CF%82"
PEV_SITEMAP = "https://events.public.gr/sitemap.xml"
PEV_LINK = re.compile(r"(?:https://events\.public\.gr)?/([a-z0-9][a-z0-9-]+/\d+)(?=[\s\"')<?#]|$)")
PEV_MAX = 60
DIKI_MAX = 10
VMOC_MAX = 8                  # newest exhibitions come first in the menu
TOUR_SKIP = ("/cinema/", "/museums", "/streaming", "/subscriptions", "/voucher")
MAX_TOURS = 120

# ---------------------------------------------------------------- robots.txt
_robots = {}

def robots_for(url):
    """(parser|None, note). 404/410 → no rules (allowed). Other errors → skip today, never guess."""
    host = urlparse(url)._replace(path="", query="", fragment="").geturl()
    if host in _robots: return _robots[host]
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(host + "/robots.txt", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
        res = (rp, "robots.txt OK")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.parse([]); res = (rp, f"χωρίς robots.txt ({e.code})")
        else:
            res = (None, f"robots.txt: {why_blocked(e)}")
    except Exception as e:
        res = (None, f"robots.txt δεν απάντησε ({type(e).__name__})")
    _robots[host] = res
    return res

# ---------------------------------------------------------------- download
# some pages (Public.gr tours) set a session cookie and redirect (302) to themselves:
# without a cookie jar that is an endless redirect, so we keep cookies for the run
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

MARKDOWN_OK = ("allevents.in",)   # sites that offer a Markdown version of the page: ask for it

def get(url, attempts=3):
    """Slow servers (e.g. the 500 KB Public.gr list) get more time; 4xx errors are not retried."""
    last = None
    for i in range(attempts):
        try:
            return _get_once(url, timeout=30 * (i + 1))
        except urllib.error.HTTPError as e:
            if e.code < 500: raise
            last = e
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
            last = e
        time.sleep(5 * (i + 1))
    raise last

def _get_once(url, timeout):
    h = dict(HEADERS)
    if any(d in url for d in MARKDOWN_OK):
        h["Accept"] = "text/markdown, text/html;q=0.8"
    req = urllib.request.Request(url, headers=h)
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")

def why_blocked(ex):
    """HTTP status + who answered (Cloudflare, other WAF), for the log."""
    if not isinstance(ex, urllib.error.HTTPError): return f"{type(ex).__name__}: {ex}"
    h = ex.headers or {}
    hints = []
    if h.get("cf-ray") or "cloudflare" in (h.get("Server") or "").lower(): hints.append("Cloudflare")
    elif h.get("Server"): hints.append(f"Server={h.get('Server')}")
    if h.get("x-sucuri-id"): hints.append("Sucuri")
    return f"HTTP {ex.code}" + (f" ({', '.join(hints)})" if hints else "")

def to_text(html):
    md = markdownify(html, heading_style="ATX", strip=["script", "style"])
    md = re.sub(r"\[([^\]]*)\]\(", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)).strip() + "](", md)
    return re.sub(r"\n{3,}", "\n\n", md)

def allowed(url, note, label):
    rp, why = robots_for(url)
    if rp is None:
        note(f"SKIP   {label:24} {why}  ← {url}"); return False
    if not rp.can_fetch(UA, url):
        note(f"ROBOTS {label:24} το robots.txt απαγορεύει ρητά αυτή τη σελίδα  ← {url}"); return False
    return True

# ---------------------------------------------------------------- main
def main():
    shutil.rmtree(OUT, ignore_errors=True)          # never mix today's downloads with old ones
    os.makedirs(f"{OUT}/tours", exist_ok=True)
    log = open(f"{OUT}/_fetch.log", "w", encoding="utf-8")
    def note(msg):
        print(msg, flush=True); log.write(msg + "\n")

    ok = 0
    for fname, url in PAGES.items():
        if not allowed(url, note, fname): continue
        try:
            raw = get(url)
            if "**Event Name**" in raw:
                text = raw                                   # already structured Markdown (allevents)
            else:
                text = to_text(raw)
                if "ld+json" in raw:                         # keep the raw HTML: its schema.org JSON-LD is parsable
                    open(f"{OUT}/{fname[:-3]}.html", "w", encoding="utf-8").write(raw)
            open(f"{OUT}/{fname}", "w", encoding="utf-8").write(text)
            note(f"OK     {fname:24} {len(text):>7} χαρακτήρες  ← {url}"); ok += 1
        except Exception as ex:
            note(f"ERR    {fname:24} {why_blocked(ex)}  ← {url}")
        time.sleep(2)                                # polite pause between requests

    for url in PROBES:
        if not allowed(url, note, "probe"): continue
        try:
            text = get(url)
            fname = "probe_" + re.sub(r"[^a-z0-9]+", "_", url.split("//")[1].lower()).strip("_")[:60] + ".txt"
            open(f"{OUT}/{fname}", "w", encoding="utf-8").write(text[:400000])
            note(f"PROBE  {url}: OK, {len(text)} χαρακτήρες → {fname}")
        except Exception as ex:
            note(f"PROBE  {url}: {why_blocked(ex)}")
        time.sleep(2)

    # tours: each "Πολλαπλοι χωροι" card of the Public.gr listing has a page with one row per stop
    tours = []
    if os.path.exists(f"{OUT}/public_tickets.md"):
        listing = open(f"{OUT}/public_tickets.md", encoding="utf-8").read()
        for venue, path in re.findall(r"\n\n([^\n]+)\]\((/gr-el/tickets/[^)\s]+)\)", listing):
            v = venue.lower().replace("ώ", "ω").replace("ί", "ι")
            if "πολλαπλοι χωροι" in v and not any(k in path for k in TOUR_SKIP) and path not in tours:
                tours.append(path)
    tok = 0
    for n, path in enumerate(tours[:MAX_TOURS]):
        url = PUBLIC_BASE + path
        if not allowed(url, note, "περιοδεία"): continue
        try:
            text = to_text(get(url))
            open(f"{OUT}/tours/{n:03d}.md", "w", encoding="utf-8").write(f"URL: {url}\n\n" + text); tok += 1
        except Exception as ex:
            note(f"ERR    περιοδεία {path}: {why_blocked(ex)}")
        time.sleep(1.5)

    note(f"Περιοδείες: {tok}/{min(len(tours), MAX_TOURS)} σελίδες κατέβηκαν")

    # Museum of the City of Volos: the "Εκθέσεις" menu lists temporary exhibitions, newest first
    os.makedirs(f"{OUT}/vmoc", exist_ok=True)
    vok = 0
    if allowed(VMOC_SITEMAP, note, "vmoc sitemap"):
        try:
            smap = to_text(get(VMOC_SITEMAP))
            if "[Εκθέσεις](" not in smap:
                raise ValueError("δεν βρέθηκε το μενού «Εκθέσεις» στον χάρτη")
            block = smap.split("[Εκθέσεις](", 1)[1].split("[Δίκτυο Μουσείων](", 1)[0]
            # links may be absolute (https://vmoc.gr/index.php/x) or relative (/index.php/x or index.php/x)
            found = re.findall(r"\]\(((?:https?://(?:www\.)?vmoc\.gr)?/?index\.php/[^\s)]+)", block)
            pages = []
            for u in found:
                u = u if u.startswith("http") else "https://vmoc.gr/" + u.lstrip("/")
                if u not in pages: pages.append(u)
            pages = pages[:VMOC_MAX]
            if not pages:
                note("ERR    vmoc: το μενού «Εκθέσεις» βρέθηκε αλλά χωρίς συνδέσμους. Αρχή του μπλοκ: " + repr(block[:200]))
            for n, url in enumerate(pages):
                if not allowed(url, note, "vmoc"): continue
                try:
                    open(f"{OUT}/vmoc/{n:02d}.md", "w", encoding="utf-8").write(f"URL: {url}\n\n" + to_text(get(url))); vok += 1
                except Exception as ex:
                    note(f"ERR    vmoc {url}: {why_blocked(ex)}")
                time.sleep(1.5)
        except Exception as ex:
            note(f"ERR    vmoc sitemap: {why_blocked(ex)}")
    note(f"Μουσείο Πόλης: {vok} σελίδες εκθέσεων κατέβηκαν")

    # Volos libraries (diki.gr): same CMS; the "Εκδηλώσεις" menu (Menu_News) lists events, newest first
    os.makedirs(f"{OUT}/diki", exist_ok=True)
    dok = 0
    if allowed(DIKI_SITEMAP, note, "diki sitemap"):
        try:
            smap = to_text(get(DIKI_SITEMAP))
            m = re.search(r"\[Εκδηλώσεις\]\([^)]*Menu_News[^)]*\)(.*?)(?:Αρχείο Εκδηλώσεων|\[Περισσότερα\])", smap, re.S)
            if not m: raise ValueError("δεν βρέθηκε το μενού «Εκδηλώσεις» (Menu_News)")
            pages = []
            for u in re.findall(r"\]\(((?:https?://(?:www\.)?diki\.gr)?/?index\.php/[^\s)]+)", m.group(1)):
                u = u if u.startswith("http") else "http://www.diki.gr/" + u.lstrip("/")
                if u not in pages: pages.append(u)
            if not pages: note("ERR    diki: μενού χωρίς συνδέσμους: " + repr(m.group(1)[:200]))
            for n, url in enumerate(pages[:DIKI_MAX]):
                if not allowed(url, note, "diki"): continue
                try:
                    open(f"{OUT}/diki/{n:02d}.md", "w", encoding="utf-8").write(f"URL: {url}\n\n" + to_text(get(url))); dok += 1
                except Exception as ex:
                    note(f"ERR    diki {url}: {why_blocked(ex)}")
                time.sleep(1.5)
        except Exception as ex:
            note(f"ERR    diki sitemap: {why_blocked(ex)}")
    note(f"Βιβλιοθήκες Βόλου: {dok} σελίδες εκδηλώσεων κατέβηκαν")

    # Public stores (events.public.gr): the list is filled by JavaScript, so links are gathered from
    # the list HTML (if any), the sitemap (if any) and public_events_urls.txt; each event offers an .ics file
    os.makedirs(f"{OUT}/public_events", exist_ok=True)
    links, found_by = [], {}
    def add(path, how):
        if path not in links: links.append(path); found_by[how] = found_by.get(how, 0) + 1
    for how, url in (("λίστα", PEV_LIST), ("sitemap", PEV_SITEMAP)):
        if not allowed(url, note, f"public events {how}"): continue
        try:
            for path in PEV_LINK.findall(get(url)):
                if not path.startswith(("images/", "css/", "js/")): add(path, how)
        except Exception as ex:
            note(f"INFO   public events {how}: {why_blocked(ex)}")
        time.sleep(1.5)
    try:
        for line in open(f"{HERE}/public_events_urls.txt", encoding="utf-8"):
            m = PEV_LINK.search(line.strip())
            if m and not line.lstrip().startswith("#"): add(m.group(1), "αρχείο")
    except FileNotFoundError:
        pass
    pok = 0
    for n, path in enumerate(links[:PEV_MAX]):
        url = f"https://events.public.gr/{path}?download=ics"
        if not allowed(url, note, "public event"): continue
        try:
            body = get(url)
            if "BEGIN:VEVENT" in body:
                open(f"{OUT}/public_events/{n:02d}.ics", "w", encoding="utf-8").write(f"X-SOURCE-URL:https://events.public.gr/{path}\n" + body); pok += 1
        except Exception as ex:
            note(f"ERR    public event {path}: {why_blocked(ex)}")
        time.sleep(1.5)
    note(f"Public Events: {pok} εκδηλώσεις (.ics) από {len(links)} συνδέσμους — βρέθηκαν από: {found_by or 'πουθενά'}")
    note(f"Κύριες σελίδες: {ok}/{len(PAGES)} κατέβηκαν")
    log.close()
    if ok < len(PAGES) // 2:
        print("Απέτυχαν οι περισσότερες λήψεις — διακοπή, η σελίδα δεν ενημερώνεται.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
