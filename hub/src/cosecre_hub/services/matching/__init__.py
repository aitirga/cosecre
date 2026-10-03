"""Finding the register entry behind each bank movement.

Kept apart from ``services.statements`` on purpose: bringing a statement in
never matches anything. This package only reads movements and register
entries, and only writes ``PaymentMatch`` proposals — a person confirms them.

* :mod:`.signals` — what agrees between a movement and an invoice, deterministically.
* :mod:`.confidence` — the one 0–100 number, and its colour band.
* :mod:`.engine` — candidates, the two models, and the proposals they lead to.
"""
