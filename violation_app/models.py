from django.db import models
from django.contrib.auth.models import User

class VideoUpload(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='videos')
    video_file = models.FileField(upload_to='uploads/', max_length=255)
    video_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    processed_video = models.FileField(upload_to='processed/', blank=True, null=True, max_length=255)
    violation_count = models.IntegerField(default=0)
    processing_log = models.TextField(blank=True)
    fps = models.FloatField(default=0.0)
    total_frames = models.IntegerField(default=0)
    
    # Progress tracking
    progress_percentage = models.IntegerField(default=0)
    current_frame = models.IntegerField(default=0)
    
    # ETA tracking
    processing_started_at = models.DateTimeField(null=True, blank=True)
    estimated_seconds_remaining = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.video_name} - {self.user.username}"

class ViolationRecord(models.Model):
    video = models.ForeignKey(VideoUpload, on_delete=models.CASCADE, related_name='violations')
    timestamp = models.FloatField()
    vehicle_type = models.CharField(max_length=20)
    frame_number = models.IntegerField()
    confidence = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.vehicle_type} at {self.timestamp:.2f}s"