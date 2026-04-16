import os
import uuid
import pickle
import datetime
import time
import shutil
import cv2
import dlib
import face_recognition

from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from .models import User

ATTENDANCE_LOG_DIR = './logs'
for dir_ in [ATTENDANCE_LOG_DIR]:
    if not os.path.exists(dir_):
        os.mkdir(dir_)

def recognize(img):
    embeddings_unknown = face_recognition.face_encodings(img)
    if len(embeddings_unknown) == 0:
        return 'no_persons_found', False
    else:
        embeddings_unknown = embeddings_unknown[0]

    match = False
    matched_user_name = 'unknown_person'
    
    # Query all users with encodings
    users = User.objects.exclude(face_encoding__isnull=True)
    for user in users:
        # Load encoding from BinaryField
        embeddings = pickle.loads(user.face_encoding)[0]
        # Use a stricter tolerance (default is 0.6) to prevent false positives
        match = face_recognition.compare_faces([embeddings], embeddings_unknown, tolerance=0.45)[0]
        if match:
            matched_user_name = user.username
            break

    return matched_user_name, match

@csrf_exempt
def login(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        filename = f"{uuid.uuid4()}.png"
        
        with open(filename, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        user_name, match_status = recognize(cv2.imread(filename))

        if match_status:
            epoch_time = time.time()
            date = time.strftime('%Y%m%d', time.localtime(epoch_time))
            with open(os.path.join(ATTENDANCE_LOG_DIR, '{}.csv'.format(date)), 'a') as f:
                f.write('{},{},{}\n'.format(user_name, datetime.datetime.now(), 'IN'))
        
        if os.path.exists(filename):
            os.remove(filename)

        return JsonResponse({'user': user_name, 'match_status': bool(match_status)})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def logout(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        filename = f"{uuid.uuid4()}.png"
        
        with open(filename, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        user_name, match_status = recognize(cv2.imread(filename))

        if match_status:
            epoch_time = time.time()
            date = time.strftime('%Y%m%d', time.localtime(epoch_time))
            with open(os.path.join(ATTENDANCE_LOG_DIR, '{}.csv'.format(date)), 'a') as f:
                f.write('{},{},{}\n'.format(user_name, datetime.datetime.now(), 'OUT'))

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
            # Create/update user in database
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    'face_encoding': pickle.dumps(embeddings)
                }
            )
            # Save the image file to the User model (Django handles storage)
            user.face_image.save(f"{username}.png", file_obj, save=True)
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
    if request.method == 'GET':
        filename = 'out.zip'
        shutil.make_archive(filename[:-4], 'zip', ATTENDANCE_LOG_DIR)
        
        return FileResponse(open(filename, 'rb'), as_attachment=True, filename=filename)
    return JsonResponse({'error': 'Invalid request'}, status=400)
