"""Maintainer tool: project Natural Earth land and typeset the static atlas plates."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'assets/atlas'
LAND = json.loads((ROOT/'masters/geography/atlantic-land.geojson').read_text())
DEG = math.pi / 180


def project(lon, lat, centre, scale, origin):
    """Lambert azimuthal equal-area, spherical Earth, north up at centre."""
    lon0, lat0 = centre
    a, b, d = lat*DEG, lat0*DEG, (lon-lon0)*DEG
    k = scale * math.sqrt(2/(1+math.sin(b)*math.sin(a)+math.cos(b)*math.cos(a)*math.cos(d)))
    return (origin[0]+k*math.cos(a)*math.sin(d),
            origin[1]-k*(math.cos(b)*math.sin(a)-math.sin(b)*math.cos(a)*math.cos(d)))


def path(points, close=False):
    return 'M'+' '.join(f'{x:.1f},{y:.1f}' for x,y in points)+('Z' if close else '')


def clip_polygon(ring, width, height):
    # Clip projected land just outside the plate, including polygons spanning its frame.
    for axis, limit, keep in [(0,-3,1),(1,-3,1),(0,width+3,-1),(1,height+3,-1)]:
        if not ring: break
        result = []
        prev = ring[-1]
        for cur in ring:
            inp=(prev[axis]-limit)*keep>=0
            inc=(cur[axis]-limit)*keep>=0
            if inp!=inc:
                t=(limit-prev[axis])/(cur[axis]-prev[axis])
                result.append(tuple(prev[j]+t*(cur[j]-prev[j]) for j in (0,1)))
            if inc: result.append(cur)
            prev=cur
        ring=result
    return ring


def geography(width, height, centre, scale, origin):
    def xy(lon,lat): return project(lon,lat,centre,scale,origin)
    parts=['<g fill="none" stroke="#667991" stroke-width=".75" opacity=".48" stroke-dasharray="3 4">']
    for lon in range(-80,61,10):
        parts.append(f'<path d="{path([xy(lon,i) for i in range(20,87)])}"/>')
    for lat in range(25,86,5):
        parts.append(f'<path d="{path([xy(i,lat) for i in range(-86,56)])}"/>')
    parts.append('</g><g fill="#e8dece" fill-opacity=".37" stroke="#233c60" stroke-width="1.35" stroke-linejoin="round" fill-rule="evenodd">')
    for feature in LAND['features']:
        g=feature['geometry']
        polys=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
        for poly in polys:
            clipped=[clip_polygon([xy(lon,lat) for lon,lat in ring],width,height) for ring in poly]
            shapes=' '.join(path(r,True) for r in clipped if len(r)>2)
            if shapes: parts.append(f'<path d="{shapes}"/>')
    parts.append('</g>')
    return ''.join(parts)


def front(control, kind, marks):
    def at(t):
        return tuple((1-t)**3*control[0][i]+3*(1-t)**2*t*control[1][i]+3*(1-t)*t*t*control[2][i]+t**3*control[3][i] for i in (0,1))
    ink='#a33522' if kind=='warm' else '#1d4574'
    parts=[f'<g fill="{ink}" stroke="{ink}"><path d="{path([at(i/60) for i in range(61)])}" fill="none" stroke-width="2.4"/>']
    for t in marks:
        x,y=at(t); nx,ny=at(t+.001)
        angle=math.degrees(math.atan2(ny-y,nx-x))
        mark='M-10 0a10 10 0 0 1 20 0Z' if kind=='warm' else 'M-9 0 0 -14 9 0Z'
        parts.append(f'<path transform="translate({x:.2f} {y:.2f}) rotate({angle:.2f})" d="{mark}"/>')
    return ''.join(parts)+'</g>'


def synoptic():
    w,h=1000,660
    art=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><title>Illustrative synoptic chart of the North Atlantic and Europe</title>',
         geography(w,h,(-16,54),1060,(532,328)),
         '<g fill="none" stroke="#234d7b" stroke-linejoin="round">']
    eye=(372,271)
    labels=[]
    for i,r in enumerate((48,85,124,166,211,261,319,386)):
        points=[]
        for n in range(181):
            t=n*math.tau/180
            distort=1+.045*math.sin(3*t+.35)+.07*math.cos(2*t+.4)
            x=r*1.18*math.cos(t)*distort; y=r*.91*math.sin(t)*distort
            points.append((eye[0]+x+.21*y,eye[1]+y-.23*x))
        art.append(f'<path stroke-width="{1.25 if i%2==0 else .9}" opacity=".86" d="{path(points,True)}"/>')
        if i in (1,3,5,7):
            lx,ly=points[57];labels.append((lx,ly,982+i*4))
    art.append('</g>')
    art.append(front([(456,96),(583,117),(734,321),(900,255)],'warm',[.09,.21,.34,.48,.62,.76,.91]))
    art.append(front([(501,243),(560,361),(336,521),(173,616)],'cold',[.16,.3,.44,.58,.72,.87]))
    art.append('<g text-anchor="middle" font-family="Georgia,serif" font-weight="bold" fill="#163858" stroke="#f5eddf" stroke-width="4" paint-order="stroke">')
    for x,y,level in labels: art.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="16">{level}</text>')
    art.append('<text x="372" y="270" font-size="42">L</text><text x="372" y="292" font-size="20">982</text><text x="834" y="482" font-size="44">H</text><text x="834" y="506" font-size="20">1024</text></g></svg>')
    return ''.join(art)


def locator():
    b=json.loads((ROOT/'src/sources.json').read_text())['berlin']['public_test_point']
    centre=(8,52); origin=(257,126)
    x,y=project(b['longitude'],b['latitude'],centre,720,origin)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 245"><title>Berlin in Europe</title>'
            +geography(520,245,centre,720,origin)
            +f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="#fbf2dc" stroke="#9c3324" stroke-width="2.6"/><circle cx="{x:.1f}" cy="{y:.1f}" r="3.7" fill="#a33321"/><text x="{x+14:.1f}" y="{y+5:.1f}" font-family="Georgia,serif" font-size="20" fill="#772a20" stroke="#f4ecdc" stroke-width="4" paint-order="stroke">Berlin</text></svg>')


if __name__=='__main__':
    (OUT/'synoptic.svg').write_text(synoptic())
    (OUT/'europe.svg').write_text(locator())
