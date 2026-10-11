from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import Role
from .common import UtcDatetime
from .documents import COMPTES

RequestKind = Literal["compra", "pressupost", "consulta", "reemborsament"]
RequestStatus = Literal["oberta", "en_revisio", "aprovada", "rebutjada", "resolta", "cancellada"]

#: Kinds that are about money: they carry an amount, a supplier and an account.
SPENDING_KINDS = {"compra", "pressupost", "reemborsament"}


class PersonBrief(BaseModel):
    id: int
    name: str
    role: Role

    @classmethod
    def of(cls, user: Any) -> PersonBrief | None:
        if user is None:
            return None
        return cls(id=user.id, name=user.display_name or user.email, role=user.role)


class RequestCreate(BaseModel):
    kind: RequestKind
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10_000)
    amount: float | None = Field(default=None, ge=0)
    proveidor: str = Field(default="", max_length=255)
    compte: str = ""
    needed_by: date | None = None

    @field_validator("title", "description", "proveidor")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("compte")
    @classmethod
    def _known_account(cls, value: str) -> str:
        if value and value not in COMPTES:
            raise ValueError(f"Compte desconegut: {value}")
        return value

    @model_validator(mode="after")
    def _questions_carry_no_money(self):
        # A question has nothing to pay; dropping stray fields keeps the inbox honest.
        if self.kind == "consulta":
            self.amount, self.proveidor, self.compte = None, "", ""
        return self


class RequestMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)

    @field_validator("body")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El missatge és buit.")
        return value


class RequestStatusChange(BaseModel):
    status: RequestStatus
    #: Required when refusing: the person asking deserves the reason.
    note: str = Field(default="", max_length=10_000)


class RequestAssign(BaseModel):
    assignee_id: int | None = None


class RequestMessageRead(BaseModel):
    id: int
    kind: Literal["message", "status"]
    body: str
    status: RequestStatus | None = None
    author: PersonBrief | None = None
    created_at: UtcDatetime


class LinkedDocument(BaseModel):
    num_doc_intern: str
    num_factura: str
    proveidor: str
    import_value: float | None = None
    status: str
    validat: bool


class RequestSummary(BaseModel):
    id: int
    code: str
    kind: RequestKind
    title: str
    amount: float | None = None
    proveidor: str = ""
    compte: str = ""
    needed_by: date | None = None
    status: RequestStatus
    requester: PersonBrief
    assignee: PersonBrief | None = None
    message_count: int = 0
    document_count: int = 0
    created_at: UtcDatetime
    last_activity_at: UtcDatetime


class RequestDetail(RequestSummary):
    description: str = ""
    messages: list[RequestMessageRead] = []
    documents: list[LinkedDocument] = []
    #: What the person looking may move it to — the client offers only these.
    allowed_statuses: list[RequestStatus] = []
    can_reply: bool = True


class NotificationRead(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    link: dict[str, Any] | None = None
    actor: PersonBrief | None = None
    read: bool
    created_at: UtcDatetime


class UnreadCount(BaseModel):
    count: int
