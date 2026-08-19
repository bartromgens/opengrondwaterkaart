import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  MatAutocompleteModule,
  MatAutocompleteSelectedEvent,
} from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';
import * as maplibregl from 'maplibre-gl';

import {
  MeasurementFrequency,
  MonitoringNetworkListItem,
  WellDetail,
  WellSeries,
  WellsGeoJSON,
  WellsService,
} from '../wells.service';
import { WellChartComponent } from '../well-chart-dialog/well-chart-dialog';
import { TrackingService } from '../tracking.service';
import { SeoService } from '../seo.service';

const CLASSIFICATION_COLORS: Record<string, string> = {
  very_low: '#d73027',
  low: '#fc8d59',
  normal: '#91bfdb',
  high: '#4575b4',
  very_high: '#313695',
};

const NO_DATA_COLOR = '#cccccc';
const SELECTED_WELL_STROKE = '#111111';

const WELLS_LAYER = 'wells-circle';
const WELLS_SELECTED_LAYER = 'wells-selected';

const WELL_CIRCLE_COLOR: maplibregl.ExpressionSpecification = [
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
];

const WELL_CIRCLE_RADIUS: maplibregl.ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  6,
  3,
  12,
  7,
];

const SELECTED_WELL_CIRCLE_RADIUS: maplibregl.ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  6,
  6,
  12,
  12,
];

const CLASSIFICATION_LABELS: Record<string, string> = {
  very_low: 'Zeer laag',
  low: 'Laag',
  normal: 'Normaal',
  high: 'Hoog',
  very_high: 'Zeer hoog',
};

const INITIAL_FUNCTION_LABELS: Record<string, string> = {
  stand: 'Waterstand',
  kwaliteit: 'Kwaliteit',
  combinatie: 'Combinatie',
  onbekend: 'Onbekend',
};

const GROUNDWATER_ASPECT_LABELS: Record<string, string> = {
  kwantiteit: 'Kwantiteit',
  kwaliteit: 'Kwaliteit',
  combinatie: 'Combinatie',
};

const FREQUENCY_LABELS: Record<MeasurementFrequency, string> = {
  daily: 'Dagelijks',
  weekly: 'Wekelijks',
  monthly: 'Maandelijks',
  quarterly: 'Per kwartaal',
  yearly: 'Jaarlijks',
  irregular: 'Onregelmatig',
};

const FREQUENCY_OPTIONS: MeasurementFrequency[] = [
  'daily',
  'weekly',
  'monthly',
  'quarterly',
  'yearly',
  'irregular',
];

type FrequencyFilter = MeasurementFrequency | 'unknown';

interface WellSpec {
  label: string;
  value: string;
}

const NO_VALUE = '—';

function formatIsoDate(iso: string | null): string {
  if (!iso) return NO_VALUE;
  return new Date(iso).toLocaleDateString('nl-NL', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function formatMeters(v: number | null): string {
  if (v === null || v === undefined) return NO_VALUE;
  return v.toFixed(2) + ' m NAP';
}

function formatDepthRange(top: number | null, bottom: number | null): string {
  if (top === null || bottom === null) return formatMeters(top ?? bottom);
  return `${top.toFixed(2)} – ${bottom.toFixed(2)} m NAP`;
}

function formatDateRange(from: string | null, to: string | null): string {
  if (!from) return `tot ${formatIsoDate(to)}`;
  if (!to) return `vanaf ${formatIsoDate(from)}`;
  return `${formatIsoDate(from)} – ${formatIsoDate(to)}`;
}

function formatInitialFunction(code: string | null): string {
  if (!code) return NO_VALUE;
  return INITIAL_FUNCTION_LABELS[code] ?? code;
}

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
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    MatSliderModule,
    WellChartComponent,
  ],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class HomeComponent implements OnInit, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  private wellsService = inject(WellsService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private tracking = inject(TrackingService);
  private seo = inject(SeoService);
  private dateChange$ = new Subject<void>();
  private programmaticMove = false;

  map: maplibregl.Map | null = null;
  popup: maplibregl.Popup | null = null;
  private highlightedWellId: string | null = null;

  loading = signal(true);
  dateLoading = signal(false);
  lastUpdated = signal<string | null>(null);
  totalWells = signal(0);

  networks = signal<MonitoringNetworkListItem[]>([]);
  networkInput = signal('');
  selectedNetworkId = signal<string | null>(null);
  selectedFrequency = signal<FrequencyFilter | null>(null);

  readonly frequencyOptions = FREQUENCY_OPTIONS;
  readonly frequencyLabels = FREQUENCY_LABELS;

  readonly selectedNetwork = computed(() => {
    const id = this.selectedNetworkId();
    return this.networks().find((network) => network.bro_id === id) ?? null;
  });

  readonly filteredNetworks = computed(() => {
    const query = this.networkInput().trim().toLowerCase();
    const list = this.networks();
    if (!query) return list;
    return list.filter(
      (network) =>
        network.name.toLowerCase().includes(query) || network.bro_id.toLowerCase().includes(query),
    );
  });

  selectedWell = signal<WellDetail | null>(null);
  seriesLoading = signal(false);
  series = signal<WellSeries | null>(null);
  showChart = signal(false);

  readonly wellSpecs = computed<WellSpec[]>(() => {
    const well = this.selectedWell();
    if (!well) return [];

    const specs: WellSpec[] = [];
    if (well.well_construction_date) {
      specs.push({ label: 'Ingericht', value: formatIsoDate(well.well_construction_date) });
    }
    if (well.initial_function) {
      specs.push({ label: 'Functie', value: formatInitialFunction(well.initial_function) });
    }
    if (well.screen_top_m !== null || well.screen_bottom_m !== null) {
      specs.push({
        label: 'Filter',
        value: formatDepthRange(well.screen_top_m, well.screen_bottom_m),
      });
    }
    if (well.number_of_monitoring_tubes > 1) {
      specs.push({
        label: 'Buis',
        value: `${well.tube_number} van ${well.number_of_monitoring_tubes}`,
      });
    }
    if (well.research_first_date || well.research_last_date) {
      specs.push({
        label: 'Meetreeks',
        value: formatDateRange(well.research_first_date, well.research_last_date),
      });
    }
    return specs;
  });

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
    this.seo.updateMetadata({
      title: 'OpenGrondWaterKaart — Actuele grondwaterstanden in Nederland',
      description:
        'Interactieve kaart met actuele grondwaterstanden in Nederland, gebaseerd op open data van BRO en PDOK. Bekijk grondwaterpeilen per put en per dag.',
      path: '/',
    });
    this.initMap();
    this.loadMeta();
    this.loadNetworks();
    this.selectedNetworkId.set(this.route.snapshot.queryParamMap.get('network'));
    this.selectedFrequency.set(
      this.parseFrequencyParam(this.route.snapshot.queryParamMap.get('frequency')),
    );

    this.route.queryParamMap.subscribe((params) => {
      const broId = params.get('well');
      if (broId) {
        if (this.selectedWell()?.bro_id !== broId) {
          this.openWell(broId);
        }
      } else if (this.selectedWell() || this.highlightedWellId) {
        this.closePanelState();
      }

      const networkId = params.get('network');
      if (networkId !== this.selectedNetworkId()) {
        this.applyNetworkFilter(networkId, { fit: !!networkId });
      }

      const frequency = this.parseFrequencyParam(params.get('frequency'));
      if (frequency !== this.selectedFrequency()) {
        this.applyFrequencyFilter(frequency, { fit: !!frequency });
      }
    });

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
    this.map.on('zoomend', () => {
      if (this.programmaticMove || !this.map) return;
      this.tracking.trackEvent(
        'Map Interaction',
        'Zoom',
        `Level ${Math.round(this.map.getZoom())}`,
      );
    });
    this.map.on('dragend', () => {
      this.tracking.trackEvent('Map Interaction', 'Drag');
    });
  }

  private loadWells(): void {
    this.wellsService.getWells(this.selectedDateIso, this.wellsQuery()).subscribe({
      next: (geojson) => {
        this.loading.set(false);
        const map = this.map!;

        map.addSource('wells', {
          type: 'geojson',
          data: geojson as any,
        });

        map.addLayer({
          id: WELLS_LAYER,
          type: 'circle',
          source: 'wells',
          layout: {
            'circle-sort-key': ['case', ['==', ['get', 'classification'], null], 0, 1],
          },
          paint: {
            'circle-radius': WELL_CIRCLE_RADIUS,
            'circle-color': WELL_CIRCLE_COLOR,
            'circle-opacity': 1.0,
            'circle-stroke-width': 0,
          },
        });

        map.addLayer({
          id: WELLS_SELECTED_LAYER,
          type: 'circle',
          source: 'wells',
          filter: ['==', ['get', 'id'], ''],
          paint: {
            'circle-radius': SELECTED_WELL_CIRCLE_RADIUS,
            'circle-color': WELL_CIRCLE_COLOR,
            'circle-opacity': 1.0,
            'circle-stroke-width': 2.5,
            'circle-stroke-color': SELECTED_WELL_STROKE,
          },
        });

        for (const layerId of [WELLS_LAYER, WELLS_SELECTED_LAYER]) {
          map.on('click', layerId, (e: maplibregl.MapLayerMouseEvent) => this.onWellClick(e));
          map.on('mouseenter', layerId, () => {
            map.getCanvas().style.cursor = 'pointer';
          });
          map.on('mouseleave', layerId, () => {
            map.getCanvas().style.cursor = '';
          });
        }

        this.highlightWell(this.highlightedWellId);

        const well = this.selectedWell();
        if (well) {
          this.flyToWell(well);
        } else if (this.hasActiveMapFilter()) {
          this.fitToWells(geojson);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  private wellsQuery(): {
    network?: string | null;
    frequency?: FrequencyFilter | null;
  } {
    return {
      network: this.selectedNetworkId(),
      frequency: this.selectedFrequency(),
    };
  }

  private hasActiveMapFilter(): boolean {
    return !!this.selectedNetworkId() || !!this.selectedFrequency();
  }

  private parseFrequencyParam(raw: string | null): FrequencyFilter | null {
    if (!raw) return null;
    if (raw === 'unknown') return 'unknown';
    if ((FREQUENCY_OPTIONS as readonly string[]).includes(raw)) {
      return raw as MeasurementFrequency;
    }
    return null;
  }

  private reloadWells(opts?: { fit?: boolean }): void {
    const source = this.map?.getSource('wells') as maplibregl.GeoJSONSource | undefined;
    if (!source) return;

    this.dateLoading.set(true);
    this.wellsService.getWells(this.selectedDateIso, this.wellsQuery()).subscribe({
      next: (geojson) => {
        source.setData(geojson as any);
        this.dateLoading.set(false);
        if (opts?.fit) {
          this.fitToWells(geojson);
        }
      },
      error: () => this.dateLoading.set(false),
    });
  }

  private onDateChanged(): void {
    this.reloadWells();

    const well = this.selectedWell();
    if (well) {
      this.wellsService.getWellDetail(well.bro_id, this.selectedDateIso).subscribe({
        next: (detail) => this.selectedWell.set(detail),
      });
    }
  }

  private applyNetworkFilter(networkId: string | null, opts?: { fit?: boolean }): void {
    this.selectedNetworkId.set(networkId);
    const selected = this.selectedNetwork();
    this.networkInput.set(selected?.name ?? '');
    this.reloadWells(opts);
  }

  private applyFrequencyFilter(frequency: FrequencyFilter | null, opts?: { fit?: boolean }): void {
    this.selectedFrequency.set(frequency);
    this.reloadWells(opts);
  }

  private fitToWells(geojson: WellsGeoJSON): void {
    if (!this.map || geojson.features.length === 0) return;

    this.programmaticMove = true;
    this.map.once('moveend', () => {
      this.programmaticMove = false;
    });

    if (geojson.features.length === 1) {
      const [lng, lat] = geojson.features[0].geometry.coordinates;
      this.map.flyTo({
        center: [lng, lat],
        zoom: Math.max(this.map.getZoom(), 10),
      });
      return;
    }

    const bounds = new maplibregl.LngLatBounds();
    for (const feature of geojson.features) {
      bounds.extend(feature.geometry.coordinates as [number, number]);
    }
    this.map.fitBounds(bounds, { padding: 80, maxZoom: 12, duration: 800 });
  }

  onNetworkInput(value: string | MonitoringNetworkListItem): void {
    if (typeof value === 'string') {
      this.networkInput.set(value);
      return;
    }
    if (value) {
      this.networkInput.set(value.name);
    }
  }

  onNetworkSelected(event: MatAutocompleteSelectedEvent): void {
    const network = event.option.value as MonitoringNetworkListItem;
    this.networkInput.set(network.name);
    this.tracking.trackEvent('Map Interaction', 'Network Filter', network.bro_id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { network: network.bro_id },
      queryParamsHandling: 'merge',
    });
  }

  clearNetwork(event?: Event): void {
    event?.stopPropagation();
    this.networkInput.set('');
    this.tracking.trackEvent('Map Interaction', 'Network Filter', 'all');
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { network: null },
      queryParamsHandling: 'merge',
    });
  }

  onFrequencySelected(frequency: FrequencyFilter | null): void {
    this.tracking.trackEvent('Map Interaction', 'Frequency Filter', frequency ?? 'all');
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { frequency: frequency },
      queryParamsHandling: 'merge',
    });
  }

  clearFrequency(): void {
    this.onFrequencySelected(null);
  }

  readonly displayNetwork = (network: MonitoringNetworkListItem | string | null): string => {
    if (!network) return '';
    if (typeof network === 'string') return network;
    return network.name;
  };

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

    this.tracking.trackEvent('Map Interaction', 'Well Click', broId);
    this.highlightWell(broId);

    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { well: broId },
      queryParamsHandling: 'merge',
    });

    this.popup?.remove();
  }

  private openWell(broId: string): void {
    this.highlightWell(broId);
    this.selectedWell.set(null);
    this.series.set(null);
    this.seriesLoading.set(true);

    this.wellsService.getWellDetail(broId, this.selectedDateIso).subscribe({
      next: (detail) => {
        this.selectedWell.set(detail);
        this.showChart.set(true);
        this.loadSeries(broId);
        this.flyToWell(detail);
      },
      error: () => {
        this.seriesLoading.set(false);
        void this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { well: null },
          queryParamsHandling: 'merge',
        });
      },
    });
  }

  private flyToWell(well: WellDetail): void {
    if (!this.map) return;
    this.programmaticMove = true;
    this.map.once('moveend', () => {
      this.programmaticMove = false;
    });
    this.map.flyTo({
      center: [well.location.lng, well.location.lat],
      zoom: Math.max(this.map.getZoom(), 12),
    });
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

  private loadNetworks(): void {
    this.wellsService.getNetworks().subscribe({
      next: (response) => {
        this.networks.set(response.results);
        const selected = this.selectedNetwork();
        if (selected) {
          this.networkInput.set(selected.name);
        }
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
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { well: null },
      queryParamsHandling: 'merge',
    });
  }

  private closePanelState(): void {
    this.highlightWell(null);
    this.selectedWell.set(null);
    this.series.set(null);
    this.showChart.set(false);
    this.seriesLoading.set(false);
  }

  private highlightWell(broId: string | null): void {
    this.highlightedWellId = broId;
    const map = this.map;
    if (!map?.getLayer(WELLS_SELECTED_LAYER)) return;

    if (broId) {
      map.setFilter(WELLS_LAYER, ['!=', ['get', 'id'], broId]);
      map.setFilter(WELLS_SELECTED_LAYER, ['==', ['get', 'id'], broId]);
      return;
    }

    map.setFilter(WELLS_LAYER, ['has', 'id']);
    map.setFilter(WELLS_SELECTED_LAYER, ['==', ['get', 'id'], '']);
  }

  formatDate(iso: string | null): string {
    return formatIsoDate(iso);
  }

  formatValue(v: number | null): string {
    return formatMeters(v);
  }

  formatPercentile(p: number | null): string {
    if (p === null || p === undefined) return NO_VALUE;
    return Math.round(p * 100) + 'e percentiel';
  }

  formatGroundwaterAspect(code: string | null): string {
    if (!code) return '';
    return GROUNDWATER_ASPECT_LABELS[code] ?? code;
  }
}
