from django.contrib import admin
from .models import VideoUpload, ViolationRecord

@admin.register(VideoUpload)
class VideoUploadAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'video_name', 'location', 'status', 'violation_count', 'uploaded_at']
    list_filter = ['status', 'uploaded_at']
    search_fields = ['video_name', 'user__username']

@admin.register(ViolationRecord)
class ViolationRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'video', 'timestamp', 'vehicle_type', 'frame_number']
    list_filter = ['vehicle_type']