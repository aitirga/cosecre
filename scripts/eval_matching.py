"""Run the real matching pipeline over a backup and a statement, and print what it proposes.

Works on a *copy* of the database, so nothing is ever written to the backup or
to production. Uses the real models when keys are set (``COSECRE_OPENAI_API_KEY``,
``COSECRE_TYPESAFE_API_KEY``); without them only rule-decided matches appear.

    just eval-matching backups/cosecre-….tar.gz ~/Downloads/Moviments_compte.xls
"""

from __future__ import annotations

import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from cosecre_hub.bootstrap import apply_compat_migrations
from cosecre_hub.config import Settings
from cosecre_hub.db import create_session_factory, create_sqlalchemy_engine, init_db
from cosecre_hub.models import BankMovement, Document
from cosecre_hub.services.classification import JevClient
from cosecre_hub.services.llm import LLMRegistry
from cosecre_hub.services.matching import engine
from cosecre_hub.services.matching.confidence import band
from cosecre_hub.services.statements import caixa_xls, store

DOTS = {"high": "🟢", "medium": "🟡", "low": "🔴", "none": "⚪"}


def database_from(source: Path, workdir: Path) -> Path:
    target = workdir / "cosecre.db"
    if source.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(source) as archive:
            member = archive.getmember("cosecre.db")
            with archive.extractfile(member) as data, target.open("wb") as out:
                shutil.copyfileobj(data, out)
    else:
        shutil.copy(source, target)
    return target


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    workdir = Path(tempfile.mkdtemp(prefix="cosecre-eval-"))
    db_path = database_from(Path(argv[1]), workdir)
    settings = Settings(database_url=f"sqlite:///{db_path}", upload_dir=workdir / "uploads")
    db = create_sqlalchemy_engine(settings.database_url)
    init_db(db)
    session: Session = create_session_factory(db)()
    apply_compat_migrations(session)

    registry = LLMRegistry.from_settings(settings)
    jev = JevClient(settings.typesafe_api_key, settings.jev_model) if settings.typesafe_api_key else None
    print(f"Register: {session.query(Document).count()} entries · "
          f"gpt: {'on' if registry.any_configured() else 'off'} · Jev: {'on' if jev else 'off'}\n")

    for path in map(Path, argv[2:]):
        parsed = caixa_xls.parse(path.read_bytes(), path.name)
        statement = store.save(session, parsed, compte="General", file_name=path.name)
        print(f"{path.name}: {statement.rows_total} movements, {parsed.account_iban}")

    pending = session.query(BankMovement).filter(BankMovement.match_status == "unmatched").all()
    documents = engine.open_documents(session)
    calls = 0
    rows = []
    for movement in pending:
        outcome = engine.match_movement(
            session, movement, registry=registry, jev=jev, model=settings.openai_model, documents=documents
        )
        calls += int("openai" in outcome.trace)
        if outcome.candidates:
            rows.append((movement, outcome))

    withdrawn = engine.resolve_conflicts(session, [m.id for m in pending])
    proposed = sum(1 for m, _ in rows if m.match_status == "proposed")
    print(
        f"\n{len(pending)} payments · {len(rows)} with candidates · {calls} sent to the models · "
        f"{proposed} proposed · {withdrawn} withdrawn (invoice fits another movement better)\n"
    )
    for movement, outcome in rows:
        session.refresh(movement)
        print(f"{movement.data}  {movement.import_value:>10.2f}  {movement.concepte} | {movement.mes_dades}")
        for match in sorted(movement.matches, key=lambda m: (m.rank, m.id)):
            d = match.document
            tick = DOTS[band(match.confidence)] if match.status == "proposed" else "  "
            signals = " ".join(
                f"{k}={v:g}" for k, v in match.signals.items() if k not in {"group", "set_size"} and v
            )
            print(
                f"   {tick} {match.status:<11} {match.confidence:>3}  {d.num_factura} · {d.proveidor} · "
                f"{d.data_factura} · {d.import_value}  [{match.decided_by}] {signals}"
            )
        trace = outcome.trace
        if "openai" in trace:
            o = (trace["openai"].get("answer") or {})
            j = (trace.get("jev", {}).get("answer") or {})
            print(f"      gpt: {o.get('choice')} ({o.get('confidence')}) {o.get('reason', '')}")
            print(f"      jev: {j.get('choice')} ({j.get('confidence')})  status={trace.get('jev', {}).get('status')}")
        print()
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
