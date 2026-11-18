"""Typeset the key, two source-specified peer layouts and the Berlin coordinate inset."""
from math import cos, hypot, radians

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
    """Draw the supplied topology as a print diagram; direction follows the forecast."""
    data = network['layouts'][layout]
    width, height = data['width'], data['height']
    desktop = layout == 'desktop'
    # The wide plate follows the staggered composition of the printed reference.
    points = dict(A=(82,106), B=(229,42), C=(420,70), D=(150,186), E=(318,151), F=(453,166)) if desktop else data['points']
    radius = 18 if desktop else 16
    routes = [{tuple(edge) for edge in zip(route, route[1:])} for route in network['routes']]
    bends = {('A','B'):-23, ('B','C'):-16, ('A','D'):18, ('D','E'):23,
             ('E','F'):10, ('C','F'):-12, ('B','E'):22, ('B','F'):-6}
    positions = {
        'desktop': [('in', (1,115)), ('out1',(width-4,53)), ('out2',(width-4,173))],
        'mobile': [('in',(65,2)), ('out1',(78,height-4)), ('out2',(223,height-4))]
    }
    coordinates = {**points, **dict(positions[layout])}
    arrow = 'arrow-' + layout
    globe = 'peer-' + layout
    parts = [f'<svg class="mesh-{layout}" role="img" aria-label="Six cooperating peers. A public forecast can travel from A to F via B and C, or via D and E. F can deliver it to either app." viewBox="0 0 {width} {height}">',
             f"""<defs>
               <marker id="{arrow}" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 9 4 0 8 2.3 4Z" fill="{NAVY}"/></marker>
               <radialGradient id="{globe}-ink" cx=".34" cy=".26" r=".79"><stop stop-color="#faf4e8"/><stop offset=".53" stop-color="#e1dac8"/><stop offset="1" stop-color="#85949a"/></radialGradient>
               <pattern id="{globe}-lines" width="5" height="4.5" patternUnits="userSpaceOnUse" patternTransform="rotate(12)"><path d="M-.5 2q2 -1 6 0" fill="none" stroke="#475e6d" stroke-width=".8"/></pattern>
             </defs>"""]

    def connection(a, b, bend, style, graph_edge=False):
        x1, y1 = coordinates[a]
        x2, y2 = coordinates[b]
        dx, dy = x2-x1, y2-y1
        length = hypot(dx, dy)
        cx = (x1+x2)/2 - dy/length*bend
        cy = (y1+y2)/2 + dx/length*bend
        # Stop before the discs so the arrowheads remain visible at all sizes.
        if a in points:
            start = (radius+4)/hypot(cx-x1, cy-y1)
            x1, y1 = x1+start*(cx-x1), y1+start*(cy-y1)
        if b in points:
            end = (radius+4)/hypot(cx-x2, cy-y2)
            x2, y2 = x2+end*(cx-x2), y2+end*(cy-y2)
        attr = f' data-edge="{a}-{b}"' if graph_edge else ''
        parts.append(f'<path class="mesh-path {style}"{attr} d="M{x1:.1f} {y1:.1f} Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" marker-end="url(#{arrow})"/>')

    for a, b in network['edges']:
        style = 'route-one' if (a,b) in routes[0] else 'route-two' if (a,b) in routes[1] else 'alternate'
        connection(a, b, bends[a,b] if desktop else -bends[a,b]*.7, style, graph_edge=True)
    connection('in','A',0 if desktop else 4,'terminal')
    connection('F','out1',-43 if desktop else -7,'terminal')
    connection('F','out2',-24 if desktop else -15,'terminal')
    for node in network['nodes']:
        x, y = points[node]
        parts.append(f"""<g data-peer="{node}" transform="translate({x} {y})">
            <circle r="{radius}" fill="url(#{globe}-ink)" stroke="{NAVY}" stroke-width="2.2"/>
            <circle r="{radius-1.5}" fill="url(#{globe}-lines)"/>
            <path d="M{-radius*.73} {-radius*.42} Q{-radius*.35} {-radius*.89} {radius*.22} {-radius*.72}" fill="none" stroke="#fff9e9" stroke-width="1.5"/>
            <text text-anchor="middle" y="5" font-family="Georgia,serif" font-size="16" font-weight="bold" stroke="#f6efdf" stroke-width="2.5" paint-order="stroke" fill="{NAVY}">{node}</text></g>""")
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
