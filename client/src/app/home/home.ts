import { Component, ElementRef, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import * as maplibregl from 'maplibre-gl';

import { WellDetail, WellSeries, WellsService } from '../wells.service';
import { WellChartComponent } from '../well-chart-dialog/well-chart-dialog';

const CLASSIFICATION_COLORS: { [key: string]: string } = {
  very_low: '#d73027',
  low: '#fc8d59',
  normal: '#91bfdb',
  high: '#4575b4',
  very_high: '#313695',
  unknown: '#aaaaaa',
};

const CLASSIFICATION_LABELS: { [key: string]: string } = {
  very_low: 'Zeer laag',
  low: 'Laag',
  normal: 'Normaal',
  high: 'Hoog',
  very_high: 'Zeer hoog',
  unknown: 'Onbekend',
};

@Component({
  selector: 'app-home',
  imports: [CommonModule, MatProgressSpinnerModule, MatIconModule, WellChartComponent],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class HomeComponent implements OnInit, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  private wellsService = inject(WellsService);

  map: maplibregl.Map | null = null;
  popup: maplibregl.Popup | null = null;

  loading = signal(true);
  lastUpdated = signal<string | null>(null);
  totalWells = signal(0);

  selectedWell = signal<WellDetail | null>(null);
  seriesLoading = signal(false);
  series = signal<WellSeries | null>(null);
  showChart = signal(false);

  readonly classifications = Object.keys(CLASSIFICATION_LABELS);
  readonly classificationColors = CLASSIFICATION_COLORS;
  readonly classificationLabels = CLASSIFICATION_LABELS;

  ngOnInit(): void {
    this.initMap();
    this.loadMeta();
  }

  ngOnDestroy(): void {
    this.map?.remove();
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
    this.wellsService.getWells().subscribe({
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
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 3, 12, 7],
            'circle-color': [
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
              CLASSIFICATION_COLORS['unknown'],
            ],
            'circle-opacity': ['case', ['get', 'is_stale'], 0.4, 1.0],
            'circle-stroke-width': ['case', ['get', 'is_stale'], 1, 0],
            'circle-stroke-color': '#ffffff',
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

  private onWellClick(e: maplibregl.MapLayerMouseEvent): void {
    const features = e.features;
    if (!features || features.length === 0) return;

    const props = features[0].properties;
    const broId = props['id'];

    this.selectedWell.set(null);
    this.series.set(null);
    this.seriesLoading.set(true);

    this.wellsService.getWellDetail(broId).subscribe({
      next: (detail) => {
        this.selectedWell.set(detail);
        this.loadSeries(broId);
      },
    });

    this.popup?.remove();
  }

  private loadSeries(broId: string): void {
    this.wellsService.getWellSeries(broId).subscribe({
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

  openDetailChart(): void {
    this.showChart.set(true);
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
