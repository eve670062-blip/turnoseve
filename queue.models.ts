export type TicketStatus = 'waiting' | 'called' | 'completed' | 'cancelled';

export interface Ticket {
  id: number;
  number: number;
  service: string;
  status: TicketStatus;
  desk_id: number | null;
  created_at: string;
  called_at: string | null;
  completed_at: string | null;
}

export interface Desk {
  id: number;
  name: string;
  current_ticket: Ticket | null;
}

export interface QueueState {
  updated_at: string;
  desks: Desk[];
  waiting: Ticket[];
}

export interface TicketCreated {
  ticket: Ticket;
  position: number;
}

export interface FinishResult {
  completed: Ticket;
  next_ticket: Ticket | null;
  desk_id: number;
}
