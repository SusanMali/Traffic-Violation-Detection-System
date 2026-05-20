import io
import os
import mimetypes
import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib import messages
from django.http import HttpResponse, FileResponse, JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.views.static import serve
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from .forms import SignUpForm, VideoUploadForm
from .models import VideoUpload, ViolationRecord
from .utils import process_video_thread


def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)
            return redirect('dashboard')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


@login_required
def dashboard_view(request):
    videos = VideoUpload.objects.filter(user=request.user)
    total_videos = videos.count()
    processed_videos = videos.filter(status='completed').count()
    total_violations = sum(video.violation_count for video in videos.filter(status='completed'))
    context = {
        'total_videos': total_videos,
        'processed_videos': processed_videos,
        'total_violations': total_violations,
    }
    return render(request, 'dashboard.html', context)


@login_required
def upload_video_view(request):
    if request.method == 'POST':
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            video = form.save(commit=False)
            video.user = request.user
            video.save()
            thread = threading.Thread(target=process_video_thread, args=(video.id,))
            thread.start()
            messages.success(request, 'Video uploaded and processing started.')
            return redirect('reports')
    else:
        form = VideoUploadForm()
    return render(request, 'upload_video.html', {'form': form})


@login_required
def reports_view(request):
    videos = VideoUpload.objects.filter(user=request.user).order_by('-uploaded_at')
    return render(request, 'reports.html', {'videos': videos})


@login_required
def report_detail_view(request, pk):
    video = get_object_or_404(VideoUpload, pk=pk, user=request.user)
    violations = video.violations.all().order_by('timestamp')
    return render(request, 'report_detail.html', {'video': video, 'violations': violations})


@login_required
def download_pdf_report(request, pk):
    video = get_object_or_404(VideoUpload, pk=pk, user=request.user)
    violations = video.violations.all().order_by('timestamp')
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        title = Paragraph(f"Traffic Violation Report: {video.video_name}", styles['Title'])
        elements.append(title)
        info_data = [
            ['Video Name', video.video_name],
            ['Location', video.location],
            ['Uploaded At', video.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')],
            ['Total Violations', str(video.violation_count)],
            ['Total Frames', str(video.total_frames)],
            ['FPS', f"{video.fps:.2f}"]
        ]
        info_table = Table(info_data)
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 12),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(info_table)
        elements.append(Paragraph("<br/><br/>", styles['Normal']))
        if violations.exists():
            violation_data = [['Timestamp (s)', 'Vehicle Type', 'Frame Number', 'Confidence']]
            for v in violations:
                violation_data.append([
                    f"{v.timestamp:.2f}",
                    v.vehicle_type,
                    str(v.frame_number),
                    f"{v.confidence:.2f}"
                ])
            table = Table(violation_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 12),
                ('BACKGROUND', (0,1), (-1,-1), colors.beige),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph("No violations recorded.", styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f'report_{video.id}.pdf')
    except Exception as e:
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('report_detail', pk=pk)


@login_required
def get_processing_progress(request, pk):
    video = get_object_or_404(VideoUpload, pk=pk, user=request.user)
    data = {
        'status': video.status,
        'progress_percentage': video.progress_percentage,
        'current_frame': video.current_frame,
        'total_frames': video.total_frames,
        'violation_count': video.violation_count,
        'estimated_seconds_remaining': video.estimated_seconds_remaining,
    }
    return JsonResponse(data)


@login_required
@require_POST
def delete_report(request, pk):
    video = get_object_or_404(VideoUpload, pk=pk, user=request.user)
    if video.video_file:
        video.video_file.delete(save=False)
    if video.processed_video:
        video.processed_video.delete(save=False)
    video.delete()
    messages.success(request, f'Report "{video.video_name}" deleted successfully.')
    return redirect('reports')


@login_required
def profile_view(request):
    return render(request, 'profile.html', {'user': request.user})


@login_required
def play_video_view(request, pk):
    video = get_object_or_404(VideoUpload, pk=pk, user=request.user)
    if not video.processed_video:
        messages.error(request, 'Processed video not available.')
        return redirect('report_detail', pk=pk)
    path = video.processed_video.path
    content_type, _ = mimetypes.guess_type(path)
    content_type = content_type or 'video/mp4'
    response = serve(request, os.path.basename(path), os.path.dirname(path))
    response['Content-Type'] = content_type
    response['Accept-Ranges'] = 'bytes'
    return response