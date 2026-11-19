"""Serve the local nested preview, including byte-range seeking for the published MP4."""
import argparse
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Preview(SimpleHTTPRequestHandler):
    def serve_movie_range(self, with_body):
        if urlsplit(self.path).path != '/volparossa-weather/assets/demo/weather-demo-0-final.mp4' or 'Range' not in self.headers:
            return False
        movie = Path(self.translate_path(self.path))
        size = movie.stat().st_size
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers['Range'])
        start, end = 0, -1
        if match and any(match.groups()):
            left, right = match.groups()
            start = int(left) if left else max(0, size-int(right))
            end = min(int(right),size-1) if left and right else size-1
        if not (0 <= start <= end < size):
            self.send_response(416)
            self.send_header('Content-Range',f'bytes */{size}')
            self.end_headers()
            return True
        self.send_response(206)
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Content-Type','video/mp4')
        self.end_headers()
        if with_body:
            with movie.open('rb') as f:
                f.seek(start)
                self.wfile.write(f.read(end-start+1))
        return True

    def do_GET(self):
        if not self.serve_movie_range(True):
            super().do_GET()

    def do_HEAD(self):
        if not self.serve_movie_range(False):
            super().do_HEAD()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8783)
    args = parser.parse_args()
    handler = partial(Preview,directory=str(ROOT/'preview'))
    ThreadingHTTPServer(('127.0.0.1',args.port),handler).serve_forever()
