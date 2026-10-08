from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, Depends
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
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)


board_manager = BoardConnections()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.scalars(select(Desk)).all()
        if not existing:
            for name in SERVICE_NAMES:
                db.add(Desk(name=name, status="libre"))
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(lifespan=lifespan)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependencia para manejar la sesión de la base de datos correctamente en FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_write_db():
    db = write_session()
    try:
        yield db
    finally:
        db.close()


def get_queue_state(db: Session) -> QueueState:
    desks = db.scalars(select(Desk).order_by(Desk.id)).all()
    waiting_tickets = db.scalars(
        select(Ticket).where(Ticket.status == "esperando").order_by(Ticket.created_at.asc())
    ).all()
    
    current_serving = [
        TicketOut(
            id=d.current_ticket.id,
            number=d.current_ticket.number,
            service=d.current_ticket.service,
            status=d.current_ticket.status,
            created_at=d.current_ticket.created_at,
            called_at=d.current_ticket.called_at,
        )
        for d in desks if d.current_ticket is not None
    ]
    
    waiting = [
        TicketOut(
            id=t.id,
            number=t.number,
            service=t.service,
            status=t.status,
            created_at=t.created_at,
            called_at=t.called_at,
        )
        for t in waiting_tickets
    ]
    
    desk_outs = [
        DeskOut(
            id=d.id,
            name=d.name,
            status=d.status,
            current_ticket=(
                TicketOut(
                    id=d.current_ticket.id,
                    number=d.current_ticket.number,
                    service=d.current_ticket.service,
                    status=d.current_ticket.status,
                    created_at=d.current_ticket.created_at,
                    called_at=d.current_ticket.called_at,
                )
                if d.current_ticket
                else None
            ),
        )
        for d in desks
    ]
    
    return QueueState(desks=desk_outs, waiting=waiting, current_serving=current_serving)


@app.get("/api/state", response_model=QueueState)
def api_get_state(db: Session = Depends(get_db)):
    return get_queue_state(db)


@app.post("/api/tickets", response_model=TicketCreated)
def api_create_ticket(payload: TicketCreate, db: Session = Depends(get_write_db)):
    service = payload.service
    if service not in SERVICE_NAMES:
        raise HTTPException(status_code=400, detail="Servicio inválido")
        
    seq = db.scalar(select(TicketSequence).where(TicketSequence.service == service))
    if not seq:
        seq = TicketSequence(service=service, last_number=0)
        db.add(seq)
        db.flush()
        
    seq.last_number += 1
    ticket_number = seq.last_number
    
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        number=ticket_number,
        service=service,
        status="esperando",
        created_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    
    # Asignación automática si hay mesas libres
    free_desk = db.scalars(
        select(Desk).where(Desk.status == "libre").order_by(Desk.id.asc())
    ).first()
    
    if free_desk:
        ticket.status = "atendiendo"
        ticket.called_at = now
        free_desk.status = "ocupada"
        free_desk.current_ticket_id = ticket.id
        db.commit()
        
    return TicketCreated(
        id=ticket.id,
        number=ticket.number,
        service=ticket.service,
        status=ticket.status,
        created_at=ticket.created_at,
        message="Turno creado exitosamente",
    )


@app.post("/api/desks/{desk_id}/finish", response_model=FinishResult)
def api_finish_desk(desk_id: int, db: Session = Depends(get_write_db)):
    desk = db.get(Desk, desk_id)
    if not desk:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")
        
    now = datetime.now(timezone.utc)
    if desk.current_ticket:
        desk.current_ticket.status = "terminado"
        desk.current_ticket.finished_at = now
        
    desk.current_ticket_id = None
    desk.status = "libre"
    
    # Tomar el siguiente de la fila (FIFO)
    next_ticket = db.scalars(
        select(Ticket).where(Ticket.status == "esperando").order_by(Ticket.created_at.asc())
    ).first()
    
    if next_ticket:
        next_ticket.status = "atendiendo"
        next_ticket.called_at = now
        desk.status = "ocupada"
        desk.current_ticket_id = next_ticket.id
        
    db.commit()
    return FinishResult(success=True, message="Mesa liberada y siguiente turno asignado")


@app.websocket("/ws/board")
async def websocket_board(websocket: WebSocket):
    await board_manager.connect(websocket)
    db = SessionLocal()
    try:
        initial_state = get_queue_state(db)
        await websocket.send_json(initial_state.model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        board_manager.disconnect(websocket)
    finally:
        db.close()
