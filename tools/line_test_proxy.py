"""Restricted proxy for testing the LINE acknowledge button + clip from a dev PC through a temporary public tunnel.

Codex + Gemini (8 Oct): never tunnel the whole backend (login, registration, /videos and the default admin password
would be on the internet). The tunnel points at THIS proxy, which forwards exactly two things to the backend and refuses
everything else with 404:
  POST /api/line/webhook               -- LINE delivering the button press (the backend checks the HMAC signature)
  GET/HEAD /api/alert-images/<file>     -- the alert image / clip LINE downloads (plain file names only)
Forwarded/Host headers from outside are dropped, so nothing upstream can be steered by a spoofed X-Forwarded-Host.
Resource limits (Codex re-reviews): socket timeout 10 s, the whole webhook body within 5 s, at most MAX_CONC requests at once (else 503), forbidden
requests are refused WITHOUT reading their body, webhook bodies capped at 1 MB, media streamed in 64 KB chunks with the
upstream Content-Length (HEAD included). Every request is logged with its verdict.

Usage: python tools/line_test_proxy.py [listen_port=8940] [backend=http://127.0.0.1:8932]
then:  cloudflared tunnel --url http://127.0.0.1:8940

(Moved from the friend's repository; the only change is that the port and backend are no longer read from sys.argv at
import time, so tests/v3/test_step5_line.py can start it on a free port in front of a fake backend.)
"""
import http.server
import re
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_PORT, DEFAULT_BACKEND = 8940, 'http://127.0.0.1:8932'
MEDIA = re.compile(r'^/api/alert-images/[A-Za-z0-9_.\-]{1,200}$')
KEEP = {'content-type', 'x-line-signature', 'user-agent'}
MAX_BODY, MAX_CONC, BODY_DEADLINE = 1_000_000, 8, 5.0
SLOTS = threading.BoundedSemaphore(MAX_CONC)


class Proxy(http.server.BaseHTTPRequestHandler):
    timeout = 10                     # socket read/write deadline (slow bodies, idle connections)
    backend = DEFAULT_BACKEND

    def _plain(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        return status

    def _forward(self, method, body=None):
        headers = {k: v for k, v in self.headers.items() if k.lower() in KEEP}
        req = urllib.request.Request(self.backend + self.path, data=body, headers=headers, method=method)
        try:
            r = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            self.send_response(r.status if hasattr(r, 'status') else r.code)
            for h in ('Content-Type', 'Content-Length'):
                if r.headers.get(h):
                    self.send_header(h, r.headers.get(h))
            self.end_headers()
            if method != 'HEAD':
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return r.status if hasattr(r, 'status') else r.code

    def _read_body(self, n):
        """The whole body within BODY_DEADLINE seconds IN TOTAL (Codex: a per-read timeout lets a sender trickle one
        byte at a time forever and hold a slot); None when the deadline passes."""
        end, parts, got = time.monotonic() + BODY_DEADLINE, [], 0
        while got < n:
            left = end - time.monotonic()
            if left <= 0:
                return None
            self.connection.settimeout(min(left, self.timeout))
            try:
                chunk = self.rfile.read1(min(65536, n - got))
            except (TimeoutError, OSError):
                return None
            if not chunk:
                return None
            parts.append(chunk)
            got += len(chunk)
        return b''.join(parts)

    def _guarded(self, method, allowed):
        if not allowed:
            return self._plain(404)                       # never read a forbidden request's body
        if not SLOTS.acquire(blocking=False):
            return self._plain(503)
        try:
            if method == 'POST':
                n = int(self.headers.get('Content-Length') or 0)
                if not 0 < n <= MAX_BODY:
                    return self._plain(413 if n > MAX_BODY else 400)
                body = self._read_body(n)
                if body is None:
                    return self._plain(408)
                return self._forward('POST', body)
            return self._forward(method)
        finally:
            SLOTS.release()

    def do_POST(self):
        self.log_message('POST %s -> %s', self.path[:80], self._guarded('POST', self.path == '/api/line/webhook'))

    def do_GET(self):
        self.log_message('GET %s -> %s', self.path[:80], self._guarded('GET', bool(MEDIA.match(self.path))))

    def do_HEAD(self):
        self.log_message('HEAD %s -> %s', self.path[:80], self._guarded('HEAD', bool(MEDIA.match(self.path))))

    def do_PUT(self):
        self.log_message('%s %s -> %s', self.command, self.path[:80], self._plain(404))

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT


def make_server(port=DEFAULT_PORT, backend=DEFAULT_BACKEND):
    """A server on 127.0.0.1:port (0 = any free port) that forwards the two allowed request kinds to `backend`."""
    handler = type('BoundProxy', (Proxy,), {'backend': backend.rstrip('/')})
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    backend = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BACKEND
    print('LINE test proxy on 127.0.0.1:%d -> %s (webhook POST + alert media GET/HEAD only)' % (port, backend), flush=True)
    make_server(port, backend).serve_forever()
