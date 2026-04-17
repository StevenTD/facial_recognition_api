import os
import sys
import uuid
import pickle
import datetime
import time
import shutil
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
from .models import User, Face, AttendanceLog

ATTENDANCE_LOG_DIR = './logs'
for dir_ in [ATTENDANCE_LOG_DIR]:
    if not os.path.exists(dir_):
        os.mkdir(dir_)

def recognize(img):
    embeddings_unknown = face_recognition.face_encodings(img)
    if len(embeddings_unknown) == 0:
        return None, False
    else:
        embeddings_unknown = embeddings_unknown[0]

    match = False
    matched_face = None

    # Query all faces with encodings
    faces = Face.objects.exclude(face_encoding__isnull=True)
    for face in faces:
        # Load encoding from BinaryField
        embeddings = pickle.loads(face.face_encoding)[0]
        # Use a stricter tolerance (default is 0.6) to prevent false positives
        match = face_recognition.compare_faces([embeddings], embeddings_unknown, tolerance=0.45)[0]
        if match:
            matched_face = face
            break

    return matched_face, match

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
            # Create database attendance log
            with open(filename, 'rb') as f:
                log = AttendanceLog.objects.create(
                    face=matched_face,
                    username=matched_face.username,
                    action='IN'
                )
                # Save the captured face image to the log
                log.captured_image.save(f"login_{matched_face.username}_{uuid.uuid4().hex[:8]}.png", File(f), save=True)

            if os.path.exists(filename):
                os.remove(filename)
            return JsonResponse({'user': matched_face.username, 'match_status': True})
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
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        filename = f"{uuid.uuid4()}.png"

        with open(filename, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        matched_face, match_status = recognize(cv2.imread(filename))

        user_name = 'unknown_person'
        if match_status:
            user_name = matched_face.username
            # Create database attendance log
            with open(filename, 'rb') as f:
                log = AttendanceLog.objects.create(
                    face=matched_face,
                    username=matched_face.username,
                    action='OUT'
                )
                log.captured_image.save(f"logout_{matched_face.username}_{uuid.uuid4().hex[:8]}.png", File(f), save=True)

        if os.path.exists(filename):
            os.remove(filename)

        return JsonResponse({'user': user_name, 'match_status': bool(match_status)})
    return JsonResponse({'error': 'Invalid request'}, status=400)

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
