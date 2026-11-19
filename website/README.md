# VOLPAROSSA Weather · Atlas of the Atmosphere

The English product page is served at [volparossa.org/volparossa-weather/](https://volparossa.org/volparossa-weather/). It runs from a static project subpath. All page artwork, fonts, the demonstration and its captions are local.

## Build and review

From the repository root, with Python 3.11 or later:

```sh
python3 website/scripts/build_site.py
python3 website/scripts/check_site.py
python3 website/scripts/preview.py
```

Open <http://127.0.0.1:8783/volparossa-weather/>. The preview server handles HTTP byte ranges so that the native video player can seek. The normal build uses the committed image exports and requires only the Python standard library.

```sh
python3 website/scripts/build_site.py --production --output website/dist/volparossa-weather
python3 website/scripts/check_site.py --production --output website/dist/volparossa-weather
```

The preview carries `noindex,nofollow`. Production has its own canonical and sitemap. The **Weather website** workflow attaches the preview on pull requests. An explicit workflow dispatch on main deploys only the checked production directory.

## Evidence and provenance

- [Source register](src/sources.json) covers project links, five pinned Weather Demo 0 release files, Berlin model data and both six-peer layouts. The builder checks file digests against the official publication inventory. The site check compares the Berlin plate with [the decoder record](../third_party/ecmwf-smoke.json).
- [Site settings](src/content.json) include metadata, the reviewed theme commit and the documentation target. The builder verifies every file in the [theme inventory](vendor/volparossa-theme/theme-version.json).
- [Asset register](masters/README.md) records the print masters, export recipes, geographic sources, media and rights. The reference and source masters stay outside the generated Pages artifact.
- [Browser review](review/README.md) contains actual responsive renders and test results. For optional local browser checks, run `npm ci --prefix website`, install the Playwright browser binaries, then use `npm --prefix website run qa`. Set `CHROME_PATH` to use an installed Chromium, `QA_ENGINES` to select engines and `WEATHER_QA_URL` to check a deployed page.
