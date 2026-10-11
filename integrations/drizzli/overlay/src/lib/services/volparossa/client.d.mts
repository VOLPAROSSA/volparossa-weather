// SPDX-License-Identifier: GPL-3.0-only
export interface DisplayForecast {
  timeline: { valid_at: string[] };
  series: {
    variable: string;
    availability: 'supported' | 'unavailable';
    unit: string | null;
    values: (number | null)[] | null;
    value_status: string[] | null;
    statistic?: 'accumulation';
    accumulation_windows?: { start_at: string; end_at: string }[];
  }[];
  forecast: {
    area: { latitude: number; longitude: number };
    source: { model: string; model_run_at: string; attribution: string; license: string; license_url: string; changes: string };
  };
  freshness: { expires_at: string };
}
export const ENDPOINT: string;
export const MAX_PROVIDER_BYTES: number;
export function validateProvider(value: unknown, now?: string): DisplayForecast;
export function fetchProvider(fetcher: typeof fetch, signal: AbortSignal): Promise<DisplayForecast>;
export function displayValue(forecast: DisplayForecast, variable: string, index: number): string;
export function hasSupportedPrecipitation(forecast: DisplayForecast): boolean;
export function displayAccumulationWindow(forecast: DisplayForecast, index: number): string;
