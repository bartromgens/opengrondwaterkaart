import { Component, OnInit, ViewChild, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginator, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';

import { MeasurementFrequency, WellOverviewRow, WellsService } from '../wells.service';

const FREQUENCY_LABELS: Record<MeasurementFrequency, string> = {
  daily: 'Dagelijks',
  weekly: 'Wekelijks',
  monthly: 'Maandelijks',
  quarterly: 'Per kwartaal',
  yearly: 'Jaarlijks',
  irregular: 'Onregelmatig',
};

@Component({
  selector: 'app-wells-overview',
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatPaginatorModule,
    MatProgressSpinnerModule,
    MatSortModule,
    MatTableModule,
  ],
  templateUrl: './wells-overview.html',
  styleUrl: './wells-overview.scss',
})
export class WellsOverviewComponent implements OnInit {
  @ViewChild(MatPaginator) paginator!: MatPaginator;

  private wellsService = inject(WellsService);

  readonly displayedColumns = [
    'name',
    'nitg_code',
    'first_measured_on',
    'last_measured_on',
    'frequency',
    'measurement_count',
  ];

  rows = signal<WellOverviewRow[]>([]);
  total = signal(0);
  loading = signal(false);
  pageSize = signal(25);

  private ordering = '-last_measured_on';

  ngOnInit(): void {
    this.load(0, this.pageSize(), this.ordering);
  }

  onPageChange(event: PageEvent): void {
    this.pageSize.set(event.pageSize);
    this.load(event.pageIndex, event.pageSize, this.ordering);
  }

  onSortChange(sort: Sort): void {
    this.ordering = sort.direction
      ? `${sort.direction === 'desc' ? '-' : ''}${sort.active}`
      : '-last_measured_on';
    this.paginator.firstPage();
    this.load(0, this.pageSize(), this.ordering);
  }

  formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('nl-NL', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  }

  formatFrequency(frequency: MeasurementFrequency | null): string {
    return frequency ? FREQUENCY_LABELS[frequency] : '—';
  }

  private load(pageIndex: number, pageSize: number, ordering: string): void {
    this.loading.set(true);
    this.wellsService.getWellsOverview({ page: pageIndex + 1, pageSize, ordering }).subscribe({
      next: (response) => {
        this.rows.set(response.results);
        this.total.set(response.count);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }
}
