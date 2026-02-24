import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from picamera2 import Picamera2

lock = threading.Lock()
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if 'action=snapshot' in self.path or 'action=stream' in self.path:
            try:
                with lock:
                    buf = io.BytesIO()
                    picam2.capture_file(buf, format='jpeg')
                    frame = buf.getvalue()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', len(frame))
                self.send_header('Cache-Control', 'no-cache, no-store')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(frame)
            except Exception as e:
                self.send_error(500)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass

class StreamingServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

print("Stream running on port 8080")
server = StreamingServer(('', 8080), StreamingHandler)
server.serve_forever()