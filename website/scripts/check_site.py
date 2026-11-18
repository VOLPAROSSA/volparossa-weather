"""Validate the generated subroute, release assets, diagrams and archival source, offline."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from build_site import CANONICAL, CONFIG, ROOT, SOURCES, verify_sources


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.words = [], []
        self.feed(html)

    def handle_starttag(self, name, attrs):
        self.tags.append((name, dict(attrs)))

    def handle_data(self, data):
        self.words.append(data)

    def select(self, tag):
        return [attrs for name,attrs in self.tags if name == tag]


def check(output, production):
    verify_sources()
    assert (output/'sitemap.xml').exists() == production
    folders = {'', 'assets', 'credits'}
    assert all(not p.is_dir() or p.name in folders for p in output.iterdir())
    for sub in ['', 'credits/']:
        directory = output/sub
        html = (directory/'index.html').read_text()
        page = Page(html)
        assert '{{' not in html and page.select('html') == [{'lang':'en'}]
        assert len(page.select('h1')) == 1
        assert {'name':'robots','content':'index,follow' if production else 'noindex,nofollow'} in page.select('meta')
        assert {'property':'og:locale','content':'en_GB'} in page.select('meta')
        assert {'rel':'canonical','href':CANONICAL+sub} in page.select('link')
        assert len(page.select('main')) == 1
        ids = [a['id'] for _,a in page.tags if 'id' in a]
        assert len(ids) == len(set(ids))
        for _,attrs in page.tags:
            refs = [attrs[k] for k in ('href','src','poster') if k in attrs]
            refs += [part.strip().split()[0] for part in attrs.get('srcset','').split(',') if part.strip()]
            for ref in refs:
                url = urlsplit(ref)
                if url.scheme:
                    assert url.scheme == 'https', ref
                    continue
                if not url.path:
                    assert url.fragment in ids, ref
                    continue
                assert not url.path.startswith('/'), ref
                item = (directory/url.path).resolve()
                if item.is_dir():
                    item = item/'index.html'
                assert item.is_relative_to(output.resolve()) and item.is_file(), ref

    page = Page((output/'index.html').read_text())
    assert [s['id'] for s in page.select('section')] == ['intro','demo','forecast-source','shared-forecast','forecast-fields','apps','research','evidence','contribute']
    assert len(page.select('h2')) == 8
    assert [a['datetime'] for a in page.select('time')] == [SOURCES['berlin'][k] for k in ('model_run_at','valid_at')]
    record = json.loads((ROOT.parent/'third_party/ecmwf-smoke.json').read_text())
    for k in ['model','model_run_at','lead_hours','valid_at','parameter','input_unit','decoded_temperature_kelvin','normalized_temperature_celsius','public_test_point','nearest_model_grid_point']:
        assert record[k] == SOURCES['berlin'][k], k
    assert SOURCES['berlin']['display_temperature'] == f"{record['decoded_temperature_kelvin']-273.15:.1f} °C"
    network = SOURCES['network']
    assert set(network['routes'][0][1:-1]).isdisjoint(network['routes'][1][1:-1])
    for layout in network['layouts']:
        svg = (output/'index.html').read_text().split(f'<svg class="mesh-{layout}"',1)[1].split('</svg>',1)[0]
        assert [a['data-peer'] for a in Page(svg).select('g') if 'data-peer' in a] == network['nodes']
        assert [a['data-edge'] for a in Page(svg).select('path') if 'data-edge' in a] == ['-'.join(e) for e in network['edges']]
    assert len([a for a in page.select('a') if a['href'] == CONFIG['docs_url']]) == 2
    assert 'Unavailable' in page.words
    video, fallback = page.select('video')
    assert video == fallback
    assert video['preload']=='none' and 'controls' in video and 'playsinline' in video and 'autoplay' not in video
    assert page.select('track')[0]['srclang']=='en' and 'default' in page.select('track')[0]
    for item in SOURCES['demo']['assets']:
        assert hashlib.sha256((output/'assets/demo'/item['filename']).read_bytes()).hexdigest() == item['sha256']
    for name, rows in json.loads((ROOT/'src/variants.json').read_text()).items():
        for row in rows:
            for ext in ('webp','jpg'):
                image = output/'assets/atlas'/f'{name}-{row["width"]}.{ext}'
                assert hashlib.sha256(image.read_bytes()).hexdigest()==row[ext]['sha256']
    assert (output/'assets/atlas/social.jpg').is_file()
    print('Verified product and credits pages, routes, metadata, atlas assets, source record, both meshes and official media.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'preview/volparossa-weather')
    opts = parser.parse_args()
    check(opts.output, opts.production)
