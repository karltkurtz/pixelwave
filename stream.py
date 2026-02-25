import io
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from picamera2 import Picamera2

# Latest frame cache
latest_frame = None
frame_lock = threading.Lock()

# Camera setup
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

def capture_loop():
    global latest_frame
    while True:
        try:
            buf = io.BytesIO()
            picam2.capture_file(buf, format='jpeg')
            with frame_lock:
                latest_frame = buf.getvalue()
        except Exception:
            pass
        time.sleep(0.1)

capture_thread = threading.Thread(target=capture_loop, daemon=True)
capture_thread.start()

# Wait for first frame
time.sleep(1)

class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if 'action=snapshot' in self.path or 'action=stream' in self.path:
            with frame_lock:
                frame = latest_frame
            if frame is None:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', len(frame))
            self.send_header('Cache-Control', 'no-cache, no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(frame)
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