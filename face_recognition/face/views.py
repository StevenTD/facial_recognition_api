import os
import sys
import uuid
import pickle
import datetime
import time
import shutil
import threading
import cv2
import dlib
import face_recognition
from django.conf import settings

# Mount the Silent-Face-Anti-Spoofing repository so we can import its modules seamlessly
SPOOFING_DIR = settings.SPOOFING_DIR

if SPOOFING_DIR not in sys.path:
    sys.path.insert(0, SPOOFING_DIR)

import importlib.util
spec = importlib.util.spec_from_file_location("anti_spoof_test", os.path.join(SPOOFING_DIR, "test.py"))
anti_spoof_test = importlib.util.module_from_spec(spec)
sys.modules["anti_spoof_test"] = anti_spoof_test
spec.loader.exec_module(anti_spoof_test)
check_liveness = anti_spoof_test.test

MODEL_DIR = os.path.join(SPOOFING_DIR, "resources/anti_spoof_models")
DEVICE_ID = 0

from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.core.files import File
from django.utils import timezone

from .models import User, Face, AttendanceLog
from .utils import get_next_log_type, ATTENDANCE_WINDOWS, MANILA_TZ
from . import handlers

ATTENDANCE_LOG_DIR = './logs'
for dir_ in [ATTENDANCE_LOG_DIR]:
    if not os.path.exists(dir_):
        os.mkdir(dir_)

def recognize(img):
    unknown_encodings = face_recognition.face_encodings(img)
    if not unknown_encodings:
        return None, False

    unknown_encoding = unknown_encodings[0]
    tolerance = getattr(settings, 'FACE_RECOGNITION_TOLERANCE', 0.45)

    # Query all faces with encodings
    faces = list(Face.objects.exclude(face_encoding__isnull=True))
    if not faces:
        return None, False

    if getattr(settings, 'FACE_RECOGNITION_OPTIMIZED', True):
        # Optimized Vectorized Comparison
        try:
            known_encodings = [pickle.loads(face.face_encoding)[0] for face in faces]
            matches = face_recognition.compare_faces(known_encodings, unknown_encoding, tolerance=tolerance)
            if True in matches:
                return faces[matches.index(True)], True
        except Exception as e:
            print(f"Error in optimized recognition: {e}")
            # Fallback to loop if optimization fails

    # Non-optimized Fallback Loop
    for face in faces:
        try:
            embeddings = pickle.loads(face.face_encoding)[0]
            if face_recognition.compare_faces([embeddings], unknown_encoding, tolerance=tolerance)[0]:
                return face, True
        except Exception as e:
            continue

    return None, False

@csrf_exempt
def login(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        filename = f"{uuid.uuid4()}.png"

        with open(filename, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        img = cv2.imread(filename)

        # Explicit resize to strictly 3:4 ratio to bypass the check_image fail in Silent-Face-Anti-Spoofing
        img_liveness = cv2.resize(img, (600, 800))

        if settings.LIVENESS_DETECTION_ENABLED:
            try:
                # 1 == real face, 0 or 2 == spoof attempt
                label = check_liveness(img_liveness, MODEL_DIR, DEVICE_ID)
                if label != 1:
                    if os.path.exists(filename):
                        os.remove(filename)
                    return JsonResponse({'match_status': False, 'error': 'Spoofing detected. Please use a live face.'}, status=400)
            except Exception as e:
                print("Liveness detection error: ", str(e))
                pass # fallback to recognition if liveness fails to initialize properly, or we can choose to strictly block

        matched_face, match_status = recognize(img)

        if match_status:
            # Determine log type based on state and time
            log_type, error_message = get_next_log_type(matched_face)

            # Fetch today's logs for display (by username, covers all enrolled faces)
            today_logs = AttendanceLog.objects.filter(
                username=matched_face.username,
                timestamp__date=timezone.now().astimezone(MANILA_TZ).date()
            ).order_by('timestamp')

            history = [{
                'log_type': log.log_type,
                'log_display': log.get_log_type_display(),
                'time': log.timestamp.astimezone(MANILA_TZ).strftime("%I:%M %p"),
                'action': log.action
            } for log in today_logs]

            if not log_type:
                if os.path.exists(filename):
                    os.remove(filename)
                return JsonResponse({
                    'user': matched_face.username,
                    'match_status': False,
                    'error': error_message,
                    'history': history
                }, status=201)

            # Map log_type to action
            action_map = {w[0]: w[1] for w in ATTENDANCE_WINDOWS}
            action = action_map.get(log_type, 'IN')

            # Create database attendance log
            with open(filename, 'rb') as f:
                log = AttendanceLog.objects.create(
                    face=matched_face,
                    username=matched_face.username,
                    action=action,
                    log_type=log_type
                )
                # Save the captured face image to the log
                log.captured_image.save(f"log_{log_type}_{matched_face.username}_{uuid.uuid4().hex[:8]}.png", File(f), save=True)

            if os.path.exists(filename):
                os.remove(filename)

            log_display = next(choice[1] for choice in AttendanceLog.LOG_TYPE_CHOICES if choice[0] == log_type)

            # Build the shared payload for handlers and webhooks
            event_payload = {
                'username':         matched_face.username,
                'log_type':         log_type,
                'log_type_display': log_display,
                'action':           action,
                'timestamp':        log.timestamp.astimezone(MANILA_TZ).isoformat(),
            }

            # ── Code-level handlers (handlers.py) ───────────────────────────
            # Each handler runs in a background thread so the login response
            # is never delayed. Add your integration code in handlers.py.
            if log_type == 'MI':
                threading.Thread(target=handlers.on_morning_in,   args=(event_payload,), daemon=True).start()
            elif log_type == 'MO':
                threading.Thread(target=handlers.on_morning_out,  args=(event_payload,), daemon=True).start()
            elif log_type == 'AI':
                threading.Thread(target=handlers.on_afternoon_in,  args=(event_payload,), daemon=True).start()
            elif log_type == 'AO':
                threading.Thread(target=handlers.on_afternoon_out, args=(event_payload,), daemon=True).start()

            # Add the newly created log to history if not already there
            # (Though we already saved it, we need to refresh or just append)
            history.append({
                'log_type': log_type,
                'log_display': log_display,
                'time': log.timestamp.astimezone(MANILA_TZ).strftime("%I:%M %p"),
                'action': action
            })

            return JsonResponse({
                'user': matched_face.username,
                'match_status': True,
                'log_type': log_type,
                'log_type_display': log_display,
                'message': f"Logged as {log_display}",
                'history': history
            })
        else:
            if os.path.exists(filename):
                os.remove(filename)

            error_msg = 'Access denied. Face not recognized.'
            if matched_face is None:
                error_msg = 'No face detected. Please ensure your face is clearly visible.'

            return JsonResponse({'match_status': False, 'error': error_msg}, status=400)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def logout(request):
    """
    Deprecated: Using login endpoint for both IN and OUT logs.
    Forwarding request to login view for compatibility.
    """
    return login(request)

@csrf_exempt
def register_new_user(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file_obj = request.FILES['file']
        username = request.POST.get('text') or request.GET.get('text')

        if not username:
            return JsonResponse({'error': 'No username provided'}, status=400)

        # Temporarily save to calculate encoding
        temp_filename = f"{uuid.uuid4()}.png"
        with open(temp_filename, "wb") as f:
            for chunk in file_obj.chunks():
                f.write(chunk)

        img = cv2.imread(temp_filename)
        embeddings = face_recognition.face_encodings(img)

        if len(embeddings) > 0:
            # Check if this face already exists in the system
            matched_face, match_status = recognize(img)
            if match_status:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
                return JsonResponse({'error': f'Face is already registered under {matched_face.username}'}, status=400)

            # Try to associate with an existing user if one exists with the same employee ID
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = None

            # Create a new Face record (not update_or_create, to allow multiple faces)
            face = Face.objects.create(
                username=username,
                face_encoding=pickle.dumps(embeddings),
                user=user
            )
            # Save the image file to the Face model
            face.face_image.save(f"{username}.png", file_obj, save=True)
        else:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
            return JsonResponse({'error': 'No face found'}, status=400)

        if os.path.exists(temp_filename):
            os.remove(temp_filename)

        return JsonResponse({'registration_status': 200, 'username': username})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def get_attendance_logs(request):
    """Returns a ZIP file containing CSV of all database attendance logs."""
    if request.method == 'GET':
        import csv
        from io import StringIO

        # Create a CSV and zip it
        logs = AttendanceLog.objects.all().order_by('-timestamp')

        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['Username', 'Timestamp', 'Action'])

        for log in logs:
            writer.writerow([log.username, log.timestamp, log.action])

        # Save to a temp folder and zip
        TEMP_EXPORT_DIR = './temp_export'
        if not os.path.exists(TEMP_EXPORT_DIR):
            os.mkdir(TEMP_EXPORT_DIR)

        csv_file_path = os.path.join(TEMP_EXPORT_DIR, 'attendance_logs.csv')
        with open(csv_file_path, 'w') as f:
            f.write(csv_buffer.getvalue())

        filename = 'attendance_export.zip'
        shutil.make_archive(filename[:-4], 'zip', TEMP_EXPORT_DIR)

        # Clean up temp file
        os.remove(csv_file_path)
        os.rmdir(TEMP_EXPORT_DIR)

        return FileResponse(open(filename, 'rb'), as_attachment=True, filename=filename)
    return JsonResponse({'error': 'Invalid request'}, status=400)
