import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map, shareReplay } from 'rxjs/operators';

export interface AdminStatus {
  is_staff: boolean;
  username: string | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);

  readonly isStaff = signal(false);
  readonly username = signal<string | null>(null);
  readonly loaded = signal(false);

  private readonly status$: Observable<boolean> = this.http
    .get<AdminStatus>('/api/admin/status/', { withCredentials: true })
    .pipe(
      map((status) => {
        this.isStaff.set(status.is_staff);
        this.username.set(status.username);
        this.loaded.set(true);
        return status.is_staff;
      }),
      catchError(() => {
        this.isStaff.set(false);
        this.username.set(null);
        this.loaded.set(true);
        return of(false);
      }),
      shareReplay(1),
    );

  constructor() {
    this.status$.subscribe();
  }

  ensureLoaded(): Observable<boolean> {
    if (this.loaded()) {
      return of(this.isStaff());
    }
    return this.status$;
  }
}
