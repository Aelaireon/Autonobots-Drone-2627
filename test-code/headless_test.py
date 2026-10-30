import os
# Stop CPU core thrashing
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import time
import threading
import cv2
import numpy as np
import pyrealsense2 as rs
from ultralytics import YOLO

# Global variables for thread communication
frame_lock = threading.Lock()
latest_raw_frame = None
is_running = True

def camera_thread_worker():
    """Dedicated background thread to keep the RealSense pipeline alive."""
    global latest_raw_frame, is_running
    
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    
    print("[INFO] Starting RealSense background capture link...")
    pipeline.start(config)
    
    try:
        while is_running:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue
            
            with frame_lock:
                latest_raw_frame = np.asanyarray(color_frame.get_data())
    finally:
        pipeline.stop()
        print("[INFO] RealSense background thread shut down safely.")

# 1. Load the NCNN Model
print("[INFO] Loading NCNN Model...")
model = YOLO("yolo26n_ncnn_model")

# 2. Warm up NCNN to absorb the internal startup lag
print("[INFO] Warming up NCNN graph engines...")
dummy_blank = np.zeros((480, 640, 3), dtype=np.uint8)
_ = model(dummy_blank, imgsz=480, verbose=False)

# 3. Spin up the dedicated hardware capture thread
cam_thread = threading.Thread(target=camera_thread_worker, daemon=True)
cam_thread.start()

print("\n[INFO] Complete system online! Starting detection loop...")

try:
    while True:
        frame_to_process = None
        
        with frame_lock:
            if latest_raw_frame is not None:
                frame_to_process = latest_raw_frame.copy()
                latest_raw_frame = None  # Consume it

        if frame_to_process is None:
            time.sleep(0.005)
            continue

        start_time = time.time()

        # High-speed vertical rotation fix
        frame = cv2.rotate(frame_to_process, cv2.ROTATE_90_CLOCKWISE)

        # High speed optimized inference tracking call
        results = model(frame, classes=0, imgsz=480, verbose=False)

        # Performance delta timing calculations
        inference_ms = (time.time() - start_time) * 1000
        fps = 1000 / inference_ms

        # FIX: Extract the first batch item safely
        first_result = results[0]
        boxes = first_result.boxes
        
        if len(boxes) > 0:
            print(f"[DETECTED] Tracked {len(boxes)} target(s) | Latency: {inference_ms:.1f}ms ({fps:.1f} FPS)")
        else:
            print(f"[SCANNING] Target clear | Latency: {inference_ms:.1f}ms ({fps:.1f} FPS)")

except KeyboardInterrupt:
    print("\n[INFO] Exit signal caught. Exiting system cleanly...")
finally:
    is_running = False
    cam_thread.join(timeout=2.0)
    print("[INFO] System terminated successfully.")
