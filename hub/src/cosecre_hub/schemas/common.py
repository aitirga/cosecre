from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel


class MessageResponse(BaseModel):
    message: str


class CountResponse(BaseModel):
    count: int


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even for ``DateTime(timezone=True)``;
    # they are UTC, and saying so on the wire stops a browser reading them as
    # local time.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


#: A timestamp that always goes out with its offset.
UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
