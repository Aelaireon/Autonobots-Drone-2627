import cv2
import numpy as np
from ultralytics import YOLO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import socket

# DYNAMIC INTERFACE LOOKUP: Automatically fetches the current network IP
def get_current_ipv4():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "0.0.0.0"

current_ip = get_current_ipv4()

# Load your 320px high-speed model folder
model = YOLO("yolo26n_320_ncnn_model")

# System Variables for Cross-Thread communication
frame_lock = threading.Lock()
raw_frame = None
output_frame = None
keep_running = True

# PERFORMANCE FIX: Track frame freshness to stop streaming thread from over-encoding
frame_updated = False
condition = threading.Condition()

# Thread 1: Dedicated Hardware Camera Reader Loop (Maximized for USB 3.0)
def camera_capture_thread():
    global raw_frame, keep_running
    camera_index = 4  # 4 for RGB, 2 for IR Night Vision
    cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    
    # Configure baseline USB 3.0 hardware capabilities
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # =========================================================================
    # OPTIONAL MANUAL CAMERA CONTROLS (Kept exactly as requested)
    # =========================================================================
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)      # 1 = Manual Mode, 3 = Auto Mode
    cap.set(cv2.CAP_PROP_EXPOSURE, 100)         # Shutter speed / exposure value (typically 1 to 5000)
    cap.set(cv2.CAP_PROP_GAIN, 100)             # Sensor gain / sensitivity value (typically 0 to 254)
    # =========================================================================

    if not cap.isOpened():
        print(f"Error: Cannot open camera index {camera_index}")
        keep_running = False
        return

    while keep_running:
        ret, frame = cap.read()
        if ret and frame is not None:
            with frame_lock:
                raw_frame = frame

    cap.release()

# MJPEG Browser Network Interface Configuration
class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global output_frame, frame_updated
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            while keep_running:
                # PERFORMANCE FIX: Only encode when a brand new frame is ready
                with condition:
                    while not frame_updated:
                        if not condition.wait(timeout=0.1):
                            break
                    frame_updated = False

                if output_frame is None:
                    continue

                # Direct array compression only when matching processing rate
                rc, encoded_jpeg = cv2.imencode('.jpg', output_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if not rc:
                    continue
                bytes_jpeg = encoded_jpeg.tobytes()
                try:
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-type', 'image/jpeg')
                    self.send_header('Content-length', str(len(bytes_jpeg)))
                    self.end_headers()
                    self.wfile.write(bytes_jpeg)
                    self.wfile.write(b'\r\n')
                except (ConnectionResetError, BrokenPipeError):
                    break
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><head><title>Drone Stream</title></head>"
                             b"<body style='background:#111; text-align:center; margin-top:50px;'>"
                             b"<img src='/stream.mjpg' style='border:2px solid #333;'/>"
                             b"</body></html>")

def start_web_server():
    server = ThreadingHTTPServer(('0.0.0.0', 8080), StreamHandler)
    server.serve_forever()

# Start background network threads
threading.Thread(target=camera_capture_thread, daemon=True).start()
threading.Thread(target=start_web_server, daemon=True).start()

print("-------------------------------------------------------")
print(f"High-Throughput USB3 Tracker Active: http://{current_ip}:8080")
print("-------------------------------------------------------")

# Thread 2 (Main Thread): High-Speed Inference Worker
try:
    while keep_running:
        with frame_lock:
            if raw_frame is None:
                continue
            # PERFORMANCE FIX: Direct assignment pointer reference instead of deep array copying
            working_canvas = raw_frame

        start_time = time.time()

        # Feed image directly, model handles the optimized downscaling internally
        results_list = model(working_canvas, classes=0, verbose=False, conf=0.4, imgsz=320)
        results = results_list[0]

        # Draw native bounding boxes and labels
        annotated_frame = results.plot()

        # Overlay green midpoint tracking dots
        if results.boxes is not None:
            xyxy_array = results.boxes.xyxy.cpu().numpy()
            for box in xyxy_array:
                x_min, y_min, x_max, y_max = box
                cx = int((x_min + x_max) / 2)
                cy = int((y_min + y_max) / 2)
                cv2.circle(annotated_frame, (cx, cy), 6, (0, 255, 0), -1)

        latency = (time.time() - start_time) * 1000
        fps = 1000 / latency if latency > 0 else 0
        print(f"[TRACKING] Latency: {latency:.1f}ms ({fps:.1f} FPS)    ", end="\r")

        clean_web_frame = np.ascontiguousarray(annotated_frame, dtype=np.uint8)

        # Safely alert streaming threads that a fresh frame is ready
        with condition:
            output_frame = clean_web_frame
            frame_updated = True
            condition.notify_all()

except KeyboardInterrupt:
    print("\nStopping drone tracker...")
    keep_running = False
