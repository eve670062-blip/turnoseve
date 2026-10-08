from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Desk(Base):
    __tablename__ = "desks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="desk")


class TicketSequence(Base):
    __tablename__ = "ticket_sequences"

    day_key: Mapped[str] = mapped_column(String(10), primary_key=True)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("day_key", "number", name="uq_ticket_day_number"),
        Index(
            "uq_called_ticket_per_desk",
            "desk_id",
            unique=True,
            sqlite_where=text("status = 'called'"),
            postgresql_where=text("status = 'called'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_key: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    service: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="waiting", index=True)
    desk_id: Mapped[int | None] = mapped_column(ForeignKey("desks.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    desk: Mapped[Desk | None] = relationship(back_populates="tickets")
