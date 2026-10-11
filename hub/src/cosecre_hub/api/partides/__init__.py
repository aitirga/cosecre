"""Budget lines (partides) and the invoices charged to them.

One directory, as ``hub/README.md`` asks of an app with server-side code:
models, schemas and routes together, and one ``include_router``.
"""

from .routes import router

__all__ = ["router"]
