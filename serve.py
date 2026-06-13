#!/usr/bin/env python3
"""
Minimal live-reload server — no webbrowser calls, ever.
Watches *.html, *.css, *.js, *.svg and tells open tabs to refresh via SSE.

Usage:  python serve.py
Then open http://localhost:8000 once manually.
"""
import http.server
import os
import re
import sys
import threading
import time

PORT = 8000
WATCH_EXTS = {'.html', '.css', '.js', '.svg'}

# ---------- shared state ----------
_version = [0]
_lock = threading.Lock()

def bump():
    with _lock:
        _version[0] += 1

def current_version():
    with _lock:
        return _version[0]

# ---------- file watcher ----------
def watch_files(root='.'):
    snapshots = {}
    def scan():
        m = {}
        for dirpath, _, files in os.walk(root):
            for f in files:
                if os.path.splitext(f)[1] in WATCH_EXTS:
                    p = os.path.join(dirpath, f)
                    try:
                        m[p] = os.path.getmtime(p)
                    except OSError:
                        pass
        return m

    snapshots = scan()
    while True:
        time.sleep(0.4)
        current = scan()
        if current != snapshots:
            changed = [p for p in current if current[p] != snapshots.get(p)]
            if changed:
                print(f'  changed: {", ".join(os.path.relpath(p) for p in changed)}')
                bump()
        snapshots = current

# ---------- HTTP handler ----------
INJECT = b"""
<script>
(function(){
  var v=null;
  function poll(){
    fetch('/__reload__?v='+(v||''))
      .then(function(r){return r.text();})
      .then(function(t){
        t=t.trim();
        if(v!==null && t!==v){ location.reload(); }
        v=t; setTimeout(poll,0);
      })
      .catch(function(){ setTimeout(poll,2000); });
  }
  poll();
})();
</script>
"""

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/__reload__'):
            # long-poll: hold until version changes, then return new version
            client_v = None
            try:
                qs = self.path.split('?v=', 1)
                if len(qs) > 1 and qs[1]:
                    client_v = int(qs[1])
            except ValueError:
                pass

            deadline = time.time() + 25  # 25 s max hold
            while time.time() < deadline:
                v = current_version()
                if client_v is None or v != client_v:
                    body = str(v).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                time.sleep(0.3)

            # timeout — return current version so client re-polls
            body = str(current_version()).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        # Serve file normally; inject reload script into HTML responses
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, 'index.html')

        if path.endswith('.html') and os.path.isfile(path):
            with open(path, 'rb') as f:
                data = f.read()
            data = data.replace(b'</body>', INJECT + b'</body>', 1)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return

        # Everything else (incl. video) goes through a Range-aware static server,
        # so browsers can stream/seek instead of waiting on the whole file.
        self._serve_static(path)

    def _serve_static(self, path):
        # Directory listings / redirects: let the stdlib handler deal with them.
        if os.path.isdir(path) or not os.path.isfile(path):
            return super().do_GET()

        try:
            fs = os.stat(path)
        except OSError:
            self.send_error(404, 'File not found')
            return

        size = fs.st_size
        ctype = self.guess_type(path)
        start, end, status = 0, size - 1, 200

        rng = self.headers.get('Range')
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)\s*$', rng)
            if m:
                g1, g2 = m.group(1), m.group(2)
                if g1 == '' and g2:                 # suffix: last N bytes
                    start, end = max(0, size - int(g2)), size - 1
                elif g1:
                    start = int(g1)
                    end = int(g2) if g2 else size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        if self.command == 'HEAD':
            return
        with open(path, 'rb') as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def log_message(self, fmt, *args):
        # suppress per-request noise; file changes are printed by watcher
        pass

# ---------- main ----------
if __name__ == '__main__':
    watcher = threading.Thread(target=watch_files, daemon=True)
    watcher.start()

    server = http.server.ThreadingHTTPServer(('', PORT), Handler)
    print(f'Serving at http://localhost:{PORT}')
    print('Open that URL once — tabs reload automatically on file changes.')
    print('Ctrl-C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
