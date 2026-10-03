"""Fakes for the statements and matching tests: a model that answers by schema, and Jev."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from dataclasses import dataclass, field
from typing import Any

import httpx

from cosecre_hub.services.classification import DocumentClassifier, JevClient
from cosecre_hub.services.llm import StructuredRequest, StructuredResult, Usage

from conftest import FakeProvider

def _iban(country: str, bban: str) -> str:
    """A checksum-valid IBAN for an invented account."""
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(digits) % 97
    raw = f"{country}{check:02d}{bban}"
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


#: An invented account: the repository is public, so no real statement is in it.
GENERAL_IBAN = _iban("ES", "21009999990000001234")

#: ``(date, moviment, més dades, import)``, newest first, the way the bank lists them.
SAMPLE_ROWS = [
    (date(2026, 10, 1), "MANTENIMENT", "", -30.00),
    (date(2026, 10, 1), "CARLIN CATALUNYA", "B64902166006", -312.40),
    (date(2026, 10, 1), "CARLIN CATALUNYA", "B64902166006", -205.10),
    (date(2026, 10, 1), "CARLIN CATALUNYA", "B64902166006", -98.35),
    (date(2026, 9, 30), "CORRESP. 09/2026", "", -1.39),
    (date(2026, 9, 29), "FAC:PRF26-00001", "EDITORIAL TEIDE", -151.20),
    (date(2026, 9, 29), "FAC:0397", "EDISAMA", -70.00),
    (date(2026, 9, 29), "FAC:30737", "ANDES LIBROS", -88.80),
    (date(2026, 9, 29), "CARREGA.TARG.PREPAG", "", -400.00),
    (date(2026, 9, 25), "JUNIOR REPORT", "", -64.00),
    (date(2026, 9, 25), "CONSOR DEDUCAC.BA", "GA PRIM 3R TRIM/14.09.2026", 5000.00),
    (date(2026, 9, 24), "OPENAI *CHATGPT S", "", -78.01),
    (date(2026, 9, 17), "FAC:2026/116574", "HERMEX IBERICA SL", -4321.50),
    (date(2026, 9, 17), "FAC:22617094", "ELKSPORT", -45.60),
    (date(2026, 9, 17), "FAC:140927 CUSTOM", "THOMANN", -120.00),
    (date(2026, 9, 17), "FAC:0272", "DRAC MAGIC", -59.90),
    (date(2026, 9, 12), "FAC:Q000059/2026", "FARMACIA EXEMPLE", -9.37),
    (date(2026, 9, 12), "FAC:260103762", "VICENS VIVES", -410.00),
    (date(2026, 9, 10), "IKEA IBERICA WEB", "", -812.30),
    (date(2026, 9, 10), "SIEMENS FINANCIAL", "Rebuts varis", -69.20),
]

#: Older months, for a longer statement that overlaps the sample.
EARLIER_ROWS = [
    (date(2026, 8, 24), "OPENAI *CHATGPT S", "", -78.01),
    (date(2026, 7, 24), "OPENAI *CHATGPT S", "", -78.01),
    (date(2026, 7, 8), "NOVES DISTR.CATAL", "B62092358000", -47.09),
    (date(2026, 6, 30), "IMP. EFECTIU-FAMILIES", "", 1278.00),
    (date(2026, 6, 24), "OPENAI *CHATGPT S", "", -78.01),
    (date(2026, 6, 18), "Fac: EV2647117", "Events Branch SL", -1500.00),
    (date(2026, 6, 11), "WWW.AMAZON", "", -31.86),
    (date(2026, 6, 8), "Fac: ES 139/2026", "N54 Produccions SL", -286.00),
    (date(2026, 6, 3), "Reserva P2026076", "Salvador Exemple", -339.00),
    (date(2026, 5, 24), "OPENAI *CHATGPT S", "", -78.01),
    (date(2026, 5, 15), "Fac: CC 4034", "Estudi Cinema", -138.65),
    (date(2026, 4, 24), "OPENAI *CHATGPT S", "", -61.11),
]


def caixa_xls(rows, iban: str = GENERAL_IBAN, closing: float = 50_000.0) -> bytes:
    """A statement in CaixaBank's exact export layout, as a real BIFF ``.xls``.

    Balances are worked back from ``closing``, so two overlapping statements
    agree on the balance of every line they share — as the bank's do.
    """
    import io

    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Moviments")
    compact = iban.replace(" ", "")
    sheet.write(0, 0, f"Moviments del compte {iban} (CCC: {compact[4:8]} {compact[8:12]} {compact[12:14]} {compact[14:]})")
    sheet.write(1, 0, "Imports expressats en euros")
    for col, header in enumerate(["Data", "Data valor", "Moviment", "Més dades", "Import", "Saldo"]):
        sheet.write(2, col, header)
    balances = []
    balance = closing
    for row in rows:
        balances.append(round(balance, 2))
        balance -= row[3]
    epoch = date(1899, 12, 30)
    for index, ((when, moviment, extra, amount), saldo) in enumerate(zip(rows, balances), start=3):
        serial = (when - epoch).days
        for col, value in enumerate([serial, serial, moviment, extra, amount, saldo]):
            sheet.write(index, col, value)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


LONG_ROWS = sorted(SAMPLE_ROWS + EARLIER_ROWS, key=lambda r: r[0], reverse=True)
SAMPLE_XLS = caixa_xls(SAMPLE_ROWS)
LONG_XLS = caixa_xls(LONG_ROWS)


VALID_FORMAT = {
    "valid": True,
    "bank": "CaixaBank",
    "account_iban": GENERAL_IBAN,
    "header_row": 2,
    "confidence": 0.97,
    "issues": [],
}


def options(prompt: str) -> dict[str, str]:
    """``c1 → description`` from a matching prompt."""
    return dict(re.findall(r"^- (c\d+|cap): (.*)$", prompt, flags=re.MULTILINE))


@dataclass
class RoutingProvider(FakeProvider):
    """Answers each structured call according to what it was asked for."""

    format_verdict: dict[str, Any] = field(default_factory=lambda: dict(VALID_FORMAT))
    #: ``prompt options → (choice, confidence)`` for the matching question.
    chooser: Callable[[dict[str, str]], tuple[str, float]] = lambda opts: ("cap", 0.5)
    match_calls: int = 0

    def structured(self, request: StructuredRequest) -> StructuredResult:
        self._guard()
        self.structures.append(request)
        if request.schema_name == "statement_format_check":
            data = dict(self.format_verdict)
        elif request.schema_name == "payment_match":
            self.match_calls += 1
            choice, confidence = self.chooser(options(request.messages[0].content))
            data = {"choice": choice, "confidence": confidence, "reason": "Fake reason."}
        else:
            data = dict(self.structured_payload)
        return StructuredResult(data=data, model="fake-model-1", provider=self.id, usage=Usage())


def jev_classifier(chooser: Callable[[dict[str, str]], tuple[str, float]]) -> DocumentClassifier:
    """A Jev whose answer to the matching question comes from ``chooser``."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        answers = {}
        for name, question in body["questions"].items():
            choice, confidence = chooser(question["criteria"])
            answers[name] = {"choice": choice, "confidence": confidence, "probabilities": {choice: confidence}}
        return httpx.Response(200, json={"answers": answers})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DocumentClassifier(JevClient("test-key", client=client))


def pick(word: str, confidence: float = 0.9) -> Callable[[dict[str, str]], tuple[str, float]]:
    """Choose the option whose description mentions ``word``."""

    def chooser(opts: dict[str, str]) -> tuple[str, float]:
        for key, text in opts.items():
            if key != "cap" and word.lower() in text.lower():
                return key, confidence
        return "cap", confidence

    return chooser
