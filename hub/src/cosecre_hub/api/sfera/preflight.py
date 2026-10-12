"""Checks a supplier invoice before it may be exported to Esfer@, and builds its payload.

Pure functions: no database and no network, so every rule can be tested alone.
The rules encode what was verified against Esfer@ formació on 2026-10-12 (see
``docs/integrations/esfera.md``):

* each line needs its cost centre — without it the portal fails server-side and
  a ``PUT`` surfaces as a generic 405 "HTTP method PUT is not supported";
* ``/factura/validate`` does not check lengths, but ``/factura/desa`` fails the
  same way when a value is longer than its column (the form's ``maxlength``);
* only zero VAT and zero withholding, transfer (``TR``) or direct debit (``R``)
  due dates, and centres that do not settle VAT were exercised end to end.

Anything outside that envelope is *blocked*, not guessed: a capability that was
not verified is not one Cosecre has.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .schemas import ExportContext, InvoiceIn

#: The invoice form's ``maxlength`` values: longer passes validate, fails desa.
LIMITS = {
    "document_number": 20,
    "internal_number": 20,
    "description": 100,
    "observations": 500,
    "due_description": 200,
}
#: Payment types saved and read back successfully in formació.
VERIFIED_PAYMENT_TYPES = {"TR", "R"}
#: Environments where writing supplier invoices was verified.
VERIFIED_ENVIRONMENTS = {"training"}
CENT = Decimal("0.01")

CAPABILITIES = [
    {
        "entity": "supplier_invoice",
        "action": "create",
        "environment": "training",
        "status": "verified",
        "verified_on": "2026-10-12",
        "scope": "Factura pendent, sense pagament; IVA i IRPF zero; venciment TR o R; centre que no liquida IVA.",
    },
    {
        "entity": "supplier_invoice",
        "action": "create",
        "environment": "production",
        "status": "disabled",
        "verified_on": None,
        "scope": "No s'ha verificat cap escriptura a producció.",
    },
]


@dataclass(frozen=True)
class Problem:
    field: str
    code: str
    message: str
    blocking: bool = True


def duplicate_key(invoice: InvoiceIn) -> str:
    """Supplier and number, as Esfer@ judges a duplicate within a budget."""
    return f"{invoice.supplier_remote_id}:{invoice.document_number.strip().upper()}"


def _cents(value: Decimal) -> bool:
    return value == value.quantize(CENT)


def check_invoice(context: ExportContext, invoice: InvoiceIn, *, today: date | None = None) -> list[Problem]:
    """Every reason this invoice cannot be exported as it stands."""
    today = today or date.today()
    problems: list[Problem] = []
    add = problems.append

    if context.environment not in VERIFIED_ENVIRONMENTS:
        add(Problem("context.environment", "environment_unverified", "L'escriptura a aquest entorn no està verificada."))
    if context.vat_settlement:
        add(Problem("context.vat_settlement", "vat_settlement_unverified", "El centre liquida IVA: cal un tractament fiscal verificat abans d'exportar."))
    if invoice.accounting_date.year != context.financial_year:
        add(Problem("accounting_date", "year_mismatch", f"La data comptable no és de l'exercici {context.financial_year}."))
    if invoice.document_date > invoice.accounting_date:
        add(Problem("document_date", "document_after_accounting", "La data del document és posterior a la data comptable.", blocking=False))
    if invoice.accounting_date > today:
        add(Problem("accounting_date", "future_date", "La data comptable és futura."))

    texts = {
        "document_number": invoice.document_number,
        "internal_number": invoice.internal_number or "",
        "description": invoice.description,
        "observations": invoice.observations or "",
    }
    if not invoice.document_number.strip():
        add(Problem("document_number", "required", "Cal el número de factura del proveïdor."))
    if not invoice.description.strip():
        add(Problem("description", "required", "Cal una descripció."))
    for field, value in texts.items():
        if len(value) > LIMITS[field]:
            add(Problem(field, "too_long", f"{len(value)} caràcters; Esfer@ n'admet {LIMITS[field]}."))

    total = invoice.total
    if not _cents(total) or total <= 0:
        add(Problem("total", "invalid_amount", "L'import total ha de ser positiu i amb cèntims com a màxim."))

    if not invoice.lines:
        add(Problem("lines", "required", "Cal almenys una línia."))
    line_sum = Decimal(0)
    for i, line in enumerate(invoice.lines):
        where = f"lines[{i}]"
        if line.cost_centre_remote_id is None:
            add(Problem(f"{where}.cost_centre_remote_id", "cost_centre_missing", "Cada línia necessita el centre de cost de la partida; sense ell Esfer@ falla en desar."))
        if line.vat_amount is None:
            add(Problem(f"{where}.vat_amount", "vat_unknown", "Cal indicar l'IVA de la línia, encara que sigui zero; no se suposa."))
        elif line.vat_amount != 0:
            add(Problem(f"{where}.vat_amount", "vat_unverified", "Només s'ha verificat l'exportació amb IVA zero."))
        if line.withholding_amount != 0:
            add(Problem(f"{where}.withholding_amount", "withholding_unverified", "Només s'ha verificat l'exportació sense retenció d'IRPF."))
        for name in ("base", "vat_amount", "withholding_amount"):
            value = getattr(line, name)
            if value is not None and not _cents(value):
                add(Problem(f"{where}.{name}", "precision", "Com a màxim dos decimals."))
        if line.base <= 0:
            add(Problem(f"{where}.base", "invalid_amount", "La base ha de ser positiva; els abonaments tenen un circuit propi."))
        line_sum += line.base + (line.vat_amount or 0) - line.withholding_amount
    if invoice.lines and line_sum != total:
        add(Problem("lines", "lines_total_mismatch", f"Les línies sumen {line_sum} i el total és {total}."))

    if not invoice.due_dates:
        add(Problem("due_dates", "required", "Cal almenys un venciment."))
    due_sum = Decimal(0)
    for i, due in enumerate(invoice.due_dates):
        where = f"due_dates[{i}]"
        if due.payment_type not in VERIFIED_PAYMENT_TYPES:
            add(Problem(f"{where}.payment_type", "payment_type_unverified", f"Forma de pagament no verificada ({due.payment_type}); s'admet {', '.join(sorted(VERIFIED_PAYMENT_TYPES))}."))
        if due.bank_account_remote_id is None:
            add(Problem(f"{where}.bank_account_remote_id", "bank_account_missing", "Cal el compte bancari del centre per al venciment."))
        if due.description and len(due.description) > LIMITS["due_description"]:
            add(Problem(f"{where}.description", "too_long", f"Esfer@ n'admet {LIMITS['due_description']} caràcters."))
        if not _cents(due.amount) or due.amount <= 0:
            add(Problem(f"{where}.amount", "invalid_amount", "Import positiu amb cèntims com a màxim."))
        due_sum += due.amount
    if invoice.due_dates and due_sum != total:
        add(Problem("due_dates", "due_total_mismatch", f"Els venciments sumen {due_sum} i el total és {total}."))
    return problems


def _date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _amount(value: Decimal) -> float:
    return float(value.quantize(CENT))


def esfera_payload(context: ExportContext, invoice: InvoiceIn) -> dict[str, Any]:
    """The ``/factura/validate`` and ``/factura/desa`` body, in the portal form's shape.

    References go as ``{id}`` only; that was enough for validate and desa.
    """
    total = _amount(invoice.total)
    return {
        "rapel": False,
        "assignacio": None,
        "dataAnulacio": None,
        "dataAbonament": None,
        "dataDocument": _date(invoice.document_date),
        "dataRegistre": _date(invoice.accounting_date),
        "descripcio": invoice.description,
        "observacions": invoice.observations,
        "despesaSimplificada": "F",
        "identificadorDocCentre": invoice.internal_number,
        "identificadorDocProveidor": invoice.document_number,
        "importIrpf": _amount(sum((line.withholding_amount for line in invoice.lines), Decimal(0))),
        "importIvaTotal": _amount(sum((line.vat_amount or Decimal(0) for line in invoice.lines), Decimal(0))),
        "importPendent": total,
        "importTotalFinal": total,
        "motiuAnulacio": None,
        "numeroDocumentAbonament": None,
        "tipusDespesa": "1",
        "tipusDocument": "F",
        "pressupost": {"id": context.remote_budget_id, "any": context.financial_year, "idCentre": context.remote_centre_id},
        "proveidor": {"id": invoice.supplier_remote_id},
        "liquidat": "F",
        "partidasFactura": [
            {
                "partidaPressupost": {"id": line.partida_remote_id},
                "centreCost": {"id": line.cost_centre_remote_id},
                "importBase": _amount(line.base),
                "importIrpf": f"{line.withholding_amount.quantize(CENT)}",
                # Esfer@ stores the line base here for a centre that does not settle VAT.
                "importBaseProrrata": _amount(line.base),
                "reservaDespesa": None,
            }
            for line in invoice.lines
        ],
        "vencimentsFactura": [
            {
                "anulat": "F",
                "liquidat": "F",
                "dataVenciment": _date(due.date),
                "import_": _amount(due.amount),
                "tipusPagament": due.payment_type,
                "numeroXec": None,
                "compteBancari": {"id": due.bank_account_remote_id},
                "descripcio": due.description or f"Pagament de la factura {invoice.document_number}",
            }
            for due in invoice.due_dates
        ],
    }


def plan_hash(context: ExportContext, invoices: list[InvoiceIn]) -> str:
    """What an approval is bound to: any material change produces another hash."""
    body = {
        "context": context.model_dump(mode="json"),
        "items": [invoice.model_dump(mode="json") for invoice in invoices],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def problems_json(problems: list[Problem]) -> list[dict[str, Any]]:
    return [asdict(p) for p in problems]
