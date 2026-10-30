import cv2
import numpy as np
from ultralytics import YOLO
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

# Load the edge-optimized YOLO26 nano model
model = YOLO("yolo26n.pt")

# Force integer camera index for standard V4L2 hardware pipeline
#camera_index = 2 # Infrared, works in dark rooms
camera_index = 4 # RGB
cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)

# Enforce raw hardware pixel format decoding for the D435 sensor
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

if not cap.isOpened():
    print(f"Error: Cannot open RealSense RGB stream at index: {camera_index}")
    exit()

# Global variables for cross-thread frame streaming
output_frame = None
lock = threading.Lock()

class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global output_frame, lock
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            while True:
                with lock:
                    if output_frame is None:
                        continue
                    
                    # Encode array as a highly compressed JPEG (75% quality) 
                    # Lowering quality optimizes throughput over drone Wi-Fi connections
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
                    # Clean handle browser disconnect/refresh events smoothly
                    break
                time.sleep(0.04) # Caps network push matching your processing speed
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><head><title>Drone Stream</title></head>"
                             b"<body style='background:#111; text-align:center; margin-top:50px;'>"
                             b"<img src='/stream.mjpg' style='border:2px solid #333; box-shadow: 0 4px 8px rgba(0,0,0,0.5);'/>"
                             b"</body></html>")

def start_web_server():
    # Bind to port 8080 on all local network adapters
    server = HTTPServer(('0.0.0.0', 8080), StreamHandler)
    print("-------------------------------------------------------")
    print("Web Stream Active! Open on laptop browser:")
    print("http://192.168.10.210:8080")
    print("-------------------------------------------------------")
    server.serve_forever()

# Launch network background handler thread as a daemon service
server_thread = threading.Thread(target=start_web_server, daemon=True)
server_thread.start()

try:
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        # Force verbose to guarantee PyTorch stays on the stable internal pathway
        results_list = model(frame, classes=0, verbose=True)
        results = results_list[0]

        # Extract annotated layout canvas frame using index zero layer
        annotated_frame = results.plot()

        # Render a small dot explicitly at target centers to track coordinates visually
        if hasattr(results, 'boxes') and results.boxes is not None:
            xyxy_array = results.boxes.xyxy.numpy()
            for box in xyxy_array:
                x_min, y_min, x_max, y_max = box
                cx, cy = int((x_min + x_max) / 2), int((y_min + y_max) / 2)
                # Draw a bright green target crosshair indicator at the midpoint coordinates
                cv2.circle(annotated_frame, (cx, cy), 5, (0, 255, 0), -1)

        # Enforce strict raw layout array formatting to prevent split-screen browser bugs
        clean_web_frame = np.ascontiguousarray(annotated_frame, dtype=np.uint8)

        with lock:
            output_frame = clean_web_frame

except KeyboardInterrupt:
    print("\nShutting down stream servers and cleaning tracking instances...")
finally:
    cap.release()
