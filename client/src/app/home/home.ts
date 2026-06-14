import { Component, inject, OnInit, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatCardModule } from '@angular/material/card';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

interface HealthResponse {
  status: string;
}

@Component({
  selector: 'app-home',
  imports: [MatCardModule, MatProgressSpinnerModule],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class HomeComponent implements OnInit {
  private http = inject(HttpClient);

  health = signal<string | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);

  ngOnInit(): void {
    this.http.get<HealthResponse>('/api/health/').subscribe({
      next: (res) => {
        this.health.set(res.status);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not reach backend');
        this.loading.set(false);
      },
    });
  }
}
