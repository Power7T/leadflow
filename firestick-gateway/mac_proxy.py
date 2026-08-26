import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

class SimpleProxy(BaseHTTPRequestHandler):
    def do_GET(self):
        url = self.path
        req = urllib.request.Request(url, headers=dict(self.headers))
        try:
            with urllib.request.urlopen(req) as response:
                self.send_response(response.status)
                for key, value in response.getheaders():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

if __name__ == '__main__':
    # Try multiple ports if 8080 is in use
    for port in [8080, 8081, 8888, 9999]:
        try:
            server = HTTPServer(('127.0.0.1', port), SimpleProxy)
            print(f"Proxy server running on 127.0.0.1:{port}...")
            server.serve_forever()
            break
        except OSError:
            continue
