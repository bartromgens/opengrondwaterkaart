import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export type Classification = 'very_low' | 'low' | 'normal' | 'high' | 'very_high';

export interface WellProperties {
  id: string;
  classification: Classification | null;
  percentile: number | null;
  value_m_nap: number | null;
  measured_on: string | null;
}

export interface WellFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: WellProperties;
}

export interface WellsGeoJSON {
  type: 'FeatureCollection';
  features: WellFeature[];
}

export interface WellDetail {
  bro_id: string;
  tube_number: number;
  nitg_code: string;
  name: string;
  location: { lng: number; lat: number };
  ground_level_m: number | null;
  tube_top_m: number | null;
  screen_top_m: number | null;
  screen_bottom_m: number | null;
  status: {
    value_m_nap: number | null;
    measured_on: string | null;
    percentile: number | null;
    classification: Classification | null;
  };
  baseline: {
    p10: number;
    p50: number;
    p90: number;
    sample_count: number;
    baseline_start: string;
    baseline_end: string;
  } | null;
}

export interface SeriesPoint {
  t: string;
  v: number;
}

export interface WeeklyBaseline {
  week: number;
  p10: number;
  p50: number;
  p90: number;
}

export interface WellSeries {
  bro_id: string;
  series: SeriesPoint[];
  baseline_bands: { p10: number; p50: number; p90: number } | null;
  weekly_baselines: WeeklyBaseline[];
}

export interface MetaResponse {
  last_updated: string | null;
  total_wells: number;
}

@Injectable({ providedIn: 'root' })
export class WellsService {
  private http = inject(HttpClient);

  getWells(date: string, bbox?: [number, number, number, number]): Observable<WellsGeoJSON> {
    let params = new HttpParams().set('date', date);
    if (bbox) {
      params = params.set('bbox', bbox.join(','));
    }
    return this.http.get<WellsGeoJSON>('/api/wells/', { params });
  }

  getWellDetail(broId: string, date: string): Observable<WellDetail> {
    const params = new HttpParams().set('date', date);
    return this.http.get<WellDetail>(`/api/wells/${broId}/`, { params });
  }

  getWellSeries(broId: string, opts?: { full?: boolean; date?: string }): Observable<WellSeries> {
    let params = new HttpParams();
    if (opts?.full) {
      params = params.set('full', '1');
    }
    if (opts?.date) {
      params = params.set('date', opts.date);
    }
    return this.http.get<WellSeries>(`/api/wells/${broId}/series/`, { params });
  }

  getMeta(): Observable<MetaResponse> {
    return this.http.get<MetaResponse>('/api/meta/');
  }
}
