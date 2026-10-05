"""Every bank movement carries an internal code: one series per account."""

from __future__ import annotations

from datetime import date

from conftest import build_client

from cosecre_hub.models import BankMovement, StatementImport
from cosecre_hub.services.statements.store import assign_codes


def test_each_account_counts_its_own_series_and_codes_never_move(tmp_path):
    client, _ = build_client(tmp_path)
    with client, client.app.state.session_factory() as session:
        def add(compte: str, day: date, ref: str = "") -> BankMovement:
            statement = StatementImport(source="caixa_xls", compte=compte)
            session.add(statement)
            session.flush()
            row = BankMovement(
                import_id=statement.id, fingerprint=f"{compte}-{day}-{ref}", source="caixa_xls",
                compte=compte, data=day, import_value=-1.0, external_ref=ref,
            )
            session.add(row)
            return row

        later = add("Menjador", date(2026, 3, 1))
        earlier = add("Menjador", date(2026, 1, 1))
        card = add("Targeta Prepagament", date(2026, 2, 1))
        general = add("General", date(2026, 2, 1))
        material = add("Material i Sortides", date(2026, 2, 1))
        cash = add("Caixeta", date(2026, 2, 4), "Cix_013")
        assign_codes(session)

        assert (earlier.codi, later.codi) == ("MEN_001", "MEN_002")
        assert (card.codi, general.codi, material.codi) == ("TP_001", "G_001", "M_001")
        assert cash.codi == "Cix_013"

        # A statement for an earlier month comes in afterwards: next number, nothing renumbered.
        older = add("Menjador", date(2025, 12, 1))
        assign_codes(session)
        assert (older.codi, earlier.codi, later.codi) == ("MEN_003", "MEN_001", "MEN_002")

        # The caixeta follows its sheet.
        cash.external_ref = "Cix_014"
        assign_codes(session)
        assert cash.codi == "Cix_014"
