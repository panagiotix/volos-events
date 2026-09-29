"""
Daily download of the structured sources → live/<file>, in the same text form
the parsers read (HTML converted to Markdown). Respects robots.txt.
Sources whose snapshots were normalised by hand (More/Public listings, Mood,
tour pages, AOGOC) still need a dedicated HTML parser: until then they report
0 records in the log, which is the signal to write it.
"""
import os, re, sys, time, urllib.request, urllib.robotparser
from urllib.parse import urlparse
from markdownify import markdownify

UA = "VolosEventsBot/1.0 (+https://github.com/)"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/live"

# file the parser expects  →  page to download
PAGES = {
    "artandlife_volos.md": "https://www.artandlife.gr/volos/events",
    "cineportal_volos.md": "https://cineportal.gr/bolos/",
    "thessaly_app.md":     "https://app.thessaly.gov.gr/TourismEventsApp",
    "uth_events.md":       "https://www.uth.gr/events",
    "ticketservices.md":   "https://www.ticketservices.gr/",
    "fever_volos.md":      "https://feverup.com/el/volos-ellada",
    "zagora_calendar.md":  "https://www.dimos-zagoras-mouresiou.gr/fullcalendar",
}
_robots = {}

def allowed(url):
    host = urlparse(url)._replace(path="", query="", fragment="").geturl()
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
        try: rp.read()
        except Exception: rp = None
        _robots[host] = rp
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(UA, url)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el-GR,el;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")

def to_text(html):
    md = markdownify(html, heading_style="ATX", strip=["script", "style"])
    # one line per link text, as the parsers expect "[text](url)"
    md = re.sub(r"\[([^\]]*)\]\(", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)).strip() + "](", md)
    return re.sub(r"\n{3,}", "\n\n", md)

def main():
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for fname, url in PAGES.items():
        if not allowed(url):
            print(f"robots.txt: {url} — παραλείπεται"); continue
        try:
            text = to_text(get(url))
            open(f"{OUT}/{fname}", "w", encoding="utf-8").write(text)
            print(f"OK  {fname:24} {len(text):>7} χαρακτήρες  ← {url}"); ok += 1
        except Exception as ex:
            print(f"ERR {fname:24} {type(ex).__name__}: {ex}")
        time.sleep(2)                                    # polite pause between sites
    print(f"{ok}/{len(PAGES)} σελίδες κατέβηκαν")
    return 0

if __name__ == "__main__":
    sys.exit(main())
