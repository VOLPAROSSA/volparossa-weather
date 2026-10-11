<!-- SPDX-License-Identifier: GPL-3.0-only -->
<script lang="ts">
  import { displayValue } from '../../../lib/services/volparossa/client.mjs';
  import type { DisplayAirQualityForecast } from '../../../lib/services/volparossa/client.mjs';
  let { forecast }: { forecast: DisplayAirQualityForecast } = $props();
</script>

<dl class="mt-4 grid gap-2 text-sm">
  <div><dt class="font-semibold">Configured air-quality area</dt><dd>{forecast.forecast.area.latitude}° latitude, {forecast.forecast.area.longitude}° longitude</dd></div>
  <div><dt class="font-semibold">Air-quality model and run</dt><dd>{forecast.forecast.source.model} · {forecast.forecast.source.model_run_at}</dd></div>
  <div data-testid="air-quality-expiry"><dt class="font-semibold">Valid air-quality publication until</dt><dd>{forecast.freshness.expires_at}</dd></div>
</dl>
<p class="mt-4 text-sm" data-testid="air-quality-scope">
  Instantaneous particulate forecasts at native NOAA UTC timestamps, not AQI or current observations.
  No health category, daily average, hourly interpolation or comparison with an observation is inferred.
</p>
<div class="mt-4 overflow-x-auto">
  <table class="w-full text-left text-sm">
    <caption class="mb-2 text-left">Native particulate forecast points · UTC</caption>
    <thead><tr><th class="p-2">Valid time</th><th class="p-2">PM2.5 (µg/m³)</th><th class="p-2">PM10 (µg/m³)</th></tr></thead>
    <tbody>
      {#each forecast.timeline.valid_at as time, i}
        <tr class="border-t border-border"><th class="p-2 font-normal">{time}</th>
          <td class="p-2">{displayValue(forecast, 'pm2_5', i)}</td>
          <td class="p-2">{displayValue(forecast, 'pm10', i)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
<p class="mt-4 text-sm">Missing values mean not available, not zero or clean air. Other pollutants and AQI are not available through this particulate feed.</p>
<p class="mt-3 text-sm text-muted-foreground" data-testid="air-quality-source">
  <a class="underline" href="https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gefs_aero.php" target="_blank" rel="noopener noreferrer">{forecast.forecast.source.attribution}</a>
  · <a class="underline" href={forecast.forecast.source.license_url} target="_blank" rel="noopener noreferrer">{forecast.forecast.source.license}</a>
  · Processing: {forecast.forecast.source.changes}
  This modified presentation is not an official NOAA product or endorsement.
  Local core delivery does not attest the original source or establish forecast accuracy.
</p>
