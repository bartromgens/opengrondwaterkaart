import { Component, OnInit, OnChanges, inject, input, output, signal } from '@angular/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsCoreOption } from 'echarts/core';

import { WellDetail, WellSeries, WeeklyBaseline, WellsService } from '../wells.service';

function getIsoWeek(date: Date): number {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

type BaselinePoint = [number, number] | [number, null];

function buildBaselineSeries(
  startDate: Date,
  endDate: Date,
  weekMap: Map<number, WeeklyBaseline>,
): { p10: BaselinePoint[]; p50: BaselinePoint[]; p90Band: BaselinePoint[] } {
  const p10: BaselinePoint[] = [];
  const p50: BaselinePoint[] = [];
  const p90Band: BaselinePoint[] = [];

  const cur = new Date(startDate);
  cur.setUTCHours(0, 0, 0, 0);
  const end = new Date(endDate);
  end.setUTCHours(0, 0, 0, 0);

  while (cur <= end) {
    const week = getIsoWeek(cur);
    const bl = weekMap.get(week) ?? weekMap.get(week === 53 ? 52 : week);
    const ts = cur.getTime();
    if (bl) {
      p10.push([ts, bl.p10]);
      p50.push([ts, bl.p50]);
      p90Band.push([ts, bl.p90 - bl.p10]);
    } else {
      p10.push([ts, null]);
      p50.push([ts, null]);
      p90Band.push([ts, null]);
    }
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return { p10, p50, p90Band };
}

@Component({
  selector: 'app-well-chart',
  imports: [MatProgressSpinnerModule, MatIconModule, NgxEchartsDirective],
  templateUrl: './well-chart-dialog.html',
  styleUrl: './well-chart-dialog.scss',
})
export class WellChartComponent implements OnInit, OnChanges {
  private wellsService = inject(WellsService);

  readonly well = input.required<WellDetail>();
  readonly closed = output<void>();

  loading = signal(true);
  chartOption = signal<EChartsCoreOption | null>(null);

  ngOnInit(): void {
    this.fetchChart();
  }

  ngOnChanges(): void {
    this.loading.set(true);
    this.chartOption.set(null);
    this.fetchChart();
  }

  close(): void {
    this.closed.emit();
  }

  private fetchChart(): void {
    this.wellsService.getWellSeries(this.well().bro_id, { full: true }).subscribe({
      next: (series) => this.buildChart(series),
      error: () => this.loading.set(false),
    });
  }

  private buildChart(series: WellSeries): void {
    const well = this.well();
    const weekMap = new Map<number, WeeklyBaseline>(
      series.weekly_baselines.map((b) => [b.week, b]),
    );

    const GAP_THRESHOLD_MS = 45 * 24 * 60 * 60 * 1000;
    const raw: [number, number][] = series.series
      .map((p): [number, number] => [new Date(p.t).getTime(), p.v])
      .sort((a, b) => a[0] - b[0]);

    const measurements: ([number, number] | [number, null])[] = [];
    for (let i = 0; i < raw.length; i++) {
      measurements.push(raw[i]);
      if (i < raw.length - 1 && raw[i + 1][0] - raw[i][0] > GAP_THRESHOLD_MS) {
        measurements.push([Math.round((raw[i][0] + raw[i + 1][0]) / 2), null]);
      }
    }

    const now = Date.now();

    let baselineP10: BaselinePoint[] = [];
    let baselineP50: BaselinePoint[] = [];
    let baselineP90Band: BaselinePoint[] = [];

    if (weekMap.size > 0 && raw.length > 0) {
      const built = buildBaselineSeries(new Date(raw[0][0]), new Date(now), weekMap);
      baselineP10 = built.p10;
      baselineP50 = built.p50;
      baselineP90Band = built.p90Band;
    }

    const gl = well.ground_level_m;
    const useDepth = gl != null;

    // In depth mode transform all y-values: depth = ground_level_m - m_nap
    // Band floor becomes the shallower P90 edge; spread stays the same (p90-p10).
    const toDepth = (v: number) => gl! - v;
    const transformPoints = (pts: BaselinePoint[]): BaselinePoint[] =>
      useDepth ? pts.map((p) => (p[1] == null ? [p[0], null] : [p[0], toDepth(p[1])])) : pts;

    const plotMeasurements: ([number, number] | [number, null])[] = useDepth
      ? measurements.map((p) => (p[1] == null ? [p[0], null] : [p[0], toDepth(p[1])]))
      : measurements;

    // For the band in depth mode: floor = depth(p90) = depth(p10) - spread,
    // i.e. ground_level_m - (p10 + p90Band). Spread stays unchanged.
    const plotFloor: BaselinePoint[] = useDepth
      ? baselineP10.map((p, i): BaselinePoint => {
          if (p[1] == null) return [p[0], null];
          const spread = baselineP90Band[i]?.[1] ?? 0;
          return [p[0], toDepth(p[1] + (spread as number))];
        })
      : baselineP10;
    const plotSpread: BaselinePoint[] = baselineP90Band; // spread unchanged
    const plotP50: BaselinePoint[] = transformPoints(baselineP50);

    // y-axis bounds
    const plotFloorNonNull = plotFloor.filter((p) => p[1] != null) as [number, number][];
    const plotSpreadNonNull = plotSpread.filter((p) => p[1] != null) as [number, number][];
    const rawDepthValues = raw.map((p) => (useDepth ? toDepth(p[1]) : p[1]));
    const allYValues: number[] = [
      ...rawDepthValues,
      ...plotFloorNonNull.map((p) => p[1]),
      ...plotFloorNonNull.map((p, i) => p[1] + (plotSpreadNonNull[i]?.[1] ?? 0)),
      ...(useDepth ? [0] : [gl ?? 0]), // always include maaiveld (depth=0 or gl m NAP)
    ];
    const yMin = Math.min(...allYValues);
    const yMax = Math.max(...allYValues);
    const yPad = (yMax - yMin) * 0.05 || 0.1;

    // Tooltip shows depth + m NAP when in depth mode, m NAP only otherwise
    const tooltipFormatter = (params: any[]) => {
      if (!params?.length) return '';
      const date = new Date(params[0].axisValue).toLocaleDateString('nl-NL', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      });
      let html = `<div style="font-weight:600;margin-bottom:4px">${date}</div>`;
      for (const p of params) {
        if (p.seriesName === 'Grondwaterstand' && p.value?.[1] != null) {
          const depthVal = p.value[1] as number;
          const napVal = useDepth ? (gl! - depthVal).toFixed(3) : depthVal.toFixed(3);
          const depthStr = useDepth ? ` / ${depthVal.toFixed(2)} m diepte` : '';
          html += `<div>${p.marker} ${p.seriesName}: <b>${napVal} m NAP${depthStr}</b></div>`;
        } else if (p.seriesName === 'Mediaan (seizoen)' && p.value?.[1] != null) {
          const depthVal = p.value[1] as number;
          const napVal = useDepth ? (gl! - depthVal).toFixed(3) : depthVal.toFixed(3);
          html += `<div>${p.marker} ${p.seriesName}: <b>${napVal} m NAP</b></div>`;
        }
      }
      return html;
    };

    const option: EChartsCoreOption = {
      animation: false,
      backgroundColor: 'transparent',
      grid: { top: 40, right: 80, bottom: 80, left: 60 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: '#999' } },
        formatter: tooltipFormatter,
      },
      legend: {
        top: 8,
        data: ['Grondwaterstand', 'Mediaan (seizoen)', 'Bandbreedte P10–P90'],
        textStyle: { fontSize: 11 },
      },
      xAxis: {
        type: 'time',
        min:
          raw.length > 0
            ? (() => {
                const d = new Date(raw[0][0]);
                d.setUTCHours(0, 0, 0, 0);
                return d.getTime();
              })()
            : undefined,
        max: now,
        axisLabel: { fontSize: 11 },
      },
      yAxis: [
        {
          type: 'value',
          name: useDepth ? 'Diepte onder maaiveld (m)' : 'm NAP',
          inverse: useDepth,
          min: yMin - yPad,
          max: yMax + yPad,
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11, formatter: (v: number) => v.toFixed(2) },
        },
        {
          type: 'value',
          name: useDepth ? 'm NAP' : 'Diepte onder maaiveld (m)',
          position: 'right',
          inverse: useDepth,
          min: yMin - yPad,
          max: yMax + yPad,
          show: gl != null,
          splitLine: { show: false },
          nameTextStyle: { fontSize: 11 },
          axisLabel: {
            fontSize: 11,
            formatter: (v: number) =>
              useDepth ? (gl! - v).toFixed(2) : gl != null ? (gl - v).toFixed(2) : '',
          },
        },
      ],
      dataZoom: [
        { type: 'inside', start: 0, end: 100, filterMode: 'none' },
        {
          type: 'slider',
          bottom: 4,
          height: 40,
          start: 0,
          end: 100,
          filterMode: 'none',
          labelFormatter: (v: number) =>
            new Date(v).toLocaleDateString('nl-NL', { month: 'short', year: 'numeric' }),
        },
      ],
      series: [
        {
          name: 'P10 bodem',
          type: 'line',
          data: plotFloor,
          stack: 'band',
          stackStrategy: 'all',
          connectNulls: false,
          symbol: 'none',
          lineStyle: { opacity: 0 },
          itemStyle: { color: 'transparent' },
          areaStyle: { color: 'transparent' },
          tooltip: { show: false },
          legendHoverLink: false,
          showInLegend: false,
        } as any,
        {
          name: 'Bandbreedte P10–P90',
          type: 'line',
          data: plotSpread,
          stack: 'band',
          stackStrategy: 'all',
          connectNulls: false,
          symbol: 'none',
          lineStyle: { opacity: 0 },
          itemStyle: { color: 'rgba(100,150,220,0.6)' },
          areaStyle: { color: 'rgba(100,150,220,0.18)' },
        } as any,
        {
          name: 'Mediaan (seizoen)',
          type: 'line',
          data: plotP50,
          connectNulls: false,
          symbol: 'none',
          lineStyle: { color: 'rgba(100,150,220,0.7)', type: 'dashed', width: 1.5 },
          itemStyle: { color: 'rgba(100,150,220,0.7)' },
        },
        {
          name: 'Grondwaterstand',
          type: 'line',
          data: plotMeasurements,
          connectNulls: false,
          symbol: 'none',
          lineStyle: { color: '#1a6ebd', width: 1.5 },
          itemStyle: { color: '#1a6ebd' },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [
              {
                xAxis: now,
                lineStyle: { color: '#e55', type: 'solid', width: 1.5 },
                label: {
                  formatter: 'Vandaag',
                  position: 'insideEndTop',
                  fontSize: 10,
                  color: '#e55',
                },
              },
              ...(gl != null
                ? [
                    {
                      yAxis: useDepth ? 0 : gl,
                      lineStyle: { color: '#7a5c2e', type: 'dashed', width: 1.5 },
                      label: {
                        formatter: `Maaiveld (${gl.toFixed(2)} m NAP)`,
                        position: 'insideEndBottom',
                        fontSize: 10,
                        color: '#7a5c2e',
                      },
                    },
                  ]
                : []),
            ],
          },
        },
      ],
    };

    this.chartOption.set(option);
    this.loading.set(false);
  }
}
