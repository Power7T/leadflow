import socket, select, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ProxyHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        address = self.path.split(':', 1)
        address[1] = int(address[1]) or 443
        try:
            s = socket.create_connection(address, timeout=self.timeout)
        except Exception as e:
            self.send_error(502)
            return
        self.send_response(200, 'Connection Established')
        self.end_headers()
        conns = [self.connection, s]
        self.close_connection = False
        while True:
            r, w, x = select.select(conns, [], conns, self.timeout)
            if x:
                break
            for i in r:
                other = conns[1] if i is conns[0] else conns[0]
                data = i.recv(8192)
                if not data:
                    return
                other.sendall(data)
    
    def do_GET(self):
        import urllib.request, urllib.error
        req = urllib.request.Request(self.path, headers=dict(self.headers))
        try:
            with urllib.request.urlopen(req) as response:
                self.send_response(response.status)
                for k, v in response.getheaders():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response.read())
        except Exception:
            self.send_error(500)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

if __name__ == '__main__':
    for port in [8080]:
        try:
            server = ThreadedHTTPServer(('127.0.0.1', 8080), ProxyHTTPRequestHandler)
            print("Proxy server running on 127.0.0.1:8080...")
            server.serve_forever()
        except Exception:
            pass

