from __future__ import annotations

from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class CountResponse(BaseModel):
    count: int
