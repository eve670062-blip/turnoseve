import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { QueueApiService } from './queue-api.service';
import { Desk, QueueState, Ticket } from './queue.models';

type View = 'client' | 'board' | 'staff';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit, OnDestroy {
  private readonly api = inject(QueueApiService);
  private readonly subscriptions = new Subscription();
  readonly state = signal<QueueState | null>(null);
  readonly view = signal<View>('client');
  readonly selectedService = signal('Cajas');
  readonly ticket = signal<Ticket | null>(null);
  readonly busy = signal(false);
  readonly notice = signal('');
  readonly connected = signal(false);

  readonly services = [
    { name: 'Cajas', description: 'Depósitos, retiros y pagos', icon: '▤', color: 'blue' },
    { name: 'Atención a clientes', description: 'Aclaraciones y consultas', icon: '♧', color: 'violet' },
    { name: 'Créditos', description: 'Solicitudes y seguimiento', icon: '▥', color: 'orange' },
    { name: 'Empresas', description: 'Servicios para negocios', icon: '⌂', color: 'green' },
  ];

  ngOnInit(): void {
    this.subscriptions.add(this.api.getState().subscribe({
      next: (state) => { this.state.set(state); this.connected.set(true); },
      error: () => this.showNotice('No pudimos conectar con el servidor. Revisa que la API esté activa.'),
    }));
    this.subscriptions.add(this.api.watchBoard().subscribe({
      next: (state) => {
        this.state.set(state);
        this.connected.set(true);
        this.syncTicket(state);
      },
      error: () => this.connected.set(false),
    }));
    this.restoreTicket();
  }

  ngOnDestroy(): void {
    this.subscriptions.unsubscribe();
  }

  chooseService(service: string): void {
    this.selectedService.set(service);
  }

  requestTicket(): void {
    if (this.busy() || this.ticket()) return;
    this.busy.set(true);
    this.api.createTicket(this.selectedService()).subscribe({
      next: (response) => {
        this.ticket.set(response.ticket);
        this.saveTicketId(response.ticket.id);
        this.busy.set(false);
        if (response.ticket.status === 'called') {
          this.showNotice(`Tu turno es el ${this.formatNumber(response.ticket.number)}. Pasa a la mesa ${response.ticket.desk_id}.`);
        } else {
          this.showNotice(`Tu turno es el ${this.formatNumber(response.ticket.number)}. Ya estás en la fila.`);
        }
      },
      error: (error: unknown) => {
        this.busy.set(false);
        this.showNotice(this.errorMessage(error, 'No fue posible tomar el turno.'));
      },
    });
  }

  cancelTicket(): void {
    const current = this.ticket();
    if (!current || current.status !== 'waiting') return;
    this.api.cancelTicket(current.id).subscribe({
      next: () => { this.clearTicket(); this.showNotice('Turno cancelado.'); },
      error: (error: unknown) => this.showNotice(this.errorMessage(error, 'No fue posible cancelar el turno.')),
    });
  }

  finishDesk(desk: Desk): void {
    if (!desk.current_ticket) return;
    this.api.finishDesk(desk.id).subscribe({
      next: (result) => {
        if (this.ticket()?.id === result.completed.id) this.clearTicket();
        if (result.next_ticket) {
          this.showNotice(`Turno ${this.formatNumber(result.next_ticket.number)} llamado a la mesa ${desk.id}.`);
        } else {
          this.showNotice(`Mesa ${desk.id} libre. No hay turnos pendientes.`);
        }
      },
      error: (error: unknown) => this.showNotice(this.errorMessage(error, 'No fue posible terminar la atención.')),
    });
  }

  waitPosition(ticket: Ticket): number {
    const queue = this.state()?.waiting ?? [];
    return queue.findIndex((item) => item.id === ticket.id) + 1;
  }

  freeDeskCount(): number {
    return (this.state()?.desks ?? []).filter((desk) => !desk.current_ticket).length;
  }

  formatNumber(number: number): string {
    return String(number).padStart(3, '0');
  }

  private restoreTicket(): void {
    try {
      const savedId = Number(localStorage.getItem('turnoseve-ticket-id'));
      if (!savedId) return;
      this.subscriptions.add(this.api.getTicket(savedId).subscribe({
        next: (ticket) => {
          if (ticket.status === 'waiting' || ticket.status === 'called') this.ticket.set(ticket);
          else this.removeSavedTicket();
        },
        error: () => this.removeSavedTicket(),
      }));
    } catch {
      // The app still works if browser storage is unavailable.
    }
  }

  private saveTicketId(id: number): void {
    try { localStorage.setItem('turnoseve-ticket-id', String(id)); } catch { /* storage is optional */ }
  }

  private removeSavedTicket(): void {
    try { localStorage.removeItem('turnoseve-ticket-id'); } catch { /* storage is optional */ }
  }

  private clearTicket(): void {
    this.ticket.set(null);
    this.removeSavedTicket();
  }

  private syncTicket(state: QueueState): void {
    const current = this.ticket();
    if (!current) return;
    const assigned = state.desks.find((desk) => desk.current_ticket?.id === current.id)?.current_ticket;
    if (assigned) {
      this.ticket.set(assigned);
      return;
    }
    const waiting = state.waiting.find((ticket) => ticket.id === current.id);
    if (waiting) {
      this.ticket.set(waiting);
      return;
    }
    this.subscriptions.add(this.api.getTicket(current.id).subscribe({
      next: (ticket) => {
        if (ticket.status === 'waiting' || ticket.status === 'called') this.ticket.set(ticket);
        else this.clearTicket();
      },
      error: () => this.clearTicket(),
    }));
  }

  private showNotice(message: string): void {
    this.notice.set(message);
    setTimeout(() => { if (this.notice() === message) this.notice.set(''); }, 4500);
  }

  private errorMessage(error: unknown, fallback: string): string {
    if (typeof error === 'object' && error !== null && 'error' in error) {
      const payload = (error as { error?: { detail?: unknown } }).error;
      if (typeof payload?.detail === 'string') return payload.detail;
    }
    return fallback;
  }
}
