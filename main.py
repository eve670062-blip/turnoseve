from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, IS_SQLITE, SessionLocal, engine, write_session
from .models import Desk, Ticket, TicketSequence
from .schemas import DeskOut, FinishResult, QueueState, TicketCreate, TicketCreated, TicketOut


LOCAL_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Mexico_City"))
SERVICE_NAMES = {"Cajas", "Atención a clientes", "Créditos", "Empresas"}


class BoardConnections:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def publish(self, payload: dict) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


board_connections = BoardConnections()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with write_session() as db:
        for desk_id in range(1, 5):
            if db.get(Desk, desk_id) is None:
                db.add(Desk(id=desk_id, name=f"Mesa {desk_id}"))
    yield


app = FastAPI(title="TurnoSeve API", version="1.0.0", lifespan=lifespan)
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def ticket_query(db: Session, ticket_id: int) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def build_state(db: Session) -> QueueState:
    desks: list[DeskOut] = []
    for desk in db.scalars(select(Desk).order_by(Desk.id)).all():
        current = db.scalar(
            select(Ticket).where(Ticket.desk_id == desk.id, Ticket.status == "called")
        )
        desks.append(
            DeskOut(id=desk.id, name=desk.name, current_ticket=TicketOut.model_validate(current) if current else None)
        )
    waiting = db.scalars(
        select(Ticket)
        .where(Ticket.status == "waiting")
        .order_by(Ticket.created_at, Ticket.id)
    ).all()
    return QueueState(
        updated_at=datetime.now(timezone.utc),
        desks=desks,
        waiting=[TicketOut.model_validate(ticket) for ticket in waiting],
    )


def read_state() -> QueueState:
    with SessionLocal() as db:
        return build_state(db)


def acquire_desks(db: Session) -> list[Desk]:
    query = select(Desk).order_by(Desk.id)
    if not IS_SQLITE:
        query = query.with_for_update()
    return list(db.scalars(query).all())


def allocate_to_first_free(db: Session, ticket: Ticket, desks: list[Desk]) -> bool:
    busy_ids = set(
        db.scalars(select(Ticket.desk_id).where(Ticket.status == "called", Ticket.desk_id.is_not(None))).all()
    )
    desk = next((desk for desk in desks if desk.id not in busy_ids), None)
    if desk is None:
        return False
    ticket.status = "called"
    ticket.desk_id = desk.id
    ticket.called_at = local_now()
    return True


def assigned_desk(db: Session, ticket: Ticket) -> int | None:
    if ticket.status != "called":
        return None
    return ticket.desk_id


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "turnoseve-api"}


@app.get("/api/state", response_model=QueueState)
def get_state() -> QueueState:
    return read_state()


@app.get("/api/queue", response_model=list[TicketOut])
def get_queue() -> list[TicketOut]:
    return read_state().waiting


@app.get("/api/turns/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int) -> TicketOut:
    with SessionLocal() as db:
        ticket = ticket_query(db, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="No se encontró ese turno.")
        return TicketOut.model_validate(ticket)


@app.post("/api/turns", response_model=TicketCreated, status_code=201)
async def create_ticket(request: TicketCreate) -> TicketCreated:
    service = request.service.strip()
    if service not in SERVICE_NAMES:
        raise HTTPException(status_code=422, detail="Selecciona un trámite válido.")
    now = local_now()
    day_key = now.date().isoformat()
    with write_session() as db:
        desks = acquire_desks(db)
        sequence = db.get(TicketSequence, day_key)
        if sequence is None:
            sequence = TicketSequence(day_key=day_key, next_number=1)
            db.add(sequence)
            db.flush()
        number = sequence.next_number
        sequence.next_number += 1
        ticket = Ticket(day_key=day_key, number=number, service=service, status="waiting", created_at=now)
        db.add(ticket)
        db.flush()
        allocate_to_first_free(db, ticket, desks)
        db.flush()
        ticket_out = TicketOut.model_validate(ticket)
        position = 0 if ticket.status == "called" else len(
            db.scalars(select(Ticket.id).where(Ticket.status == "waiting").order_by(Ticket.created_at, Ticket.id)).all()
        ) - 1
    await board_connections.publish(read_state().model_dump(mode="json"))
    return TicketCreated(ticket=ticket_out, position=max(position, 0))


@app.post("/api/desks/{desk_id}/finish", response_model=FinishResult)
async def finish_service(desk_id: int) -> FinishResult:
    now = local_now()
    with write_session() as db:
        desk = db.get(Desk, desk_id) if IS_SQLITE else db.scalar(
            select(Desk).where(Desk.id == desk_id).with_for_update()
        )
        if desk is None:
            raise HTTPException(status_code=404, detail="No existe esa mesa.")
        current = db.scalar(
            select(Ticket).where(Ticket.desk_id == desk_id, Ticket.status == "called")
        )
        if current is None:
            raise HTTPException(status_code=409, detail="La mesa ya está libre.")
        current.status = "completed"
        current.completed_at = now
        completed_out = TicketOut.model_validate(current)
        waiting_query = (
            select(Ticket)
            .where(Ticket.status == "waiting")
            .order_by(Ticket.created_at, Ticket.id)
            .limit(1)
        )
        if not IS_SQLITE:
            waiting_query = waiting_query.with_for_update()
        next_ticket = db.scalar(waiting_query)
        if next_ticket is not None:
            next_ticket.status = "called"
            next_ticket.desk_id = desk_id
            next_ticket.called_at = now
            db.flush()
            next_out = TicketOut.model_validate(next_ticket)
        else:
            next_out = None
    await board_connections.publish(read_state().model_dump(mode="json"))
    return FinishResult(completed=completed_out, next_ticket=next_out, desk_id=desk_id)


@app.delete("/api/turns/{ticket_id}", status_code=204, response_class=Response)
async def cancel_ticket(ticket_id: int) -> Response:
    with write_session() as db:
        ticket = ticket_query(db, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="No se encontró ese turno.")
        if ticket.status != "waiting":
            raise HTTPException(status_code=409, detail="Solo se pueden cancelar turnos que siguen en espera.")
        ticket.status = "cancelled"
    await board_connections.publish(read_state().model_dump(mode="json"))
    return Response(status_code=204)


@app.websocket("/ws/board")
async def board_socket(websocket: WebSocket) -> None:
    await board_connections.connect(websocket)
    try:
        with SessionLocal() as db:
            await websocket.send_json(build_state(db).model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        board_connections.disconnect(websocket)
