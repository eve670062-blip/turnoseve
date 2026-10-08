# TurnoSeve

Sistema de turnos para cuatro mesas de atención. El cliente toma un número y el sistema asigna inmediatamente la primera mesa libre. Si todas están ocupadas, conserva una fila FIFO y pasa al siguiente cliente a la mesa que se desocupe.

## Tecnologías

- Backend: Python, FastAPI, SQLAlchemy y SQLite.
- Frontend: Angular 22.
- Actualizaciones del tablero: WebSocket.

## Backend

Desde `backend/`, crea un entorno virtual, instala dependencias y ejecuta la API:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

La API queda en `http://localhost:8000` y su documentación interactiva en `http://localhost:8000/docs`. La base SQLite se crea automáticamente en `backend/turnoseve.db`. Para cambiarla, establece `DATABASE_URL`.

## Frontend

Requiere Node.js compatible con Angular 22. Desde `frontend/`:

```powershell
npm install
npm start
```

Abre `http://localhost:4200`. La configuración de desarrollo conecta la API a `http://localhost:8000`.

## Uso

- **Cliente:** elige el trámite y toma un turno. Verá si ya tiene mesa asignada o cuántas personas hay antes.
- **Pantalla pública:** muestra los turnos que pasan a las mesas 1 a 4 y la fila pendiente.
- **Personal:** al terminar una atención, pulsa el botón de esa mesa. El turno pendiente más antiguo pasa a ocuparla en la misma operación.

Los turnos se numeran por día y el primer turno del día es el 1. Los cuatro puestos se crean automáticamente al iniciar el backend.
