"""Writing parsed statements to the database, idempotently.

A movement already known (same fingerprint) is counted as a duplicate rather
than added, so a statement can be dropped twice, or two overlapping periods
one after the other, without doubling anything. The caixeta is the exception
that proves the rule: its rows are edited in place in the sheet, so a known
row is *updated* — and any proposal made for its old values is dropped.
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.orm import Session

from ...models import BankMovement, PaymentMatch, StatementImport, WorkspaceSetting
from . import INTERNAL, PAYMENT, SOURCE_CAIXETA, SOURCE_PREPAID, ParsedStatement

#: Settings field → ``COMPTES`` label, for the three CaixaBank accounts.
ACCOUNT_FIELDS = {
    "iban_general": "General",
    "iban_material": "Material i Sortides",
    "iban_menjador": "Menjador",
}

_MOVEMENT_FIELDS = (
    "tipus", "categoria", "data", "data_valor", "concepte", "mes_dades", "import_value",
    "saldo", "num_factura_hint", "cif_hint", "iban_hint", "external_ref", "raw",
)


#: ``COMPTES`` label → the prefix of its movements' internal codes.
CODE_PREFIXES = {
    "Caixeta": "CIX",
    "Targeta Prepagament": "TP",
    "Material i Sortides": "M",
    "Menjador": "MEN",
    "General": "G",
}


def _code_number(codi: str) -> int:
    match = re.search(r"_(\d+)$", codi)
    return int(match.group(1)) if match else 0


def assign_codes(session: Session) -> int:
    """Give every movement without one its internal code; returns how many changed.

    Each account counts on from its highest code, oldest line first, so a code
    never changes once given — a later statement for an earlier month simply
    gets the next numbers. A caixeta line is the exception: its code *is* the
    sheet's ``Cix_NNN``, and follows it if the sheet renumbers.
    """
    session.flush()
    changed = 0
    for movement in session.query(BankMovement).filter(
        BankMovement.compte == "Caixeta", BankMovement.external_ref != ""
    ):
        if movement.codi != movement.external_ref:
            movement.codi = movement.external_ref
            changed += 1
    session.flush()
    pending = (
        session.query(BankMovement)
        .filter(BankMovement.codi == "")
        .order_by(BankMovement.data.is_(None), BankMovement.data, BankMovement.id)
        .all()
    )
    if not pending:
        return changed
    last: dict[str, int] = {}
    for compte, codi in session.query(BankMovement.compte, BankMovement.codi).filter(BankMovement.codi != ""):
        last[compte] = max(last.get(compte, 0), _code_number(codi))
    for movement in pending:
        prefix = CODE_PREFIXES.get(movement.compte) or (movement.compte[:3].upper() or "MOV")
        last[movement.compte] = last.get(movement.compte, 0) + 1
        movement.codi = f"{prefix}_{last[movement.compte]:03d}"
        changed += 1
    session.flush()
    return changed


def _compact(iban: str) -> str:
    return re.sub(r"\s", "", iban or "").upper()


def account_for_iban(workspace: WorkspaceSetting, iban: str) -> str | None:
    wanted = _compact(iban)
    if not wanted:
        return None
    for field, label in ACCOUNT_FIELDS.items():
        if _compact(getattr(workspace, field, "")) == wanted:
            return label
    return None


def remember_iban(workspace: WorkspaceSetting, compte: str, iban: str) -> None:
    """Save the IBAN a person just told us belongs to ``compte``."""
    for field, label in ACCOUNT_FIELDS.items():
        if label == compte and iban:
            setattr(workspace, field, iban)


def _initial_status(categoria: str) -> str:
    return "unmatched" if categoria == PAYMENT else "not_applicable"


def save(
    session: Session,
    parsed: ParsedStatement,
    *,
    compte: str,
    file_name: str = "",
    stored_path: str | None = None,
    user_id: int | None = None,
    statement: StatementImport | None = None,
) -> StatementImport:
    """Store a statement's movements. Pass ``statement`` to add to an existing one."""
    period_from, period_to = parsed.period
    if statement is None:
        statement = StatementImport(
            source=parsed.source,
            compte=compte,
            account_iban=parsed.account_iban,
            file_name=file_name,
            stored_path=stored_path,
            created_by_id=user_id,
        )
        session.add(statement)
        session.flush()
    statement.period_from = period_from
    statement.period_to = period_to
    statement.status = "done"
    statement.error_message = None

    fingerprints = [m.fingerprint for m in parsed.movements]
    known = {
        movement.fingerprint: movement
        for movement in session.query(BankMovement).filter(BankMovement.fingerprint.in_(fingerprints))
    }
    new = duplicate = 0
    seen: set[str] = set()
    for item in parsed.movements:
        fingerprint = item.fingerprint
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        existing = known.get(fingerprint)
        if existing is None:
            session.add(
                BankMovement(
                    import_id=statement.id,
                    fingerprint=fingerprint,
                    source=parsed.source,
                    compte=compte,
                    match_status=_initial_status(item.categoria),
                    **{name: getattr(item, name) for name in _MOVEMENT_FIELDS},
                )
            )
            new += 1
            continue
        duplicate += 1
        if parsed.source == SOURCE_CAIXETA:
            _refresh(session, existing, item)

    if parsed.source == SOURCE_CAIXETA:
        # A row deleted from the sheet is gone; keep it only if someone confirmed it.
        for movement in statement.movements:
            if movement.fingerprint not in seen and movement.match_status != "confirmed":
                session.delete(movement)
        total = len(seen)
    else:
        total = len(parsed.movements)
    statement.rows_total = total
    statement.rows_new = new
    statement.rows_duplicate = duplicate
    session.flush()
    assign_codes(session)
    link_internal_transfers(session)
    session.commit()
    session.refresh(statement)
    return statement


def _refresh(session: Session, movement: BankMovement, item) -> None:
    changed = any(getattr(movement, name) != getattr(item, name) for name in _MOVEMENT_FIELDS if name != "raw")
    if not changed:
        return
    for name in _MOVEMENT_FIELDS:
        setattr(movement, name, getattr(item, name))
    if movement.match_status == "confirmed":
        return  # a person's decision outlives a typo fix in the sheet
    for match in session.query(PaymentMatch).filter(
        PaymentMatch.movement_id == movement.id, PaymentMatch.status != "confirmed"
    ).all():
        session.delete(match)
    movement.match_status = _initial_status(movement.categoria)


def link_internal_transfers(session: Session) -> int:
    """Pair each prepaid top-up with the account charge that paid for it.

    ``RECARGA TARJETA PREPAGO +400`` on the card and ``CARREGA.TARG.PREPAG −400``
    on an account are one movement of money seen from both ends.
    """
    pending = (
        session.query(BankMovement)
        .filter(BankMovement.categoria == INTERNAL, BankMovement.linked_movement_id.is_(None))
        .all()
    )
    top_ups = [m for m in pending if m.source == SOURCE_PREPAID and m.import_value > 0]
    charges = [m for m in pending if m.source != SOURCE_PREPAID and m.import_value < 0]
    linked = 0
    for top_up in top_ups:
        match = next(
            (
                charge
                for charge in charges
                if charge.linked_movement_id is None
                and abs(charge.import_value + top_up.import_value) < 0.005
                and charge.data and top_up.data
                and abs(charge.data - top_up.data) <= timedelta(days=4)
            ),
            None,
        )
        if match is None:
            continue
        top_up.linked_movement_id = match.id
        match.linked_movement_id = top_up.id
        linked += 1
    return linked
