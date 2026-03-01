import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from picamera2 import Picamera2

# Shared state
frame_lock = threading.Lock()
cam_lock = threading.Lock()
latest_frame = None
auto_reset_event = threading.Event()

def make_camera():
    cam = Picamera2()
    cfg = cam.create_video_configuration(main={"size": (640, 480)})
    cam.configure(cfg)
    cam.start()
    return cam

picam2 = make_camera()

def capture_loop():
    global latest_frame, picam2
    while True:
        if auto_reset_event.is_set():
            with cam_lock:
                try:
                    picam2.stop()
                    picam2.close()
                    picam2 = make_camera()
                    time.sleep(1.5)  # let AE converge before serving frames
                except Exception:
                    pass
                auto_reset_event.clear()
            continue

        try:
            with cam_lock:
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

    def do_POST(self):
        if self.path == '/controls':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                if data.get('auto'):
                    # Signal capture loop to fully recreate the camera (thread-safe reset)
                    auto_reset_event.set()
                else:
                    controls = {}
                    if 'exposure' in data:
                        controls['AeEnable'] = False
                        controls['ExposureTime'] = int(data['exposure'])
                    if 'gain' in data:
                        controls['AnalogueGain'] = float(data['gain'])
                    if 'brightness' in data:
                        controls['Brightness'] = float(data['brightness'])
                    if 'contrast' in data:
                        controls['Contrast'] = float(data['contrast'])
                    if 'saturation' in data:
                        controls['Saturation'] = float(data['saturation'])
                    if controls:
                        with cam_lock:
                            picam2.set_controls(controls)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "detail": str(e)}).encode())
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
