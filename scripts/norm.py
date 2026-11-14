"""Спільна нормалізація назв населених пунктів, вулиць і номерів будинків."""
import re

# ---------- нормалізація ----------
LAT2CYR = str.maketrans("ABCEHIKMOPTXaceiopxy", "АВСЕНІКМОРТХасеіорху")
TYPES = [
    ("prov", r"провулок|пров|пер|переулок|пр-к|прк"),
    ("prosp", r"проспект|просп|пр-т"),
    ("pl", r"площа|пл|майдан|м-н"),
    ("blv", r"бульвар|б-р|бул|б"),
    ("shose", r"шосе"),
    ("proizd", r"проїзд|пр-д"),
    ("uzviz", r"узвіз"),
    ("tupyk", r"тупик|туп"),
    ("nab", r"набережна|наб"),
    ("vul", r"вулиця|вул|ул|улица"),
]
TYPE_RE = [(t, re.compile(r"(?<![\w-])(?:%s)(?:\.|(?![\w-]))" % p, re.I)) for t, p in TYPES]

def street_key(s):
    """-> (тип, нормалізована назва з відсортованими словами)"""
    s = s.translate(LAT2CYR).lower().replace("ё", "е")
    s = re.sub(r"[ʼ'’`\"«»]", "", s)
    s = re.sub(r"(\d+)\s*-?\s*(?:й|ий|ій|я|а|го|ша|га|тя|та|ти)(?![а-яіїєґ])", r"\1 ", s)
    typ = None
    for t, rx in TYPE_RE:
        if rx.search(s):
            s = rx.sub(" ", s)
            if typ is None or typ == "vul": typ = t
    s = re.sub(r"(?<![\w-])(?:мікрорайон|мкрн|мкр-н|мкр|масив|квартал|кв-л|урочище|ур|територія|містечко)(?:\.|(?![\w-]))", " ", s)
    s = re.sub(r"[.,;()№]", " ", s)
    toks = [t for t in s.replace("-", " ").split() if len(t) > 1 or t.isdigit()]
    return typ or "vul", " ".join(sorted(toks))

def house_key(h):
    h = h.translate(LAT2CYR).upper()
    h = re.sub(r"[\s]", "", h)
    h = re.sub(r"^(\d+)-([А-ЯІЇЄҐ])$", r"\1\2", h)
    h = re.sub(r"(?:КОРП(?:УС)?\.?|К\.)(\d+)", r"/\1", h)
    return h

def place_key(s):
    s = re.sub(r"^(місто|м\.|село|с\.|селище|смт\.?|с/рада|хутір)\s*", "", s.strip(), flags=re.I)
    s = s.lower().replace("ё", "е")
    return re.sub(r"[ʼ'’`\"\s-]", "", s)

