import cv2
import numpy as np
from ultralytics import YOLO
import os
import time
from datetime import datetime
from collections import defaultdict

from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections

from .models import VideoUpload, ViolationRecord

# Define vehicle classes (COCO dataset)
VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck
CLASS_NAMES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}


def process_video_thread(video_id):
    """
    Background thread function to process uploaded video.
    """
    # Close stale database connections inherited from the main thread
    close_old_connections()

    try:
        video_obj = VideoUpload.objects.get(id=video_id)
        video_obj.status = 'processing'
        video_obj.processing_started_at = timezone.now()
        video_obj.progress_percentage = 0
        video_obj.current_frame = 0
        video_obj.save()

        # Paths
        input_path = video_obj.video_file.path
        output_filename = f"processed_{video_id}_{os.path.basename(input_path)}"
        output_path = os.path.join(settings.MEDIA_ROOT, 'processed', output_filename)

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Load YOLOv8 model
        model = YOLO('yolov8n.pt')

        # Open video
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Could not open video file")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        video_obj.fps = fps
        video_obj.total_frames = total_frames
        video_obj.save()

        # Video writer – H.264 codec for browser compatibility
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        # Tracking variables
        next_id = 0
        tracked_vehicles = {}
        violation_count = 0
        frame_num = 0
        violation_records = []

        start_time = time.time()

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_num += 1

            # Vehicle Detection with YOLOv8
            results = model(frame, conf=0.25, verbose=False)[0]
            detections = []
            for box in results.boxes:
                cls = int(box.cls[0])
                if cls in VEHICLE_CLASSES:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    detections.append({
                        'bbox': (x1, y1, x2, y2),
                        'center': (center_x, center_y),
                        'class': cls,
                        'conf': conf
                    })

            # Lane Detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blur, 50, 150)

            mask = np.zeros_like(edges)
            roi_vertices = np.array([[
                (0, height),
                (width // 2 - 50, height // 2 + 50),
                (width // 2 + 50, height // 2 + 50),
                (width, height)
            ]], dtype=np.int32)
            cv2.fillPoly(mask, roi_vertices, 255)
            roi_edges = cv2.bitwise_and(edges, mask)

            lines = cv2.HoughLinesP(roi_edges, 1, np.pi / 180, threshold=50,
                                    minLineLength=100, maxLineGap=50)

            left_lines, right_lines = [], []
            if lines is not None:
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    if x2 == x1:
                        continue
                    slope = (y2 - y1) / (x2 - x1)
                    if slope < -0.5:
                        left_lines.append((x1, y1, x2, y2))
                    elif slope > 0.5:
                        right_lines.append((x1, y1, x2, y2))

            def average_lines(lines):
                if not lines:
                    return None
                x_coords, y_coords = [], []
                for (x1, y1, x2, y2) in lines:
                    x_coords.extend([x1, x2])
                    y_coords.extend([y1, y2])
                if not x_coords:
                    return None
                poly = np.polyfit(y_coords, x_coords, 1)
                y_min = int(min(y_coords))
                y_max = int(max(y_coords))
                x_min = int(np.polyval(poly, y_min))
                x_max = int(np.polyval(poly, y_max))
                return (x_min, y_min, x_max, y_max)

            left_lane = average_lines(left_lines)
            right_lane = average_lines(right_lines)

            # Perspective Transform
            src_pts = np.float32([
                [width * 0.2, height * 0.65],
                [width * 0.8, height * 0.65],
                [width * 0.9, height * 0.9],
                [width * 0.1, height * 0.9]
            ])
            dst_pts = np.float32([
                [width * 0.25, 0],
                [width * 0.75, 0],
                [width * 0.75, height],
                [width * 0.25, height]
            ])
            M = cv2.getPerspectiveTransform(src_pts, dst_pts)
            warped = cv2.warpPerspective(frame, M, (width, height))

            # Violation Detection & Tracking
            for det in detections:
                cx, cy = det['center']
                violation = False
                if cx < width * 0.3 or cx > width * 0.7:
                    violation = True

                matched_id = None
                min_dist = 50
                for tid, data in tracked_vehicles.items():
                    prev_cx, prev_cy = data['center']
                    dist = np.sqrt((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2)
                    if dist < min_dist:
                        min_dist = dist
                        matched_id = tid

                if matched_id is not None:
                    tracked_vehicles[matched_id]['center'] = (cx, cy)
                    tracked_vehicles[matched_id]['bbox'] = det['bbox']
                    tracked_vehicles[matched_id]['class'] = det['class']
                    tracked_vehicles[matched_id]['conf'] = det['conf']

                    if violation and tracked_vehicles[matched_id]['cooldown'] == 0:
                        tracked_vehicles[matched_id]['violation_flag'] = True
                        violation_count += 1
                        tracked_vehicles[matched_id]['cooldown'] = 30
                        timestamp = frame_num / fps
                        violation_records.append(
                            ViolationRecord(
                                video=video_obj,
                                timestamp=timestamp,
                                vehicle_type=CLASS_NAMES[det['class']],
                                frame_number=frame_num,
                                confidence=det['conf']
                            )
                        )
                    else:
                        tracked_vehicles[matched_id]['violation_flag'] = False
                    if tracked_vehicles[matched_id]['cooldown'] > 0:
                        tracked_vehicles[matched_id]['cooldown'] -= 1
                else:
                    tracked_vehicles[next_id] = {
                        'center': (cx, cy),
                        'bbox': det['bbox'],
                        'class': det['class'],
                        'conf': det['conf'],
                        'violation_flag': violation,
                        'cooldown': 30 if violation else 0
                    }
                    if violation:
                        violation_count += 1
                        timestamp = frame_num / fps
                        violation_records.append(
                            ViolationRecord(
                                video=video_obj,
                                timestamp=timestamp,
                                vehicle_type=CLASS_NAMES[det['class']],
                                frame_number=frame_num,
                                confidence=det['conf']
                            )
                        )
                    next_id += 1

                # Annotate frame
                x1, y1, x2, y2 = det['bbox']
                color = (0, 0, 255) if violation else (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{CLASS_NAMES[det['class']]} {det['conf']:.2f}"
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            if left_lane:
                cv2.line(frame, (left_lane[0], left_lane[1]), (left_lane[2], left_lane[3]), (0, 255, 0), 3)
            if right_lane:
                cv2.line(frame, (right_lane[0], right_lane[1]), (right_lane[2], right_lane[3]), (0, 255, 0), 3)

            cv2.putText(frame, f"Violations: {violation_count}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            out.write(frame)

            # Update progress
            if frame_num % 30 == 0 or frame_num == total_frames:
                elapsed = time.time() - start_time
                fps_processing = frame_num / elapsed if elapsed > 0 else 0
                remaining_frames = total_frames - frame_num
                eta_seconds = int(remaining_frames / fps_processing) if fps_processing > 0 else 0

                progress = int((frame_num / total_frames) * 100)

                video_obj.refresh_from_db()
                video_obj.progress_percentage = progress
                video_obj.current_frame = frame_num
                video_obj.estimated_seconds_remaining = eta_seconds
                video_obj.save(update_fields=['progress_percentage', 'current_frame', 'estimated_seconds_remaining'])

                close_old_connections()

        # Finalization
        cap.release()
        out.release()
        cv2.destroyAllWindows()

        ViolationRecord.objects.bulk_create(violation_records)

        video_obj.refresh_from_db()
        video_obj.violation_count = violation_count
        video_obj.processed_video.name = f"processed/{output_filename}"
        video_obj.status = 'completed'
        video_obj.progress_percentage = 100
        video_obj.current_frame = total_frames
        video_obj.estimated_seconds_remaining = 0
        video_obj.save()

    except Exception as e:
        video_obj = VideoUpload.objects.get(id=video_id)
        video_obj.status = 'failed'
        video_obj.processing_log = str(e)
        video_obj.save()
        raise
    finally:
        close_old_connections()