"""Build the atmospheric atlas from committed static sources and a verified shared theme."""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from diagrams import inset, legend, mesh

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / 'vendor/volparossa-theme'
SRC = ROOT / 'src'
CONFIG = json.loads((SRC / 'content.json').read_text())
SOURCES = json.loads((SRC / 'sources.json').read_text())
CANONICAL = SOURCES['links']['publication_url']


def render(template, values):
    return re.sub(r'{{(\w+)}}', lambda m: values[m[1]], template)


def verify_sources():
    theme = json.loads((THEME / 'theme-version.json').read_text())
    if theme['source_commit'] != CONFIG['theme_commit']:
        raise ValueError('Unexpected central theme revision')
    for path, digest in theme['files'].items():
        if hashlib.sha256((THEME / path).read_bytes()).hexdigest() != digest:
            raise ValueError('Shared theme mismatch: ' + path)
    demo = ROOT / 'assets/demo'
    inventory = (demo / 'publication-SHA256SUMS').read_text()
    for item in SOURCES['demo']['assets']:
        data = (demo / item['filename']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256'] or len(data) != item['bytes']:
            raise ValueError('Demo release mismatch: ' + item['filename'])
        if item['filename'] != 'publication-SHA256SUMS' and item['sha256']+'  '+item['filename'] not in inventory:
            raise ValueError('Not found in official release inventory: ' + item['filename'])


def art(name, variants):
    sizes = {'storm':'(max-width:800px) 100vw, min(65vw, 885px)', 'fox':'(max-width:600px) 37vw, 220px',
             'film':'(max-width:600px) 95vw, min(44vw, 600px)', 'cloud':'min(17vw, 230px)', 'margin':'(max-width:600px) 95vw, (max-width:950px) 50vw, min(30vw, 430px)'}
    files = variants[name]
    srcset = ', '.join(f'assets/atlas/{name}-{f["width"]}.webp {f["width"]}w' for f in files)
    fallback = files[0 if name in ('fox','cloud','margin') else 1]
    w, h = fallback['width'], fallback['height']
    priority = 'loading="eager" fetchpriority="high"' if name == 'storm' else 'loading="lazy" decoding="async"'
    return f'<picture class="art"><source type="image/webp" srcset="{srcset}" sizes="{sizes[name]}"><img src="assets/atlas/{name}-{w}.jpg" width="{w}" height="{h}" alt="" {priority}></picture>'


def icons():
    marks = {'thermometer':'<path d="M10 15.5V5a2 2 0 0 1 4 0v10.5a4 4 0 1 1-4 0Z"/><path d="M12 18v-8"/>',
             'wind':'<path d="M2 8h11c5 0 5-6 1-6-1.6 0-2.5 1-2.5 2.2M2 12h16c5 0 5-6 1-6M2 16h11c5 0 5 6 1 6-1.5 0-2.5-1-2.5-2.3"/>',
             'rain':'<path d="M5 15a4 4 0 0 1-.3-8 6 6 0 0 1 11.5.2A4 4 0 1 1 18 15ZM7 18l-1 2m6-2-1 3m6-3-1 2"/>',
             'particles':'<g fill="currentColor" stroke="none">'+''.join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x,y,r in [(3,12,1.1),(8,4,1),(12,12,2),(19,9,1),(17,17,1.3),(6,18,1.4),(13,4,1),(12,21,1),(20,3,.8),(3,5,.8),(21,21,.8)])+'</g>',
             'cloud_sun':'<path d="M5.5 19a4 4 0 1 1 1-7.8 5 5 0 0 1 9.3-1.2A4.5 4.5 0 1 1 18 19ZM12.3 5.6a4 4 0 0 1 6.4 2.7M15 2V.5m6 4 1-1m-.5 7h2"/>'}
    return {name:f'<svg aria-hidden="true" class="unit-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round">{drawing}</svg>' for name,drawing in marks.items()}


def archive():
    r = SOURCES['berlin']
    def stamp(iso):
        dt = datetime.fromisoformat(iso.replace('Z','+00:00'))
        return f'{dt.day} {dt:%b %Y, %H:%M} UTC'
    def coords(point):
        return f"{point['latitude']:.2f}° N, {point['longitude']:.2f}° E"
    return dict(temperature=r['display_temperature'], run_iso=r['model_run_at'], run_text=stamp(r['model_run_at']),
                valid_iso=r['valid_at'], valid_text=stamp(r['valid_at']), lead_hours=str(r['lead_hours']),
                kelvin=f"{r['decoded_temperature_kelvin']:.3f}", celsius=f"{r['normalized_temperature_celsius']:.3f}",
                test_coords=coords(r['public_test_point']), grid_coords=coords(r['nearest_model_grid_point']),
                distance=f"{r['nearest_model_grid_point']['distance_km']:.1f}", inset=inset(r))


def build(output, production):
    verify_sources()
    output = output.resolve()
    marker = output / '.weather-atlas-build'
    if output.exists() and any(output.iterdir()):
        if not marker.is_file():
            raise ValueError('Choose an empty or previously generated Weather output directory')
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    marker.touch()
    (output / '.nojekyll').touch()
    shutil.copytree(ROOT / 'assets', output / 'assets')
    for filename in ['site.css','site.js','tokens.css','logo.png','favicon.png']:
        shutil.copy2(THEME / 'assets' / filename, output / 'assets' / filename)
    for directory in ['fonts','icons']:
        shutil.copytree(THEME / 'assets' / directory, output / 'assets' / directory)
    shutil.copy2(SRC / 'weather.css', output / 'assets/weather.css')
    shutil.copy2(SRC / 'player.js', output / 'assets/player.js')
    for filename in ['LICENSE','favicon.ico']:
        shutil.copy2(THEME / filename, output / filename)

    spec = importlib.util.spec_from_file_location('navigation', THEME / 'shared/navigation.py')
    navigation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(navigation)
    nav = json.loads((THEME/'data/navigation.json').read_text())
    projects = json.loads((THEME/'data/projects.json').read_text())
    links = navigation.site_links(nav, projects, 'https://volparossa.org/', {'github': SOURCES['links']['project']})
    github = (THEME/'assets/icons/github.svg').read_text().replace('<svg ', '<svg class="github-icon" aria-hidden="true" ', 1)
    variants = json.loads((SRC / 'variants.json').read_text())
    values = {**links, **CONFIG, **SOURCES['links'], **icons(), **archive(), 'legend':legend(), 'movie':(SRC / 'video.html').read_text().strip(),  'north_east':'<svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m3 13 10-10M4 3h9v9"/></svg>', 'github_icon':github,
              'social_image': CANONICAL+'assets/atlas/social.jpg', 'body_class':'weather-page'}
    for name in variants:
        values[name+'_picture'] = art(name, variants)
    for dimension in ['desktop','mobile']:
        values[dimension+'_mesh'] = mesh(SOURCES['network'], dimension)
    for group,key in [('main','nav_links'),('footer','footer_links')]:
        values[key] = navigation.navigation_links(nav[group],links,active='applications',github_icon=github,footer=group=='footer')
    for slug, template in [('', 'index'), ('credits/', 'credits')]:
        values.update(root='../' if slug else '', canonical=CANONICAL+slug)
        if slug:
            values['title'] = 'Sources and credits | VOLPAROSSA Weather'
        robots = 'index,follow' if production else 'noindex,nofollow'
        values['head_extra'] = f'<meta property="og:locale" content="en_GB"><meta name="robots" content="{robots}"><link rel="stylesheet" href="{values["root"]}assets/weather.css">'
        if not slug:
            values['head_extra'] += '<script src="assets/player.js" defer></script>'
        for part in ['header','footer']:
            values[part] = render((THEME/f'templates/{part}.html').read_text(), values)
        values['content'] = render((SRC/(template+'.html')).read_text(), values)
        directory = output / slug
        directory.mkdir(exist_ok=True)
        (directory / 'index.html').write_text(render((THEME/'templates/layout.html').read_text(), values))
    if production:
        sitemap = ''.join('<url><loc>'+CANONICAL+path+'</loc></url>' for path in ['', 'credits/'])
        (output / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+sitemap+'</urlset>\n')
    print('Built', 'production' if production else 'noindex preview', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'preview/volparossa-weather')
    args = parser.parse_args()
    build(args.output, args.production)
