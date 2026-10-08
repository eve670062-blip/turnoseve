from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    service: str = Field(min_length=2, max_length=80)


class TicketOut(BaseModel):
    id: int
    number: int
    service: str
    status: str
    desk_id: int | None
    created_at: datetime
    called_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class DeskOut(BaseModel):
    id: int
    name: str
    current_ticket: TicketOut | None


class QueueState(BaseModel):
    updated_at: datetime
    desks: list[DeskOut]
    waiting: list[TicketOut]


class TicketCreated(BaseModel):
    ticket: TicketOut
    position: int


class FinishResult(BaseModel):
    completed: TicketOut
    next_ticket: TicketOut | None
    desk_id: int
