import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from './environment';
import { FinishResult, QueueState, Ticket, TicketCreated } from './queue.models';

@Injectable({ providedIn: 'root' })
export class QueueApiService {
  private readonly http = inject(HttpClient);

  getState(): Observable<QueueState> {
    return this.http.get<QueueState>(`${environment.apiUrl}/state`);
  }

  createTicket(service: string): Observable<TicketCreated> {
    return this.http.post<TicketCreated>(`${environment.apiUrl}/turns`, { service });
  }

  getTicket(ticketId: number): Observable<Ticket> {
    return this.http.get<Ticket>(`${environment.apiUrl}/turns/${ticketId}`);
  }

  cancelTicket(ticketId: number): Observable<void> {
    return this.http.delete<void>(`${environment.apiUrl}/turns/${ticketId}`);
  }

  finishDesk(deskId: number): Observable<FinishResult> {
    return this.http.post<FinishResult>(`${environment.apiUrl}/desks/${deskId}/finish`, {});
  }

  watchBoard(): Observable<QueueState> {
    return new Observable<QueueState>((observer) => {
      let socket: WebSocket | undefined;
      let retryTimer: ReturnType<typeof setTimeout> | undefined;
      let closed = false;

      const connect = (): void => {
        if (closed) return;
        socket = new WebSocket(environment.websocketUrl);
        socket.onmessage = (event: MessageEvent<string>) => {
          try {
            observer.next(JSON.parse(event.data) as QueueState);
          } catch (error) {
            observer.error(error);
          }
        };
        socket.onerror = () => socket?.close();
        socket.onclose = () => {
          if (!closed) retryTimer = setTimeout(connect, 1500);
        };
      };

      connect();
      return () => {
        closed = true;
        if (retryTimer) clearTimeout(retryTimer);
        socket?.close();
      };
    });
  }
}
