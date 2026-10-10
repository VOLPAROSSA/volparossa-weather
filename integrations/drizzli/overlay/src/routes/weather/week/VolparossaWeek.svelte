<!-- SPDX-License-Identifier: GPL-3.0-only -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { reportPageReady } from '$lib/stores/page-transition.svelte';
  import { fetchProvider } from '$lib/services/volparossa/client.mjs';

  import VolparossaForecast from './VolparossaForecast.svelte';

  let forecast: Awaited<ReturnType<typeof fetchProvider>> | null = $state(null);
  let loading = $state(true);
  let error = $state('');
  let controller: AbortController | null = null;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  let requestVersion = 0;
  reportPageReady(() => !loading);

  async function refresh() {
    controller?.abort();
    clearTimeout(expiryTimer);
    const current = ++requestVersion;
    controller = new AbortController();
    const active = controller;
    const deadline = setTimeout(() => active.abort(), 185000);
    loading = true;
    forecast = null;
    error = '';
    try {
      const result = await fetchProvider(fetch, active.signal);
      if (current !== requestVersion) return;
      forecast = result;
      expiryTimer = setTimeout(() => {
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

  onMount(() => {
    void refresh();
    return () => { ++requestVersion; controller?.abort(); clearTimeout(expiryTimer); };
  });
</script>

<svelte:head><title>Drizz.li · VOLPAROSSA forecast</title></svelte:head>

<section aria-label="VOLPAROSSA forecast" class="rounded-2xl border border-border bg-card p-4 md:p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold">VOLPAROSSA · native model forecast</h2>
    <button class="rounded-md border border-border px-4 py-2" onclick={() => void refresh()} disabled={loading}>
      {loading ? 'Loading…' : 'Refresh'}
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
