"""The people named as responsible for register entries.

Every name and email saved on an entry is remembered, so the form can offer
them back as someone types, and can notice when a new name is almost exactly
an existing one ("Susna" for "Susana") — the kind of slip that would otherwise
split one person into two in every filter of the sheet.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from ..models import Responsable
from ..schemas.documents import ResponsableRead, ResponsableSearch, clean_name

SearchField = Literal["nom", "email"]
MATCH_LIMIT = 8


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", clean_name(text).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def remember(session: Session, nom: str, email: str) -> None:
    """Record a name/email pair as used. Does not commit."""
    nom = clean_name(nom or "")
    email = (email or "").strip().lower()
    if not nom and not email:
        return
    key = fold(nom)
    row = (
        session.query(Responsable)
        .filter(Responsable.nom_key == key, Responsable.email == email)
        .first()
    )
    if row is None:
        session.add(Responsable(nom=nom, nom_key=key, email=email, uses=1))
        return
    row.nom = nom or row.nom  # the latest spelling of the same folded name
    row.uses += 1
    row.last_used_at = datetime.now(UTC)


def search(session: Session, field: SearchField, query: str) -> ResponsableSearch:
    rows = (
        session.query(Responsable)
        .order_by(Responsable.uses.desc(), Responsable.last_used_at.desc())
        .all()
    )
    people = _distinct(rows, field)
    needle = fold(query)
    value = (lambda p: fold(p.nom)) if field == "nom" else (lambda p: p.email)

    if needle:
        prefix = [p for p in people if value(p).startswith(needle) or f" {needle}" in value(p)]
        inner = [p for p in people if needle in value(p) and p not in prefix]
        matches = prefix + inner
    else:
        matches = people
    exact = any(value(p) == needle for p in people)
    suggestion = None if exact or not needle else _near_miss(people, field, needle)
    return ResponsableSearch(matches=matches[:MATCH_LIMIT], suggestion=suggestion)


def _distinct(rows: list[Responsable], field: SearchField) -> list[ResponsableRead]:
    """One entry per name (with its most used email), or one per email."""
    seen: set[str] = set()
    people: list[ResponsableRead] = []
    for row in rows:
        key = row.nom_key if field == "nom" else row.email
        if not key or key in seen:
            continue
        seen.add(key)
        # A name's email: its most used pair that has one.
        email = row.email or next(
            (r.email for r in rows if r.nom_key == row.nom_key and r.email), ""
        )
        people.append(ResponsableRead(nom=row.nom, email=email))
    return people


def _near_miss(people: list[ResponsableRead], field: SearchField, needle: str) -> ResponsableRead | None:
    """The known person ``needle`` is most likely a misspelling of, if any.

    Deliberately strict — only "very obvious" slips: one edit for words of 4–8
    letters, two from 9. Short words are never corrected (Ana, Eva and Ona are
    all real names). A single typed word is also compared with first names, so
    "Susna" finds "Susana Pérez".
    """
    if field == "email":
        local, _, domain = needle.partition("@")
        candidates = [
            (p.email.partition("@")[0], p) for p in people if not domain or p.email.endswith("@" + domain)
        ]
        needle = local
    else:
        candidates = [(fold(p.nom), p) for p in people]
        if " " not in needle:
            candidates += [(fold(p.nom).split(" ")[0], p) for p in people if " " in p.nom]

    allowed = _allowed_edits(needle)
    if not allowed:
        return None
    best: tuple[int, ResponsableRead] | None = None
    for text, person in candidates:
        if not text or text == needle or abs(len(text) - len(needle)) > allowed:
            continue
        distance = edit_distance(needle, text)
        if distance <= allowed and (best is None or distance < best[0]):
            best = (distance, person)
    return best[1] if best else None


def _allowed_edits(text: str) -> int:
    length = len(text)
    if length < 4:
        return 0
    return 1 if length < 9 else 2


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance counting a swap of two neighbours as one edit."""
    previous2: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            )
            if previous2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                current[j] = min(current[j], previous2[j - 2] + 1)
        previous2, previous = previous, current
    return previous[-1]
