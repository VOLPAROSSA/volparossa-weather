# Atlas plate register

| Material | Source, treatment and rights |
| --- | --- |
| design-reference.png | Original 1024 × 1536 concept 02 from the owner-supplied Weather build brief. Retained for visual review. |
| storm.png (1610 × 977), fox.png (1817 × 866), film.png (2003 × 785), cloud.png (1254 × 1254), margin.png (2172 × 724) | New engraved illustrations generated for the VOLPAROSSA Weather site from the supplied art direction. [Prompts](illustrations.json). Shared layout and live text are composed separately. |
| Responsive art | Run `python3 website/scripts/export_images.py` with Pillow to export WebP and JPEG. The script neutralises the scanned paper on the three overlay engravings. [Exact dimensions, bytes and SHA-256](../src/variants.json). |
| geography/atlantic-land.geojson | Clipped and simplified from [Natural Earth v5.1.2, 1:50m land](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_land.geojson), SHA-256 `e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b`. [Public domain](https://www.naturalearthdata.com/about/terms-of-use/). |
| synoptic.svg, europe.svg | Run `python3 website/scripts/draw_charts.py` to project the land, draw the illustrative fronts/isobars and label the Berlin region. The Berlin detail and peer diagrams are built from the [data register](../src/sources.json) by [diagrams.py](../scripts/diagrams.py). The app frames, paper texture and timeline are original typeset illustrations. |
| social.jpg | Original share plate, 1200 × 630. With the preview server running, execute `node website/scripts/social.mjs` to composite the same chart, VOLPAROSSA mark and typography. |
| MP4, English VTT and transcript, WebP poster, publication-SHA256SUMS | Original, byte-identical media from [weather-demo-0.1.0](https://github.com/VOLPAROSSA/volparossa/releases/tag/weather-demo-0.1.0). Source and licensing information is retained in [NOTICES.md](../assets/demo/NOTICES.md). The wide blue cover is an independent atlas illustration. |
| Original VOLPAROSSA mark, fonts and shared site assets | Unmodified from [the pinned central export](../vendor/volparossa-theme/theme-version.json). The export contains the asset notices and both font licences. |

To reproduce the geographic subset with GDAL, use the pinned download above as the input to `ogr2ogr -f GeoJSON atlantic-land.geojson ne_50m_land.geojson -clipsrc -86 21 55 86 -simplify 0.028 -lco COORDINATE_PRECISION=3`. Public archive data is attributed at the point of use on the page and in the [credits](../src/credits.html).
