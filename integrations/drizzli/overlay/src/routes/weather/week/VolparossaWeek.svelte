<!-- SPDX-License-Identifier: GPL-3.0-only -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { reportPageReady } from '$lib/stores/page-transition.svelte';
  import { fetchProvider, fetchAirQualityProvider } from '$lib/services/volparossa/client.mjs';

  import VolparossaForecast from './VolparossaForecast.svelte';
  import VolparossaAirQuality from './VolparossaAirQuality.svelte';

  let forecast: Awaited<ReturnType<typeof fetchProvider>> | null = $state(null);
  let airQuality: Awaited<ReturnType<typeof fetchAirQualityProvider>> | null = $state(null);
  let loading = $state(true);
  let airQualityLoading = $state(true);
  let error = $state('');
  let airQualityError = $state('');
  let controller: AbortController | null = null;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  let airQualityExpiryTimer: ReturnType<typeof setTimeout> | undefined;
  let requestVersion = 0;
  reportPageReady(() => !loading);

  async function refreshWeather(current: number) {
    controller = new AbortController();
    const active = controller;
    const deadline = setTimeout(() => active.abort(), 185000);
    try {
      const result = await fetchProvider(fetch, active.signal);
      if (current !== requestVersion) return;
      forecast = result;
      expiryTimer = setTimeout(() => {
        if (current !== requestVersion) return;
        forecast = null;
        error = 'This forecast has expired. Refresh to request a valid publication.';
      }, Math.max(0, Date.parse(result.freshness.expires_at) - Date.now()));
    } catch {
      if (current !== requestVersion) return;
      error = 'VOLPAROSSA forecast unavailable. No other weather service was contacted.';
    } finally {
      clearTimeout(deadline);
      if (current === requestVersion) loading = false;
    }
  }

  async function refreshAirQuality(current: number) {
    controller = new AbortController();
    const active = controller;
    const deadline = setTimeout(() => active.abort(), 185000);
    try {
      const result = await fetchAirQualityProvider(fetch, active.signal);
      if (current !== requestVersion) return;
      if (forecast && (result.forecast.area.latitude !== forecast.forecast.area.latitude
          || result.forecast.area.longitude !== forecast.forecast.area.longitude)) {
        throw new Error('AIR_QUALITY_AREA_MISMATCH');
      }
      airQuality = result;
      airQualityExpiryTimer = setTimeout(() => {
        if (current !== requestVersion) return;
        airQuality = null;
        airQualityError = 'This air-quality forecast has expired. Refresh to request a valid publication.';
      }, Math.max(0, Date.parse(result.freshness.expires_at) - Date.now()));
    } catch {
      if (current !== requestVersion) return;
      airQualityError = 'VOLPAROSSA air-quality forecast unavailable or not configured. No other air-quality service was contacted.';
    } finally {
      clearTimeout(deadline);
      if (current === requestVersion) airQualityLoading = false;
    }
  }

  async function refresh() {
    controller?.abort();
    clearTimeout(expiryTimer);
    clearTimeout(airQualityExpiryTimer);
    const current = ++requestVersion;
    loading = airQualityLoading = true;
    forecast = airQuality = null;
    error = airQualityError = '';
    // The bridge admits one operation at a time. Each product keeps its own
    // deadline, error and expiry, including when the preceding request fails.
    await refreshWeather(current);
    if (current !== requestVersion) return;
    await refreshAirQuality(current);
  }

  onMount(() => {
    void refresh();
    return () => {
      ++requestVersion;
      controller?.abort();
      clearTimeout(expiryTimer);
      clearTimeout(airQualityExpiryTimer);
    };
  });
</script>

<svelte:head><title>Drizz.li · VOLPAROSSA forecast</title></svelte:head>

<section aria-label="VOLPAROSSA forecast" class="rounded-2xl border border-border bg-card p-4 md:p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold">VOLPAROSSA · native model forecast</h2>
    <button class="rounded-md border border-border px-4 py-2" onclick={() => void refresh()} disabled={loading || airQualityLoading}>
      {loading || airQualityLoading ? 'Loading…' : 'Refresh'}
    </button>
  </div>
  <p class="mt-3 text-sm text-muted-foreground">
    This development connection reads one public-community forecast configured on this device.
    It does not select your location from the URL, search history or GPS. Change the local
    provider configuration to select another area; browser location selection is unavailable.
  </p>
  {#if loading}<p role="status" class="mt-4">Requesting the configured forecast from the local core…</p>{/if}
  {#if error}<p role="alert" class="mt-4">{error}</p>{/if}
  {#if forecast}
    <VolparossaForecast {forecast} />
  {/if}
</section>

<section aria-label="VOLPAROSSA air quality" class="mt-4 rounded-2xl border border-border bg-card p-4 md:p-6">
  <h2 class="text-xl font-semibold">VOLPAROSSA · particulate forecast</h2>
  <p class="mt-3 text-sm text-muted-foreground">
    A separately configured public-community NOAA forecast for the same area. Its model run,
    native forecast times and expiry are independent of the weather feed; no time points are aligned or interpolated.
  </p>
  {#if airQualityLoading}<p role="status" class="mt-4">{loading ? 'Waiting for the weather request to finish before requesting air quality…' : 'Requesting the configured air-quality forecast from the local core…'}</p>{/if}
  {#if airQualityError}<p role="alert" class="mt-4">{airQualityError}</p>{/if}
  {#if airQuality}
    <VolparossaAirQuality forecast={airQuality} />
  {/if}
</section>
