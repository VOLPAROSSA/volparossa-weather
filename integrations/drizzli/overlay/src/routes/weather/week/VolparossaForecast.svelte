<!-- SPDX-License-Identifier: GPL-3.0-only -->
<script lang="ts">
  import { displayValue, hasSupportedPrecipitation, displayAccumulationWindow } from '../../../lib/services/volparossa/client.mjs';
  import type { DisplayForecast } from '../../../lib/services/volparossa/client.mjs';
  let { forecast }: { forecast: DisplayForecast } = $props();
  const precipitationSupported = $derived(hasSupportedPrecipitation(forecast));
</script>

    <dl class="mt-4 grid gap-2 text-sm">
      <div><dt class="font-semibold">Configured forecast area</dt><dd>{forecast.forecast.area.latitude}° latitude, {forecast.forecast.area.longitude}° longitude</dd></div>
      <div><dt class="font-semibold">Model and run</dt><dd>{forecast.forecast.source.model} · {forecast.forecast.source.model_run_at}</dd></div>
      <div><dt class="font-semibold">Valid publication until</dt><dd>{forecast.freshness.expires_at}</dd></div>
    </dl>
    <p class="mt-4 text-sm">Forecast points, not current observations. Native UTC timestamps and units are retained; no interpolation or daily extrema are invented.</p>
    <div class="mt-4 overflow-x-auto">
      <table class="w-full text-left text-sm">
        <caption class="mb-2 text-left">Available model points · UTC</caption>
        <thead><tr><th class="p-2">Valid time</th><th class="p-2">Temperature (°C)</th><th class="p-2">Wind (m/s)</th><th class="p-2">Wind from (°)</th>
          {#if precipitationSupported}<th class="p-2">Accumulated precipitation (mm)</th><th class="p-2">Accumulation window (UTC)</th>{/if}
        </tr></thead>
        <tbody>
          {#each forecast.timeline.valid_at as time, i}
            <tr class="border-t border-border"><th class="p-2 font-normal">{time}</th>
              <td class="p-2">{displayValue(forecast, 'temperature_2m', i)}</td>
              <td class="p-2">{displayValue(forecast, 'wind_speed_10m', i)}</td>
              <td class="p-2">{displayValue(forecast, 'wind_direction_10m', i)}</td>
              {#if precipitationSupported}
                <td class="p-2">{displayValue(forecast, 'precipitation', i)}</td>
                <td class="p-2">{displayAccumulationWindow(forecast, i)}</td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if precipitationSupported}
      <p class="mt-4 text-sm" data-testid="precipitation-accumulation">
        Precipitation is the total over each explicit UTC accumulation window, not an hourly rain rate.
        Windows may overlap; amounts must not be added together as separate hourly totals.
      </p>
    {/if}
    <p class="mt-4 text-sm" data-testid="unsupported-capabilities">
      {precipitationSupported ? '' : 'Precipitation, '}weather-condition icons, daily summaries, current observations,
      radar, maps and model comparisons: not available through this weather feed yet.
      Air quality has its own separately configured panel, source and native forecast times.
      Missing does not mean dry, clear or clean air.
    </p>
    <p class="mt-3 text-sm text-muted-foreground">
      <a class="underline" href="https://www.ecmwf.int/en/forecasts/datasets/open-data" target="_blank" rel="noopener noreferrer">{forecast.forecast.source.attribution}</a>
      · <a class="underline" href={forecast.forecast.source.license_url} target="_blank" rel="noopener noreferrer">{forecast.forecast.source.license}</a>
      · Processing: {forecast.forecast.source.changes}
      Local core delivery does not attest the original weather source; model corrections are not yet trained.
    </p>
