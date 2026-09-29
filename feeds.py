"""
Parsers for feeds that organisers submit (after admin approval). No LLM:
  - iCal (.ics): fully structured (DTSTART, SUMMARY, LOCATION, URL).
  - RSS with the Event module (ev:startdate / ev:location): structured.
  - Plain RSS: rule-based — a date written as "16 Οκτωβρίου" or "24/10" and an
    optional time "21:30" in the title or description. Items without an explicit
    event date are NOT guessed: they go to the log as "χωρίς ημερομηνία".
"""
import re, unicodedata, xml.etree.ElementTree as ET
from datetime import date

def _fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

MONTHS = {"ιανουαριου":1,"φεβρουαριου":2,"μαρτιου":3,"απριλιου":4,"μαιου":5,"ιουνιου":6,"ιουλιου":7,
          "αυγουστου":8,"σεπτεμβριου":9,"οκτωβριου":10,"νοεμβριου":11,"δεκεμβριου":12}

def _year_for(m, d, today):
    y = today.year
    return y if (date(y, m, d) - today).days > -60 else y + 1

# ---------------------------------------------------------------- iCal
def parse_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text)                    # unfold continuation lines
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in block.strip().splitlines():
            if ":" not in line: continue
            k, v = line.split(":", 1)
            f[k.split(";")[0].upper()] = (k, v.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip())
        if "DTSTART" not in f or "SUMMARY" not in f: continue
        def dt(key):
            if key not in f: return None, None
            v = f[key][1]
            d = f"{v[0:4]}-{v[4:6]}-{v[6:8]}"
            t = f"{v[9:11]}:{v[11:13]}" if "T" in v else None
            return d, t
        start, time = dt("DTSTART")
        end, _ = dt("DTEND")
        if end and "VALUE=DATE" in f.get("DTEND", ("", ""))[0]:   # all-day DTEND is exclusive
            y, m, d = map(int, end.split("-")); end = date.fromordinal(date(y, m, d).toordinal() - 1).isoformat()
        out.append({"title": f["SUMMARY"][1], "start": start, "end": end if end and end != start else None,
                    "time": time, "venue": f.get("LOCATION", ("", ""))[1], "url": f.get("URL", ("", ""))[1]})
    return out

# ---------------------------------------------------------------- RSS
EV = "{http://purl.org/rss/1.0/modules/event/}"

def _date_in_text(text, today):
    t = _fold(text)
    m = re.search(r"(\d{1,2}) (" + "|".join(MONTHS) + r")(?: (\d{4}))?", t)
    if m:
        d, mo = int(m.group(1)), MONTHS[m.group(2)]
        y = int(m.group(3)) if m.group(3) else _year_for(mo, d, today)
        return date(y, mo, d).isoformat()
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            y = m.group(3); y = (int(y) + 2000 if y and len(y) == 2 else int(y)) if y else _year_for(mo, d, today)
            return date(y, mo, d).isoformat()
    return None

def parse_rss(text, today):
    """Returns (events, undated_titles)."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    events, undated = [], []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        sd = it.findtext(EV + "startdate")
        if sd:                                                  # RSS Event module
            ed = it.findtext(EV + "enddate")
            events.append({"title": title, "start": sd[:10], "end": ed[:10] if ed else None,
                           "time": sd[11:16] if len(sd) > 11 else None,
                           "venue": it.findtext(EV + "location") or "", "url": link, "how": "ev:startdate"})
            continue
        d = _date_in_text(f"{title} {desc}", today)             # plain RSS: explicit date only
        if not d:
            undated.append(title); continue
        tm = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", f"{title} {desc}")
        events.append({"title": re.sub(r"\s*\d{1,2}/\d{1,2}(/\d{2,4})?\s*$", "", title), "start": d, "end": None,
                       "time": f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None,
                       "venue": desc.strip()[:160], "url": link, "how": "ημερομηνία στο κείμενο"})
    return events, undated
