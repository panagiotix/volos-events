"""
Supabase as the editorial layer (no extra libraries: plain HTTPS to the REST API).

  push_events(events)  collected + merged events → table "events" (upsert; your
                       status/overrides are never touched)
  pull_public()        public_events (hidden removed, overrides applied, approved
                       submissions included) → the page's event format
  approved_feeds()     approved iCal/RSS sources → read by the pipeline every run

Needs SUPABASE_URL and SUPABASE_SERVICE_KEY (GitHub Secrets). Without them every
function is a no-op and the site is built exactly as before.
"""
import hashlib, json, os, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def enabled():
    return bool(URL and KEY)

def key_role():
    """Which kind of key is in SUPABASE_SERVICE_KEY — for the log only."""
    import base64
    if KEY.startswith("sb_secret_"): return "νέου τύπου secret (sb_secret_…) — χρησιμοποίησε το legacy service_role"
    if KEY.startswith("sb_publishable_"): return "δημόσιο νέου τύπου (sb_publishable_…) — λάθος κλειδί"
    try:
        payload = KEY.split(".")[1]; payload += "=" * (-len(payload) % 4)
        role = json.loads(base64.urlsafe_b64decode(payload)).get("role", "?")
        return {"service_role": "service_role (σωστό)", "anon": "anon — ΛΑΘΟΣ: εδώ χρειάζεται το service_role"}.get(role, role)
    except Exception:
        return "μη αναγνωρίσιμο κλειδί"

def _req(method, path, body=None, prefer=None):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    if prefer: h["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:            # keep Supabase's own explanation for the log
        body = e.read().decode("utf-8", "replace")[:300]
        table = path.split("?")[0]
        raise RuntimeError(f"HTTP {e.code} στο «{table}»: {body}") from None

# ---------------------------------------------------------------- Athens time (no tz database needed)
def _last_sunday(y, m):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)

def athens_offset_utc(dt_utc):
    """EU rule: summer time from last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC."""
    y = dt_utc.year
    start = datetime.combine(_last_sunday(y, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(y, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return 3 if start <= dt_utc < end else 2

def local_to_utc_iso(day, hhmm):
    naive = datetime.fromisoformat(f"{day}T{hhmm or '00:00'}")
    guess = naive.replace(tzinfo=timezone.utc) - timedelta(hours=3)
    off = athens_offset_utc(guess)
    return (naive - timedelta(hours=off)).replace(tzinfo=timezone.utc).isoformat()

def utc_to_local(ts):
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    loc = dt + timedelta(hours=athens_offset_utc(dt))
    return loc.date().isoformat(), loc.strftime("%H:%M")

# ---------------------------------------------------------------- identity of a merged event
def stable_id(e):
    """Must survive re-casing (ΠΛΕΣΣΑΣ → Πλέσσας), punctuation and new sources joining:
    the title's words without accents/case + the start day."""
    import re, unicodedata
    t = unicodedata.normalize("NFD", e["title"].lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("ς", "σ")
    words = " ".join(re.findall(r"\w{3,}", t))
    return hashlib.sha1(f"{words}|{e.get('start') or ''}".encode("utf-8")).hexdigest()[:16]

_AGG = None
def _aggregator_source_id():
    global _AGG
    if _AGG: return _AGG
    rows = _req("GET", "sources?kind=eq.aggregator&select=id&limit=1")
    if not rows:
        rows = _req("POST", "sources", {"name": "VOLTA pipeline", "kind": "aggregator"}, "return=representation")
    _AGG = rows[0]["id"]
    return _AGG

def to_row(e, src_id):
    return {
        "source_id": src_id, "external_id": stable_id(e),
        "title": e["title"], "venue": e.get("venue") or None, "region": e.get("area"),
        "category": e.get("category"), "url": (e["sources"][0]["url"] if e["sources"] else None),
        "starts_at": local_to_utc_iso(e["start"], e.get("time")),
        "ends_at": local_to_utc_iso(e["end"], "23:59") if e.get("end") else None,
        "all_day": not e.get("time"), "price": e.get("price"), "hall": e.get("hall"),
        "sources": e["sources"], "collected_at": datetime.now(timezone.utc).isoformat(),
    }

def push_events(events):
    """Upsert only the collected columns; status and overrides (your decisions) stay as they are."""
    if not enabled(): return 0
    src = _aggregator_source_id()
    rows = [to_row(e, src) for e in events if e.get("start") and not e.get("running")]
    seen, uniq = set(), []
    for r in rows:                                  # one row per id within a batch (Postgres requires it)
        if r["external_id"] not in seen: seen.add(r["external_id"]); uniq.append(r)
    for i in range(0, len(uniq), 200):
        _req("POST", "events?on_conflict=source_id,external_id", uniq[i:i + 200],
             "resolution=merge-duplicates,return=minimal")
    return len(uniq)

def from_row(r):
    start, t = utc_to_local(r["starts_at"])
    end = utc_to_local(r["ends_at"])[0] if r.get("ends_at") else None
    return {
        "id": f"db{r['id']}", "title": r["title"], "start": start, "end": end if end != start else None,
        "time": None if r.get("all_day") else t, "venue": r.get("venue") or "", "area": r.get("region") or "volos",
        "category": r.get("category") or "Άλλο", "price": r.get("price"), "hall": r.get("hall"),
        "sources": r.get("sources") or ([{"source": "VOLTA", "url": r["url"]}] if r.get("url") else []),
        "running": False, "past": False, "method": "parser", "note": None,
    }

PULL_STATS = {"submitted": 0, "own": 0, "total": 0}

def pull_public(today):
    """Current and future published events, with your hide/override decisions applied."""
    if not enabled(): return None
    # "Z" instead of "+00:00": a "+" inside a URL is read as a space and the filter would fail
    since = local_to_utc_iso((today - timedelta(days=1)).isoformat(), "00:00").replace("+00:00", "Z")
    rows = _req("GET", "public_events?select=*&or=(starts_at.gte.{0},ends_at.gte.{0})&order=starts_at&limit=2000".format(since))
    out = []
    PULL_STATS.update(submitted=0, own=0, total=0)
    for r in rows or []:
        e = from_row(r)
        if (e["end"] or e["start"]) < today.isoformat(): continue
        out.append(e)
        ext = str(r.get("external_id") or "")
        PULL_STATS["total"] += 1
        if ext.startswith("sub-"): PULL_STATS["submitted"] += 1
        if ext.startswith("admin-"): PULL_STATS["own"] += 1
    return out

def approved_feeds():
    """Approved, active iCal/RSS/website sources from submissions."""
    if not enabled(): return []
    rows = _req("GET", "sources?active=eq.true&kind=in.(ical,rss,html)&select=name,kind,url,region,category")
    return [{"kind": "site" if r["kind"] == "html" else r["kind"], "url": r["url"], "organizer": r["name"],
             "area": r.get("region") or "volos", "category": r.get("category")} for r in rows or [] if r.get("url")]
