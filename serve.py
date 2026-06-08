#!/usr/bin/env python3
"""
Live reload server for development.
Automatically refreshes the browser when files change.

Requires: pip install livereload
"""
from livereload import Server

PORT = 8000

server = Server()

# Watch HTML, CSS, and JS files for changes
server.watch('*.html')
server.watch('*.css')
server.watch('*.js')
server.watch('**/*.html')
server.watch('**/*.css')
server.watch('**/*.js')

print(f"Live reload server at http://localhost:{PORT}")
print("Browser will auto-refresh when files change")
server.serve(port=PORT, open_url_delay=None)
