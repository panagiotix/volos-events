# Τι γίνεται στον Βόλο και στο Πήλιο

Αυτόματος συλλέκτης εκδηλώσεων από δομημένες πηγές, χωρίς LLM.
Τρέχει κάθε πρωί με GitHub Actions και δημοσιεύεται στο GitHub Pages.

- `fetch.py` — κατεβάζει τις πηγές (σέβεται το robots.txt) στο `live/`
- `aggregator.py` — parsers, φίλτρο Βόλος/Πήλιο, ένωση διπλοεγγραφών, `log.md`
- `feeds.py` — iCal και RSS από εγκεκριμένες υποβολές (`submissions.json`)
- `overrides.json` — χειροκίνητες αποφάσεις (π.χ. Rally Κένταυρος → Πήλιο)
- `build_site.py` — φτιάχνει το `_site/index.html` και το `events.ics`

Τοπική δοκιμή με τα αποθηκευμένα στιγμιότυπα:
    SNAPSHOT_DATE=2026-09-29 python build_site.py

Ζωντανά:
    pip install -r requirements.txt && python fetch.py && LIVE=1 python build_site.py
