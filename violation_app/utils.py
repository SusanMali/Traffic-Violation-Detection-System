import cv2
import numpy as np
from ultralytics import YOLO
import os
import time

from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections

from .models import VideoUpload, ViolationRecord


# ================= VEHICLE CLASSES =================
VEHICLE_CLASSES = [2, 3, 5, 7]
CLASS_NAMES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}


# ================= LANE CONFIG =================
LANE_DIVIDERS = [555, 925]  # adjust based on your video


def get_lane_index(cx, dividers):
    if cx < dividers[0]:
        return 0
    elif cx < dividers[1]:
        return 1
    else:
        return 2


def process_video_thread(video_id):
    close_old_connections()

    try:
        video_obj = VideoUpload.objects.get(id=video_id)

        video_obj.status = 'processing'
        video_obj.processing_started_at = timezone.now()
        video_obj.progress_percentage = 0
        video_obj.current_frame = 0
        video_obj.save()

        # ================= PATH =================
        input_path = video_obj.video_file.path
        output_filename = f"processed_{video_id}_{os.path.basename(input_path)}"
        output_path = os.path.join(settings.MEDIA_ROOT, 'processed', output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # ================= MODEL =================
        model = YOLO('yolov8n.pt')

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Could not open video")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        video_obj.fps = fps
        video_obj.total_frames = total_frames
        video_obj.save()

        # ================= VIDEO WRITER =================
        codecs = ['avc1', 'H264', 'mp4v', 'XVID']
        out = None

        for codec in codecs:
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                if out.isOpened():
                    break
                out.release()
            except:
                continue

        if out is None or not out.isOpened():
            raise Exception("No codec available")

        # ================= TRACKING =================
        next_id = 0
        tracked_vehicles = {}
        violation_count = 0
        frame_num = 0
        violation_records = []

        # 🔥 LANE FLASH SYSTEM
        lane_flash = [0] * len(LANE_DIVIDERS)
        FLASH_DURATION = 10

        start_time = time.time()

        # ================= MAIN LOOP =================
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_num += 1

            # ================= DETECTION =================
            results = model(frame, conf=0.15, verbose=False)[0]

            detections = []
            for box in results.boxes:
                cls = int(box.cls[0])

                if cls in VEHICLE_CLASSES:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2

                    detections.append({
                        'bbox': (x1, y1, x2, y2),
                        'center': (cx, cy),
                        'class': cls,
                        'conf': conf
                    })

            # ================= DRAW LANES =================
            for i, div in enumerate(LANE_DIVIDERS):

                if lane_flash[i] > 0:
                    # 🔴 RED when violation
                    color = (0, 0, 255)
                    lane_flash[i] -= 1
                else:
                    # 🟢 NORMAL GREEN
                    color = (0, 255, 0)

                cv2.line(frame, (div, 0), (div, height), color, 4)

            # ================= TRACKING =================
            for det in detections:
                cx, cy = det['center']
                current_lane = get_lane_index(cx, LANE_DIVIDERS)

                matched_id = None
                min_dist = 80

                for tid, data in tracked_vehicles.items():
                    px, py = data['center']
                    dist = np.hypot(cx - px, cy - py)

                    if dist < min_dist:
                        min_dist = dist
                        matched_id = tid

                violation_this_frame = False

                if matched_id is not None:
                    prev_lane = tracked_vehicles[matched_id]['lane_idx']
                    cooldown = tracked_vehicles[matched_id]['cooldown']

                    # 🔥 LANE CHANGE DETECTION
                    if prev_lane != current_lane and cooldown == 0:
                        violation_this_frame = True
                        violation_count += 1

                        tracked_vehicles[matched_id]['cooldown'] = 20

                        # 🔥 WHICH DIVIDER WAS CROSSED
                        crossed_divider = min(prev_lane, current_lane)
                        if crossed_divider < len(lane_flash):
                            lane_flash[crossed_divider] = FLASH_DURATION

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

                    # UPDATE TRACK
                    tracked_vehicles[matched_id]['center'] = (cx, cy)
                    tracked_vehicles[matched_id]['bbox'] = det['bbox']
                    tracked_vehicles[matched_id]['class'] = det['class']
                    tracked_vehicles[matched_id]['conf'] = det['conf']
                    tracked_vehicles[matched_id]['lane_idx'] = current_lane

                    if tracked_vehicles[matched_id]['cooldown'] > 0:
                        tracked_vehicles[matched_id]['cooldown'] -= 1

                else:
                    tracked_vehicles[next_id] = {
                        'center': (cx, cy),
                        'bbox': det['bbox'],
                        'class': det['class'],
                        'conf': det['conf'],
                        'lane_idx': current_lane,
                        'cooldown': 0
                    }
                    next_id += 1

                # ================= DRAW BOX =================
                x1, y1, x2, y2 = det['bbox']
                color = (0, 0, 255) if violation_this_frame else (0, 255, 0)

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                label = f"{CLASS_NAMES[det['class']]} {det['conf']:.2f}"
                cv2.putText(frame, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # 🔥 VIOLATION TEXT
                if violation_this_frame:
                    cv2.putText(frame, "LANE VIOLATION!",
                                (cx - 50, cy),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 0, 255), 2)

            # ================= COUNTER =================
            cv2.putText(frame, f"Violations: {violation_count}",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 2)

            out.write(frame)

            # ================= PROGRESS =================
            if frame_num % 30 == 0 or frame_num == total_frames:
                elapsed = time.time() - start_time
                fps_proc = frame_num / elapsed if elapsed > 0 else 0
                remaining = total_frames - frame_num
                eta = int(remaining / fps_proc) if fps_proc > 0 else 0

                progress = int((frame_num / total_frames) * 100)

                video_obj.refresh_from_db()
                video_obj.progress_percentage = progress
                video_obj.current_frame = frame_num
                video_obj.estimated_seconds_remaining = eta
                video_obj.save(update_fields=[
                    'progress_percentage',
                    'current_frame',
                    'estimated_seconds_remaining'
                ])

                close_old_connections()

        # ================= CLEANUP =================
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