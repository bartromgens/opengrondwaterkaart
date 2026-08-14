import { Component, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginator, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsCoreOption } from 'echarts/core';

import {
  AgeDistributionBucket,
  FrequencyDistribution,
  MeasurementFrequency,
  WellOverviewRow,
  WellsService,
  WellsStats,
} from '../wells.service';
import { SeoService } from '../seo.service';

const FREQUENCY_LABELS: Record<MeasurementFrequency, string> = {
  daily: 'Dagelijks',
  weekly: 'Wekelijks',
  monthly: 'Maandelijks',
  quarterly: 'Per kwartaal',
  yearly: 'Jaarlijks',
  irregular: 'Onregelmatig',
};

const INITIAL_FUNCTION_LABELS: Record<string, string> = {
  stand: 'Waterstand',
  kwaliteit: 'Kwaliteit',
  combinatie: 'Combinatie',
  onbekend: 'Onbekend',
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

function buildAgeChartOption(buckets: AgeDistributionBucket[]): EChartsCoreOption {
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    grid: {
      left: 48,
      right: 16,
      top: 16,
      bottom: 56,
    },
    xAxis: {
      type: 'category',
      data: buckets.map((b) => b.label),
      axisLabel: {
        interval: 0,
        rotate: 30,
        color: '#555',
        fontSize: 11,
      },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#555' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [
      {
        type: 'bar',
        data: buckets.map((b) => b.count),
        itemStyle: { color: '#2196f3', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 48,
      },
    ],
  };
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
    NgxEchartsDirective,
  ],
  templateUrl: './wells-overview.html',
  styleUrl: './wells-overview.scss',
})
export class WellsOverviewComponent implements OnInit {
  @ViewChild(MatPaginator) paginator!: MatPaginator;

  private wellsService = inject(WellsService);
  private seo = inject(SeoService);

  readonly displayedColumns = [
    'name',
    'nitg_code',
    'owner',
    'well_construction_date',
    'initial_function',
    'number_of_monitoring_tubes',
    'research_first_date',
    'monitoring_networks',
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

  ageChartOption = computed<EChartsCoreOption | null>(() => {
    const buckets = this.stats()?.latest_measurement_age_distribution;
    if (!buckets?.length) return null;
    return buildAgeChartOption(buckets);
  });

  private ordering = '-last_measured_on';

  ngOnInit(): void {
    this.seo.updateMetadata({
      title: 'Putten overzicht — OpenGrondWaterKaart',
      description:
        'Overzicht van alle grondwatermeetputten in Nederland, met meetfrequentie, laatste meting en andere statistieken per put.',
      path: '/wells',
    });
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

  formatInitialFunction(code: string | null): string {
    if (!code) return '—';
    return INITIAL_FUNCTION_LABELS[code] ?? code;
  }

  formatNetworks(networks: WellOverviewRow['monitoring_networks']): string {
    if (!networks.length) return '—';
    return networks.map((network) => network.name).join(', ');
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
