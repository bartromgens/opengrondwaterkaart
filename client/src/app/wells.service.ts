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

export interface OrganizationInfo {
  kvk: string;
  name: string | null;
  kvk_url: string;
}

export interface MonitoringNetworkInfo {
  bro_id: string;
  name: string;
  monitoring_purpose: string | null;
  groundwater_aspect: string | null;
  bro_object_url: string | null;
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
  well_construction_date: string | null;
  initial_function: string | null;
  number_of_monitoring_tubes: number;
  research_first_date: string | null;
  research_last_date: string | null;
  monitoring_networks: MonitoringNetworkInfo[];
  owner: OrganizationInfo | null;
  bronhouder: OrganizationInfo | null;
  bro_object_url: string | null;
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

export type MeasurementFrequency =
  | 'daily'
  | 'weekly'
  | 'monthly'
  | 'quarterly'
  | 'yearly'
  | 'irregular';

export interface WellOverviewNetwork {
  bro_id: string;
  name: string;
}

export interface WellOverviewRow {
  bro_id: string;
  nitg_code: string;
  name: string;
  well_construction_date: string | null;
  initial_function: string | null;
  number_of_monitoring_tubes: number;
  research_first_date: string | null;
  research_last_date: string | null;
  monitoring_networks: WellOverviewNetwork[];
  first_measured_on: string | null;
  last_measured_on: string | null;
  measurement_count: number;
  frequency: MeasurementFrequency | null;
}

export interface WellOverviewResponse {
  count: number;
  page: number;
  page_size: number;
  ordering: string;
  results: WellOverviewRow[];
}

export type FrequencyDistribution = Record<MeasurementFrequency | 'unknown' | 'no_data', number>;

export interface AgeDistributionBucket {
  key: string;
  label: string;
  count: number;
}

export interface WellsStats {
  total_wells: number;
  wells_with_data: number;
  wells_without_data: number;
  newest_measured_on: string | null;
  newest_measurement_age_days: number | null;
  frequency_distribution: FrequencyDistribution;
  latest_measurement_age_distribution: AgeDistributionBucket[];
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
    return this.http.get<WellDetail>(`/api/wells/${encodeURIComponent(broId)}/`, { params });
  }

  getWellSeries(broId: string, opts?: { full?: boolean; date?: string }): Observable<WellSeries> {
    let params = new HttpParams();
    if (opts?.full) {
      params = params.set('full', '1');
    }
    if (opts?.date) {
      params = params.set('date', opts.date);
    }
    return this.http.get<WellSeries>(`/api/wells/${encodeURIComponent(broId)}/series/`, { params });
  }

  getMeta(): Observable<MetaResponse> {
    return this.http.get<MetaResponse>('/api/meta/');
  }

  getWellsOverview(opts: {
    page: number;
    pageSize: number;
    ordering: string;
  }): Observable<WellOverviewResponse> {
    const params = new HttpParams()
      .set('page', opts.page)
      .set('page_size', opts.pageSize)
      .set('ordering', opts.ordering);
    return this.http.get<WellOverviewResponse>('/api/wells/overview/', { params });
  }

  getWellsStats(): Observable<WellsStats> {
    return this.http.get<WellsStats>('/api/wells/stats/');
  }
}
