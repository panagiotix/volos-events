"""
ALL-CAPS Greek titles → normal Greek with accents, without guessing.

Greek capitals carry no accents, so "ΤΡΑΓΟΥΔΙΑ" cannot be lowercased correctly by rule.
We learn accented spellings from mixed-case text we already download (event descriptions,
other listings), plus an optional Hunspell el_GR word list and a hand-kept accents.txt.
A title is converted only when every word is known (or is a one-syllable word, which
takes no accent in modern Greek). Otherwise it stays as published and the unknown words
are reported in the log, so they can be added to accents.txt.
"""
import os, re, unicodedata
from collections import Counter, defaultdict

GREEK_WORD = re.compile(r"[Α-Ωα-ωΆ-Ώά-ώΪΫϊϋΐΰ]+")
LATIN_WORD = re.compile(r"[A-Za-z]+")

def strip_acc(w):
    return "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")

def key(w):
    return strip_acc(w).lower().replace("ς", "σ")

_DIPH = re.compile(r"(αι|ει|οι|ου|υι|αυ|ευ|ηυ)")
NO_ACCENT = {"για", "μια", "πια", "δυο", "ποιος", "ποια", "ποιο", "ποιοι", "ποιους", "ποιων", "τρια", "νια"}

NO_ACCENT_KEYS = {x.replace("ς", "σ") for x in NO_ACCENT}

def syllables(w):
    if key(w) in NO_ACCENT_KEYS: return 1
    w = key(w)
    w = _DIPH.sub("A", w)
    return len(re.findall(r"[αεηιουωA]", w))

class Lexicon:
    def __init__(self):
        self.forms = defaultdict(Counter)   # key -> Counter(lowercase accented form)
        self.caps = Counter()               # key -> times seen capitalised mid-sentence
        self.seen = Counter()
        self.dict_proper = set()            # capitalised in the dictionary / accents.txt
        self.dict_common = set()            # lowercase in the dictionary / accents.txt
        self.lower_seen = Counter()         # key -> times written in lowercase mid-sentence
        self.override = {}                  # accents.txt: key -> exact form (final authority)

    def learn_text(self, text):
        for sent in re.split(r"(?<=[.!;:·\n])\s+", text):
            for i, m in enumerate(GREEK_WORD.finditer(sent)):
                w = m.group(0)
                if w.isupper() and len(w) > 1: continue          # caps teach us nothing about accents
                k = key(w)
                if len(k) < 2: continue
                low = w.lower()
                if low.endswith("σ"): low = low[:-1] + "ς"
                has_acc = low != strip_acc(low)
                if not has_acc and syllables(w) > 1: continue    # unaccented polysyllable: typo/caps
                self.forms[k][low] += 1
                self.seen[k] += 1
                if i > 0 and w[0].isupper(): self.caps[k] += 1
                if i > 0 and w[0].islower(): self.lower_seen[k] += 1

    def learn_words(self, words, weight=5):
        for w in words:
            w = w.strip()
            if not w or w.startswith("#") or not GREEK_WORD.fullmatch(w): continue
            k = key(w)
            self.forms[k][w.lower()] += weight
            (self.dict_proper if w[0].isupper() else self.dict_common).add(k)

    def word(self, w, first):
        k = key(w)
        if k in self.override:
            f = self.override[k]
            return (f[0].upper() + f[1:]) if first else f
        if k in self.forms:
            top = self.forms[k].most_common(2)
            if len(top) > 1 and top[1][1] >= 0.25 * top[0][1]:
                return None                                   # two accentuations seen (λάμπρος/λαμπρός): don't guess
            low = top[0][0]
            if k in self.dict_proper and k not in self.dict_common: proper = True
            elif k in self.dict_common: proper = False
            elif re.search(r"(ικ|ιν|ιακ|ειν)(οσ|η|ησ|ο|οι|εσ|ων|ου|ουσ|α)$", k): proper = False   # adjectives
            else: proper = self.lower_seen[k] == 0 and self.seen[k] >= 3 and self.caps[k] / self.seen[k] > 0.9
            return (low[0].upper() + low[1:]) if (first or proper) else low
        if syllables(w) <= 1:
            low = w.lower()
            if low.endswith("σ"): low = low[:-1] + "ς"
            return (low[0].upper() + low[1:]) if first else low
        return None

def shouty(t):
    letters = [c for c in t if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7

def recase(title, lex, acronyms=()):
    """Returns (new_title, unknown_words). new_title == title when anything is unknown."""
    if not shouty(title): return title, []
    unknown, out, pos, first = [], [], 0, True
    for m in re.finditer(r"[^\W\d_]+", title):
        gap = title[pos:m.start()]
        out.append(gap)
        if re.search(r"[«\"“:–—]|\s-\s|\(", gap): first = True      # subtitle / quote starts a new phrase
        w = m.group(0)
        if gap[-1:].isdigit():                                    # ordinals: 7Η → 7η, 4ο, 6ος
            out.append(w.lower())
        elif w in acronyms:
            out.append(w)
        elif LATIN_WORD.fullmatch(w):
            out.append(w if (len(w) <= 3 or not w.isupper()) else w.capitalize())
        else:
            r = lex.word(w, first)
            if r is None: unknown.append(w); out.append(w)
            else: out.append(r)
        first = False
        pos = m.end()
    out.append(title[pos:])
    if unknown: return title, unknown
    return "".join(out), []

def build_lexicon(text_dirs, extra_files=(), overrides_file=None):
    lex = Lexicon()
    if overrides_file and os.path.exists(overrides_file):
        for line in open(overrides_file, encoding="utf-8"):
            w = line.strip()
            if w and not w.startswith("#") and GREEK_WORD.fullmatch(w):
                lex.override[key(w)] = w
    for d in text_dirs:
        if not os.path.isdir(d): continue
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.endswith((".md", ".txt")):
                    try: lex.learn_text(open(os.path.join(root, fn), encoding="utf-8").read())
                    except Exception: pass
    for f in extra_files:                   # Hunspell .dic (word/FLAGS per line)
        if not os.path.exists(f): continue
        enc = "utf-8"
        aff = f[:-4] + ".aff"
        if os.path.exists(aff):             # the .aff declares the .dic encoding (el_GR is often ISO-8859-7)
            m = re.search(rb"^SET\s+(\S+)", open(aff, "rb").read(), re.M)
            if m: enc = m.group(1).decode().lower().replace("iso8859", "iso8859_").replace("__", "_")
        try: words = open(f, encoding=enc, errors="replace").read().split()
        except LookupError: words = open(f, encoding="utf-8", errors="replace").read().split()
        lex.learn_words((w.split("/")[0] for w in words), weight=3)
    return lex
