# Traffic-Violation-Detection-System
Traffic Violation Detection System A full‑stack web application that automatically detects lane‑change violations in traffic videos using YOLOv8 for vehicle detection and classical computer vision for lane analysis. The system processes uploaded videos, annotates them with bounding boxes and lane lines, and generates downloadable PDF reports.

 Features
User Authentication – Sign up, login, and logout.
Video Upload – Upload traffic videos (MP4, AVI, etc.) with location and name.
Real‑Time Processing – Background thread processes videos without blocking the interface.
Vehicle Detection – YOLOv8 detects cars, motorcycles, buses, and trucks in every frame.
Lane Detection – Canny edge detector + Hough Transform automatically identify lane boundaries.
Violation Counting – Tracks vehicles across frames and counts lane‑change violations only when they clearly cross a lane divider (hysteresis + cooldown).
Annotated Output – Processed video is saved with bounding boxes (green = normal, red = violation) and lane overlays.
Progress Tracking – Real‑time progress bar with estimated time remaining.
PDF Reports – Download violation reports with timestamps, vehicle types, and confidence scores.
Admin Dashboard – View all uploaded videos and violations via Django admin.

Tech Stack
Backend	Django 4.2, Python 3.10+
Database	MySQL (with mysqlclient)
Frontend	HTML5, CSS3, Bootstrap 5, JavaScript
Computer Vision	OpenCV, YOLOv8 (Ultralytics), NumPy
Reporting	ReportLab (PDF generation)
