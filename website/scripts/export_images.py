"""Regenerate the responsive atlas engravings from the unlettered masters (Pillow)."""
import hashlib
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sizes = {'storm': [640, 1000, 1440], 'fox': [240, 480], 'film': [480, 800, 1200],
         'cloud': [240, 480], 'margin': [400, 800, 1200]}
variants = {}
for name, widths in sizes.items():
    image = Image.open(ROOT / 'masters' / (name + '.png')).convert('RGB')
    # Lift the scanned paper to white so multiply blending prints only the engraving.
    white = {'storm': (252,234,209), 'fox': (252,252,252), 'margin': (252,252,252)}
    if name in white:
        image = Image.merge('RGB', tuple(band.point(lambda n: min(255, round(n * 255 / level)))
                                          for band, level in zip(image.split(), white[name])))
        opacity = image.convert('L').point(lambda lum: min(255, round((255-lum)*255/209)))
        image = Image.new('RGBA', image.size, (24, 47, 73, 255))
        image.putalpha(opacity)
    variants[name] = []
    for width in widths:
        height = round(width * image.height / image.width)
        resized = image.resize((width, height), Image.Resampling.LANCZOS)
        entry = {'width': width, 'height': height}
        for ext in ['webp', 'jpg']:
            dest = ROOT / 'assets/atlas' / f'{name}-{width}.{ext}'
            export = resized
            if ext == 'jpg' and resized.mode == 'RGBA':
                export = Image.new('RGB', resized.size, (246, 239, 223))
                export.paste(resized, mask=resized.getchannel('A'))
            export.save(dest, quality=85, optimize=True)
            entry[ext] = {'bytes': dest.stat().st_size, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
        variants[name].append(entry)
(ROOT / 'src/variants.json').write_text(json.dumps(variants, indent=2) + '\n')
