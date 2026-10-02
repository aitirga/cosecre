"""Deterministic clean-up of what the model reads off a document.

The model is told how to format things, but formatting is cheap to enforce and
expensive to trust: a supplier printed in capitals comes back in capitals often
enough that the sheet would never look consistent. Everything here is pure, so
the same rules apply to fresh extractions and to rows migrated from old tabs.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# ── Dates ────────────────────────────────────────────────────────────────────

#: Google Sheets counts days from 30 December 1899.
_SHEETS_EPOCH = date(1899, 12, 30)

_DAY_FIRST = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\b")


def parse_date(value: object) -> date | None:
    """Read a date the way a Catalan or Spanish document writes it.

    Day first, always: ``6/2/2026`` is the 6th of February. Accepts a trailing
    time (tickets print one), two-digit years, ISO strings, ``date`` objects and
    Sheets serial numbers. Anything else is ``None`` rather than a guess.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # A serial a person could plausibly mean: 1990–2100.
        if 32874 <= value <= 73051:
            return _SHEETS_EPOCH + timedelta(days=int(value))
        return None
    text = str(value).strip()
    if not text:
        return None
    if match := _ISO.match(text):
        year, month, day = (int(part) for part in match.groups())
    elif match := _DAY_FIRST.match(text):
        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_date(value: date | None) -> str:
    """``dd/mm/yyyy`` — the only format the people using this want to see."""
    return value.strftime("%d/%m/%Y") if value else ""


def to_sheets_serial(value: date) -> int:
    return (value - _SHEETS_EPOCH).days


# ── Amounts ──────────────────────────────────────────────────────────────────


def parse_amount(value: object) -> float | None:
    """Convert a currency string or number to a plain float.

    Handles European (1.234,56) and US (1,234.56) formats, and strips common
    currency symbols. Models return amounts in whichever convention the source
    document used, so this normalises at the boundary.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[€$£¥\s]|EUR", "", str(value), flags=re.IGNORECASE).strip()
    if not s:
        return None
    if "," in s and "." in s:
        # Whichever comes last is the decimal separator
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # Treat comma as decimal separator only when ≤2 digits follow it
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ── Casing ───────────────────────────────────────────────────────────────────

#: Words that stay lower case inside a name: "Institut d'Estudis Catalans",
#: "Hospitalet de Llobregat".
_PARTICLES = {
    "de", "del", "dels", "la", "les", "el", "els", "i", "y", "e", "a", "al", "als",
    "per", "en", "amb", "da", "do", "das", "dos", "the", "of", "and", "las", "los",
}
#: Company forms and other acronyms that stay upper case.
_UPPER = {
    "sl", "sa", "slu", "sau", "sll", "scp", "sccl", "scoop", "sc", "cb", "ute", "sat",
    "ltd", "llc", "inc", "gmbh", "bv", "nv", "srl", "spa", "iva", "nif", "cif", "eso",
    "bcn", "ue", "eu", "uk", "usa", "tv", "pc", "it",
}


def _letters(text: str) -> str:
    return "".join(ch for ch in text if ch.isalpha())


def is_uniform_case(text: str) -> bool:
    """True when a text is all capitals or all lower case.

    Mixed case means a person (or the document) already chose the casing on
    purpose — "McDonald's", "bonÀrea" — and rewriting it would lose that.
    """
    letters = _letters(text)
    if len(letters) < 2:
        return False
    return letters.isupper() or letters.islower()


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def _name_word(word: str, first: bool) -> str:
    bare = re.sub(r"[^\w]", "", word).lower()
    if bare in _UPPER or re.fullmatch(r"(?:[a-z]\.){2,}", word.lower()):
        return word.upper()
    # l'Hospitalet, d'Estudis: the elision stays lower, the word after it does not.
    if match := re.match(r"^([ldsn])['’](.+)$", word, flags=re.IGNORECASE):
        prefix = match.group(1).upper() if first else match.group(1).lower()
        return f"{prefix}'{_cap(match.group(2))}"
    if not first and bare in _PARTICLES:
        return word.lower()
    # Hyphenated and slashed parts each get their own capital: "Sant Joan-Despí".
    return re.sub(r"[^\W\d_]+", lambda m: _cap(m.group(0)), word.lower(), count=0)


def name_case(text: str) -> str:
    """Proper-name casing for suppliers, streets and cities.

    Only applied to text that arrived in one uniform case; see
    :func:`is_uniform_case`.
    """
    if not text or not is_uniform_case(text):
        return text.strip() if text else text
    words = text.strip().split()
    return " ".join(_name_word(word, index == 0) for index, word in enumerate(words))


def sentence_case(text: str) -> str:
    """First letter up, the rest down — for descriptions in capitals."""
    if not text or not is_uniform_case(text):
        return text.strip() if text else text
    lowered = text.strip().lower()
    # Keep acronyms that would read wrong in lower case.
    lowered = re.sub(
        r"\b(" + "|".join(sorted(_UPPER, key=len, reverse=True)) + r")\b",
        lambda m: m.group(0).upper(),
        lowered,
    )
    return lowered[:1].upper() + lowered[1:]


def compact_code(text: str) -> str:
    """Tax ids are printed with stray spaces and dashes: "G 64097215" → "G64097215"."""
    return re.sub(r"[\s\-.]", "", text or "").upper()


# ── Bank accounts ────────────────────────────────────────────────────────────


def normalize_iban(text: str) -> str:
    """Group an IBAN in blocks of four, the way banks print it."""
    raw = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    if not raw:
        return ""
    return " ".join(raw[index : index + 4] for index in range(0, len(raw), 4))


def iban_is_valid(text: str) -> bool:
    """ISO 13616 mod-97 check. Catches nearly every misread digit."""
    raw = re.sub(r"\s", "", text or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", raw):
        return False
    if raw.startswith("ES") and len(raw) != 24:
        return False
    rearranged = raw[4:] + raw[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


# ── Addresses ────────────────────────────────────────────────────────────────

_POSTCODE = re.compile(r"\b(\d{5})\b")


def split_address(text: str) -> tuple[str, str, str]:
    """Best-effort ``(street and number, postcode, city)`` from one line.

    Only used for rows migrated from the old single "Adreça" column; new
    documents get the three parts from the model directly. Without a Spanish
    postcode to anchor on, the whole text stays in the street.
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip()).strip(" ,.;")
    if not cleaned:
        return "", "", ""
    match = None
    for match in _POSTCODE.finditer(cleaned):
        pass
    if match is None:
        return cleaned, "", ""
    street = cleaned[: match.start()].strip(" ,.;-")
    city = cleaned[match.end() :].strip(" ,.;-()")
    # "08033 Barcelona (Barcelona)" — the province repeats the city often enough.
    city = re.sub(r"\s*\(.*\)$", "", city).strip()
    if not city and "," in street:
        street, _, city = street.rpartition(",")
        street, city = street.strip(" ,"), city.strip(" ,")
    return street, match.group(1), city
