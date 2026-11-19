// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { archiveGrid } from '../src/archived-temperature.mjs';
import { observationIndex, compareTemperatureCases } from '../src/forecast-verification.mjs';
import { forecast, QUERY } from './fixtures.mjs';

const cli = fileURLToPath(new URL('../scripts/verify-forecast.mjs', import.meta.url));
const manifest = fileURLToPath(new URL('../third_party/ecmwf-dwd-archive-input.json', import.meta.url));
const run = '2026-10-10T12:00:00.000Z';

// Small metadata-only fixture based on the source's October 2026 2t field.
function rasterInfo() {
  return {
    driverShortName: 'GRIB', size: [1440, 721],
    geoTransform: [-180.125, 0.25, 0, 90.125, 0, -0.25],
    bands: [{ band: 1, type: 'Float64', metadata: { '': {
      GRIB_UNIT: '[C]', GRIB_ELEMENT: 'TMP', GRIB_SHORT_NAME: '2-HTGL', GRIB_PDS_PDTN: '0',
      GRIB_REF_TIME: '1791633600', GRIB_VALID_TIME: '1791720000', GRIB_FORECAST_SECONDS: '86400',
      GRIB_IDS: 'CENTER=98(ECMWF) SUBCENTER=0 MASTER_TABLE=32 LOCAL_TABLE=0 SIGNF_REF_TIME=1(Start_of_Forecast) REF_TIME=2026-10-10T12:00:00Z PROD_STATUS=0(Operational) TYPE=1(Forecast)',
    } } }],
  };
}

function rejectedCli(args) {
  const result = spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8', timeout: 5000 });
  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  const diagnostic = JSON.parse(result.stderr);
  assert.deepEqual(Object.keys(diagnostic), ['error']);
  assert.match(diagnostic.error, /^[A-Z][A-Z0-9_]*$/);
  return diagnostic.error;
}

async function scratch(t) {
  const path = await mkdtemp(join(tmpdir(), 'weather-archive-'));
  t.after(() => rm(path, { recursive: true, force: true }));
  return path;
}

test('archive CLI requires all local inputs and refuses a field with another digest before decoding', async t => {
  const dir = await scratch(t);
  const command = ['archive', manifest, dir];
  assert.equal(rejectedCli(command), 'VERIFICATION_INPUT_FAILED');

  const declaration = JSON.parse(await readFile(manifest, 'utf8'));
  const digest = bytes => createHash('sha256').update(bytes).digest('hex');
  // Only a GRIB2 envelope, never decoded. Its digest differs by design.
  const field = Buffer.alloc(32);
  field.write('GRIB');
  field[7] = 2;
  field.writeBigUInt64BE(BigInt(field.length), 8);
  field.write('7777', field.length - 4);
  for (const [model, streamClass] of [['ifs', 'od'], ['aifs-single', 'ai']]) {
    const index = JSON.stringify({ class: streamClass, type: 'fc', date: '20261010', time: '1200',
      step: '24', expver: '0001', stream: 'oper', param: '2t', levtype: 'sfc', _offset: 0, _length: field.length });
    declaration.models[model].index_sha256 = digest(index);
    assert.notEqual(declaration.models[model].field_sha256, digest(field));
    await writeFile(join(dir, model + '.index'), index);
    await writeFile(join(dir, model + '.grib2'), field);
  }
  const changed = join(dir, 'declared.json');
  await writeFile(changed, JSON.stringify(declaration));
  assert.equal(rejectedCli(['archive', changed, dir]), 'ARCHIVE_HASH_MISMATCH');
});

test('prospective verifier rejects a retrospective manifest in place of a station observation file', async t => {
  const dir = await scratch(t);
  const ifs = join(dir, 'ifs.json'), aifs = join(dir, 'aifs.json');
  await writeFile(ifs, JSON.stringify(forecast(QUERY)));
  await writeFile(aifs, JSON.stringify(forecast({ ...QUERY, model: 'aifs-single' })));
  assert.equal(rejectedCli([ifs, aifs, manifest]), 'OBSERVATION_FORMAT_INVALID');
  const observations = join(dir, 'retrospective.json');
  const archived = JSON.parse(await readFile(manifest, 'utf8'));
  await writeFile(observations, JSON.stringify(archived.stations[0].observations));
  assert.equal(rejectedCli([ifs, aifs, observations]), 'OBSERVATION_CONTRACT_INVALID');
});

test('archive CLI rejects incompatible observations and contradictory retrieval dates before local field access', async t => {
  const dir = await scratch(t);
  const changed = join(dir, 'bad-observations.json');
  const declaration = JSON.parse(await readFile(manifest, 'utf8'));
  declaration.stations[0].observations.unit = 'K';
  await writeFile(changed, JSON.stringify(declaration));
  assert.equal(rejectedCli(['archive', changed, dir]), 'OBSERVATION_CONTRACT_INVALID');
  declaration.stations[0].observations.unit = 'degC';
  declaration.retrieved_utc_date = '2026-10-10';
  await writeFile(changed, JSON.stringify(declaration));
  assert.equal(rejectedCli(['archive', changed, dir]), 'OBSERVATION_AFTER_RETRIEVAL');
});

test('archive grid binds the global 0.25 degree raster and the native 2 m Celsius forecast identity', () => {
  const valid = rasterInfo();
  assert.equal(archiveGrid(valid, run, 24), valid.bands[0]);
  for (const mutate of [
    info => { info.size[1]--; },
    info => { info.geoTransform[0] += 0.125; },
    info => { info.geoTransform[2] = 0.25; },
    info => { info.bands.push(info.bands[0]); },
    info => { delete info.bands; },
    info => { info.bands[0] = null; },
    info => { info.bands[0].metadata[''].GRIB_PDS_PDTN = '8'; },
    info => { info.bands[0].metadata[''].GRIB_UNIT = '[K]'; },
    info => { info.bands[0].metadata[''].GRIB_SHORT_NAME = '10-HTGL'; },
    info => { info.bands[0].metadata[''].GRIB_ELEMENT = 'DPT'; },
    info => { info.bands[0].metadata[''].GRIB_IDS = 'CENTER=7(US-NCEP)'; },
    info => { info.bands[0].metadata[''].GRIB_REF_TIME = '1791622800'; },
    info => { info.bands[0].metadata[''].GRIB_VALID_TIME = '1791723600'; },
    info => { info.bands[0].metadata[''].GRIB_FORECAST_SECONDS = '82800'; },
  ]) {
    const info = rasterInfo();
    mutate(info);
    assert.throws(() => archiveGrid(info, run, 24), { code: 'ARCHIVE_GRIB_IDENTITY_MISMATCH' });
  }
});

test('nominal provisional case stays labelled and late archive availability excludes both scores', async () => {
  const declaration = JSON.parse(await readFile(manifest, 'utf8'));
  const { observations } = declaration.stations[0];
  const observed = observationIndex(observations, true);
  const [{ observed_at, temperature_2m }] = observations.samples;
  const grid = { latitude: observations.station.latitude, longitude: observations.station.longitude };
  // Synthetic forecasts exactly one degree below/above the selected nominal observation.
  const samples = [-1, 1].map(error => new Map([[observed_at, {
    valid_at: observed_at, lead_hours: 24, temperature_2m: temperature_2m + error, grid,
  }]]));
  const sources = ['ifs', 'aifs-single'].map(model => ({ model, ...declaration.models[model] }));
  const compare = () => compareTemperatureCases(sources, samples, observations, observed, true);
  const paired = compare();
  assert.equal(paired.coverage.paired, 1);
  assert.equal(paired.cases[0].observation_quality, 'provisional');
  assert.equal(paired.cases[0].observation_statistic, 'nominal-synoptic-hour');
  assert.equal(paired.observations.declared_purpose, 'retrospective-evaluation');
  assert.equal(paired.cases[0].ifs_error_degC, -1);
  assert.equal(paired.cases[0].aifs_single_error_degC, 1);
  sources[1].last_modified_at = observed_at;
  const late = compare();
  assert.deepEqual(late.coverage, { candidate_times: 1, paired: 0, excluded: 1 });
  assert.deepEqual(late.cases[0].excluded, ['aifs-single_archive_not_available_in_advance']);
  for (const metrics of Object.values(late.models))
    assert.deepEqual(metrics, { mean_error_degC: null, mean_absolute_error_degC: null });
});
