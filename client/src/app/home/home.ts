import { Component, ElementRef, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatSliderModule } from '@angular/material/slider';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';
import * as maplibregl from 'maplibre-gl';

import { WellDetail, WellSeries, WellsService } from '../wells.service';
import { WellChartComponent } from '../well-chart-dialog/well-chart-dialog';

const CLASSIFICATION_COLORS: Record<string, string> = {
  very_low: '#d73027',
  low: '#fc8d59',
  normal: '#91bfdb',
  high: '#4575b4',
  very_high: '#313695',
};

const NO_DATA_COLOR = '#cccccc';

const CLASSIFICATION_LABELS: Record<string, string> = {
  very_low: 'Zeer laag',
  low: 'Laag',
  normal: 'Normaal',
  high: 'Hoog',
  very_high: 'Zeer hoog',
};

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

const TODAY = new Date();
TODAY.setHours(0, 0, 0, 0);
const RANGE_START = addDays(TODAY, -2 * 365);
const TOTAL_DAYS = Math.round((TODAY.getTime() - RANGE_START.getTime()) / 86400000);

const JAN_FIRST = new Date(TODAY.getFullYear(), 0, 1);
const JAN_FIRST_DAYS = Math.max(
  0,
  Math.min(TOTAL_DAYS, Math.round((JAN_FIRST.getTime() - RANGE_START.getTime()) / 86400000)),
);

function daysFromRangeStart(d: Date): number {
  return Math.round((d.getTime() - RANGE_START.getTime()) / 86400000);
}

function sliderPct(days: number): number {
  return (days / TOTAL_DAYS) * 100;
}

function buildMonthTicks(): { label: string; pct: number; major: boolean }[] {
  const ticks: { label: string; pct: number; major: boolean }[] = [];
  const d = new Date(RANGE_START.getFullYear(), RANGE_START.getMonth(), 1);
  if (d < RANGE_START) {
    d.setMonth(d.getMonth() + 1);
  }
  d.setHours(0, 0, 0, 0);
  while (d.getTime() <= TODAY.getTime()) {
    const days = daysFromRangeStart(d);
    const pct = sliderPct(days);
    const month = d.getMonth();
    const major = month === 0 || month === 6;
    const label =
      month === 0
        ? d.toLocaleDateString('nl-NL', { month: 'short', year: '2-digit' })
        : month === 6
          ? d.toLocaleDateString('nl-NL', { month: 'short' })
          : '';
    ticks.push({ label, pct, major });
    d.setMonth(d.getMonth() + 1);
  }
  return ticks;
}

@Component({
  selector: 'app-home',
  imports: [
    CommonModule,
    FormsModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatSliderModule,
    WellChartComponent,
  ],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class HomeComponent implements OnInit, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  private wellsService = inject(WellsService);
  private dateChange$ = new Subject<void>();

  map: maplibregl.Map | null = null;
  popup: maplibregl.Popup | null = null;

  loading = signal(true);
  dateLoading = signal(false);
  lastUpdated = signal<string | null>(null);
  totalWells = signal(0);

  selectedWell = signal<WellDetail | null>(null);
  seriesLoading = signal(false);
  series = signal<WellSeries | null>(null);
  showChart = signal(false);

  readonly classifications = Object.keys(CLASSIFICATION_LABELS);
  readonly classificationColors = CLASSIFICATION_COLORS;
  readonly classificationLabels = CLASSIFICATION_LABELS;
  readonly noDataColor = NO_DATA_COLOR;
  readonly monthTicks = buildMonthTicks();

  /** Slider index: 0 = RANGE_START, TOTAL_DAYS = today */
  sliderValue = JAN_FIRST_DAYS;
  readonly sliderMin = 0;
  readonly sliderMax = TOTAL_DAYS;

  get selectedDate(): Date {
    return addDays(RANGE_START, this.sliderValue);
  }

  get selectedDateIso(): string {
    return toIso(this.selectedDate);
  }

  ngOnInit(): void {
    this.initMap();
    this.loadMeta();

    this.dateChange$.pipe(debounceTime(200)).subscribe(() => this.onDateChanged());
  }

  ngOnDestroy(): void {
    this.map?.remove();
    this.dateChange$.complete();
  }

  private initMap(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
      center: [5.3, 52.2],
      zoom: 7,
    });

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    this.map.on('load', () => this.loadWells());
  }

  private loadWells(): void {
    this.wellsService.getWells(this.selectedDateIso).subscribe({
      next: (geojson) => {
        this.loading.set(false);
        const map = this.map!;

        map.addSource('wells', {
          type: 'geojson',
          data: geojson as any,
        });

        map.addLayer({
          id: 'wells-circle',
          type: 'circle',
          source: 'wells',
          layout: {
            'circle-sort-key': ['case', ['==', ['get', 'classification'], null], 0, 1],
          },
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 3, 12, 7],
            'circle-color': [
              'case',
              ['==', ['get', 'classification'], null],
              NO_DATA_COLOR,
              [
                'match',
                ['get', 'classification'],
                'very_low',
                CLASSIFICATION_COLORS['very_low'],
                'low',
                CLASSIFICATION_COLORS['low'],
                'normal',
                CLASSIFICATION_COLORS['normal'],
                'high',
                CLASSIFICATION_COLORS['high'],
                'very_high',
                CLASSIFICATION_COLORS['very_high'],
                NO_DATA_COLOR,
              ],
            ],
            'circle-opacity': 1.0,
            'circle-stroke-width': 0,
          },
        });

        map.on('click', 'wells-circle', (e: maplibregl.MapLayerMouseEvent) => this.onWellClick(e));
        map.on('mouseenter', 'wells-circle', () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'wells-circle', () => {
          map.getCanvas().style.cursor = '';
        });
      },
      error: () => this.loading.set(false),
    });
  }

  private onDateChanged(): void {
    const dateIso = this.selectedDateIso;
    const source = this.map?.getSource('wells') as maplibregl.GeoJSONSource | undefined;
    if (!source) return;

    this.dateLoading.set(true);
    this.wellsService.getWells(dateIso).subscribe({
      next: (geojson) => {
        source.setData(geojson as any);
        this.dateLoading.set(false);
      },
      error: () => this.dateLoading.set(false),
    });

    const well = this.selectedWell();
    if (well) {
      this.wellsService.getWellDetail(well.bro_id, dateIso).subscribe({
        next: (detail) => this.selectedWell.set(detail),
      });
    }
  }

  onSliderDrag(value: number): void {
    this.sliderValue = value;
  }

  onSliderRelease(): void {
    this.dateChange$.next();
  }

  onDateInput(value: string): void {
    const d = new Date(value);
    if (isNaN(d.getTime())) return;
    d.setHours(0, 0, 0, 0);
    const days = Math.round((d.getTime() - RANGE_START.getTime()) / 86400000);
    this.sliderValue = Math.max(0, Math.min(TOTAL_DAYS, days));
    this.dateChange$.next();
  }

  private onWellClick(e: maplibregl.MapLayerMouseEvent): void {
    const features = e.features;
    if (!features || features.length === 0) return;

    const props = features[0].properties;
    const broId = props['id'];

    this.selectedWell.set(null);
    this.series.set(null);
    this.seriesLoading.set(true);

    this.wellsService.getWellDetail(broId, this.selectedDateIso).subscribe({
      next: (detail) => {
        this.selectedWell.set(detail);
        this.showChart.set(true);
        this.loadSeries(broId);
      },
    });

    this.popup?.remove();
  }

  private loadSeries(broId: string): void {
    this.wellsService.getWellSeries(broId, { date: this.selectedDateIso }).subscribe({
      next: (s) => {
        this.series.set(s);
        this.seriesLoading.set(false);
        setTimeout(() => this.renderChart(), 50);
      },
      error: () => this.seriesLoading.set(false),
    });
  }

  private loadMeta(): void {
    this.wellsService.getMeta().subscribe({
      next: (m) => {
        this.lastUpdated.set(m.last_updated);
        this.totalWells.set(m.total_wells);
      },
    });
  }

  private renderChart(): void {
    const canvas = document.getElementById('series-canvas') as HTMLCanvasElement | null;
    if (!canvas) return;

    const s = this.series();
    if (!s || s.series.length === 0) return;

    const ctx = canvas.getContext('2d')!;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const vals = s.series.map((p) => p.v);
    const minV = Math.min(...vals);
    const maxV = Math.max(...vals);
    const range = maxV - minV || 1;
    const padX = 8;
    const padY = 8;

    const toX = (i: number) => padX + (i / (s.series.length - 1)) * (w - 2 * padX);
    const toY = (v: number) => h - padY - ((v - minV) / range) * (h - 2 * padY);

    const bands = s.baseline_bands;
    if (bands) {
      ctx.fillStyle = 'rgba(150,200,255,0.2)';
      ctx.beginPath();
      ctx.rect(padX, toY(bands.p90), w - 2 * padX, toY(bands.p10) - toY(bands.p90));
      ctx.fill();

      ctx.strokeStyle = 'rgba(100,150,220,0.5)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padX, toY(bands.p50));
      ctx.lineTo(w - padX, toY(bands.p50));
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.strokeStyle = '#1a6ebd';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    s.series.forEach((p, i) => {
      if (i === 0) ctx.moveTo(toX(i), toY(p.v));
      else ctx.lineTo(toX(i), toY(p.v));
    });
    ctx.stroke();
  }

  closeChart(): void {
    this.showChart.set(false);
  }

  closePanel(): void {
    this.selectedWell.set(null);
    this.series.set(null);
    this.showChart.set(false);
  }

  formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('nl-NL', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  }

  formatValue(v: number | null): string {
    if (v === null || v === undefined) return '—';
    return v.toFixed(2) + ' m NAP';
  }

  formatPercentile(p: number | null): string {
    if (p === null || p === undefined) return '—';
    return Math.round(p * 100) + 'e percentiel';
  }
}
