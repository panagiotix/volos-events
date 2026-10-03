# VOLTA — Τι γίνεται στον Βόλο και στο Πήλιο

Αυτόματος συλλέκτης εκδηλώσεων από δομημένες πηγές, χωρίς LLM.
Τρέχει δύο φορές τη μέρα με GitHub Actions και δημοσιεύεται στο GitHub Pages.
Το Supabase κρατά τις αποφάσεις του διαχειριστή (υποβολές, εγκρίσεις, διορθώσεις, αναφορές λαθών).

## Αρχεία
- `fetch.py` — κατεβάζει τις πηγές στο `live/` (σέβεται το robots.txt, επαναλαμβάνει σε αργούς servers)
- `aggregator.py` — parsers, φίλτρο Βόλος/Πήλιο, ένωση διπλοεγγραφών, `log.md`
- `feeds.py` — iCal και RSS από εγκεκριμένα feeds
- `casing.py` + `accents.txt` — τίτλοι με κεφαλαία σε κανονική γραφή (συμπλήρωσε λέξεις στο `accents.txt`)
- `supa.py` — συγχρονισμός με το Supabase (στέλνει τις εκδηλώσεις, διαβάζει πίσω τη δημοσιευμένη εκδοχή)
- `build_site.py` — φτιάχνει `_site/index.html`, `_site/admin.html`, `_site/events.ics`
- `page_template.html`, `admin_template.html` — η δημόσια σελίδα και η σελίδα διαχείρισης
- `public_events_urls.txt` — σύνδεσμοι από events.public.gr που προσθέτεις χειροκίνητα
- `overrides.json` — παλιές χειροκίνητες αποφάσεις (π.χ. Rally Κένταυρος → Πήλιο)
- `supabase/migrations/…_volta.sql` — το σχήμα της βάσης
- `assets/` — λογότυπο

## GitHub Secrets (Settings → Secrets and variables → Actions)
- `SUPABASE_URL` — https://ΚΩΔΙΚΟΣ.supabase.co
- `SUPABASE_ANON_KEY` — δημόσιο κλειδί (μπαίνει στη σελίδα)
- `SUPABASE_SERVICE_KEY` — μυστικό κλειδί (μόνο για το workflow)

Χωρίς αυτά το site χτίζεται κανονικά, απλώς χωρίς φόρμα υποβολών και διαχείριση.

## Τοπικά
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    SNAPSHOT_DATE=2026-09-29 python build_site.py      # με τα αποθηκευμένα στιγμιότυπα
    python fetch.py && LIVE=1 python build_site.py     # ζωντανά
