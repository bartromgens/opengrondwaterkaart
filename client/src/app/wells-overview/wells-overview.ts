import { Component, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginator, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';

import {
  FrequencyDistribution,
  MeasurementFrequency,
  WellOverviewRow,
  WellsService,
  WellsStats,
} from '../wells.service';

const FREQUENCY_LABELS: Record<MeasurementFrequency, string> = {
  daily: 'Dagelijks',
  weekly: 'Wekelijks',
  monthly: 'Maandelijks',
  quarterly: 'Per kwartaal',
  yearly: 'Jaarlijks',
  irregular: 'Onregelmatig',
};

const DISTRIBUTION_LABELS: Record<keyof FrequencyDistribution, string> = {
  ...FREQUENCY_LABELS,
  unknown: 'Onbekend',
  no_data: 'Geen data',
};

const DISTRIBUTION_ORDER: (keyof FrequencyDistribution)[] = [
  'daily',
  'weekly',
  'monthly',
  'quarterly',
  'yearly',
  'irregular',
  'unknown',
  'no_data',
];

export interface DistributionBar {
  key: keyof FrequencyDistribution;
  label: string;
  count: number;
  percent: number;
}

@Component({
  selector: 'app-wells-overview',
  imports: [
    DecimalPipe,
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

  stats = signal<WellsStats | null>(null);
  statsLoading = signal(false);

  distributionBars = computed<DistributionBar[]>(() => {
    const distribution = this.stats()?.frequency_distribution;
    if (!distribution) return [];
    const max = Math.max(...Object.values(distribution), 1);
    return DISTRIBUTION_ORDER.filter((key) => distribution[key] > 0).map((key) => ({
      key,
      label: DISTRIBUTION_LABELS[key],
      count: distribution[key],
      percent: (distribution[key] / max) * 100,
    }));
  });

  private ordering = '-last_measured_on';

  ngOnInit(): void {
    this.load(0, this.pageSize(), this.ordering);
    this.loadStats();
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

  formatAge(days: number | null): string {
    if (days === null) return '—';
    if (days === 0) return 'vandaag';
    if (days === 1) return '1 dag geleden';
    return `${days} dagen geleden`;
  }

  private loadStats(): void {
    this.statsLoading.set(true);
    this.wellsService.getWellsStats().subscribe({
      next: (stats) => {
        this.stats.set(stats);
        this.statsLoading.set(false);
      },
      error: () => {
        this.statsLoading.set(false);
      },
    });
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
