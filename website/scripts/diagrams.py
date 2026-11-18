"""Typeset the key, two source-specified peer layouts and the Berlin coordinate inset."""
from math import cos, radians

NAVY = '#203a56'
RED = '#9c3827'


def legend():
    strokes = [
        ('Isobar', '<path d="M2 12 Q10 4 18 9 T37 8"/>'),
        ('Warm front', f'<g stroke="{RED}"><path d="M2 12h35"/><path fill="{RED}" d="M6 12a4 4 0 0 1 8 0m9 0a4 4 0 0 1 8 0"/></g>'),
        ('Cold front', '<path d="M2 12h35"/><path fill="currentColor" d="m6 12 4-7 4 7m9 0 4-7 4 7"/>'),
        ('Low pressure', '<text x="18" y="14" text-anchor="middle" stroke="none" fill="currentColor" font-size="17">L</text>'),
        ('High pressure', '<text x="18" y="14" text-anchor="middle" stroke="none" fill="currentColor" font-size="17">H</text>')
    ]
    return ''.join(f'<li><svg viewBox="0 0 40 18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4">{mark}</svg>{name}</li>' for name, mark in strokes)


def mesh(network, layout):
    data = network['layouts'][layout]
    width, height, points = data['width'], data['height'], data['points']
    horizontal = layout == 'desktop'
    hatch = 'hatch-' + layout
    parts = [f'<svg class="mesh-{layout}" role="img" aria-label="Six cooperating peers. One possible route follows A, B, C, F. Another follows A, D, E, F." viewBox="0 0 {width} {height}">',
             f'<defs><pattern id="{hatch}" patternUnits="userSpaceOnUse" width="5" height="5"><path d="m-1 2 3-3m-1 6 5-5m-1 6 2-2" stroke="#546b79" stroke-width=".7"/></pattern></defs>']
    routes = [{tuple(edge) for edge in zip(route, route[1:])} for route in network['routes']]
    for a, b in network['edges']:
        start, end = points[a], points[b]
        first, second = (a,b) in routes[0], (a,b) in routes[1]
        colour = NAVY if first else RED if second else '#84796d'
        dash = '' if first else '6 5' if second else '2 6'
        mx, my = (start[0]+end[0])/2, (start[1]+end[1])/2
        mx += 10 if not horizontal else 0
        my -= 17 if horizontal else 0
        parts.append(f'<path data-edge="{a}-{b}" d="M{start[0]} {start[1]}Q{mx} {my} {end[0]} {end[1]}" fill="none" stroke="{colour}" stroke-width="2" stroke-dasharray="{dash}"/>')
    io = ('M0 110Q32 104 70 55 M520 170Q564 161 600 65 M520 170Q565 151 600 183' if horizontal else
          'M150 0Q105 7 60 55 M230 295Q198 327 80 360 M230 295Q244 331 222 360')
    parts.append(f'<path d="{io}" fill="none" stroke="{NAVY}" stroke-width="1.5" stroke-dasharray="4 3"/>')
    for node, (x,y) in points.items():
        parts.append(f'<g data-peer="{node}"><circle cx="{x}" cy="{y}" r="16" fill="#f6edda" stroke="{NAVY}" stroke-width="2"/><circle cx="{x}" cy="{y}" r="13" fill="url(#{hatch})"/><text x="{x}" y="{y+5}" text-anchor="middle" font-family="Georgia, serif" font-size="15" stroke="#f8f0df" stroke-width="3" paint-order="stroke" fill="{NAVY}">{node}</text></g>')
    return ''.join(parts)+'</svg>'


def inset(record):
    a, b = record['public_test_point'], record['nearest_model_grid_point']
    scale = 19
    x1, y1 = 67, 60
    x2 = x1 + (b['longitude']-a['longitude'])*111.32*cos(radians(a['latitude']))*scale
    y2 = y1 + (a['latitude']-b['latitude'])*111.2*scale
    return f'''<svg viewBox="0 0 253 149" role="img" aria-label="Berlin detail. The model grid point lies east-southeast of the public test point.">
    <defs><pattern id="coordinate-grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#a89f88" stroke-width=".75"/></pattern></defs>
    <rect width="253" height="149" fill="url(#coordinate-grid)"/><g fill="none" stroke="{NAVY}"><path d="M{x1} {y1}L{x2:.1f} {y2:.1f}" stroke-dasharray="4 4"/><path d="M{x1} {y1}l-17-19H14m{x2:.1f} {y2:.1f}l9 16h45"/><path d="M18 129v5h{scale*2}v-5m179-96v-16l-3 5"/></g>
    <circle cx="{x1}" cy="{y1}" r="5" stroke="{RED}" stroke-width="2" fill="#faf2df"/><rect x="{x2-4.5:.1f}" y="{y2-4.5:.1f}" width="9" height="9" fill="{NAVY}"/>
    <g fill="{NAVY}" font-family="Georgia,serif" font-size="14"><text x="14" y="34">Public test point</text><text x="114" y="135">Model grid point</text><text x="19" y="125" font-size="12">2 km</text><text x="231" y="14" font-size="12">N</text></g></svg>'''
