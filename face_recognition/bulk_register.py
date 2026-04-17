import os
import sys
import django
import pickle
import uuid
from pathlib import Path

# Setup Django environment
# Assuming this script is placed in the 'face_recognition' directory
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'face_config.settings')
django.setup()

import face_recognition
from django.core.files import File
from face.models import Face, User

def bulk_register(folder_path):
    """
    Registers all faces from a directory.
    Filenames should be '[username].ext' (e.g., 'EMP001.jpg').
    """
    if not os.path.exists(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist.")
        return

    valid_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    
    # Collect all image files from folder and subfolders
    all_files_to_process = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith(valid_extensions):
                # Store tuple of (full_path, filename)
                all_files_to_process.append((os.path.join(root, f), f))

    if not all_files_to_process:
        print(f"No valid images found in {folder_path} or its subfolders.")
        return

    print(f"Found {len(all_files_to_process)} potential faces to register...")

    success_count = 0
    fail_count = 0

    for file_path, filename in all_files_to_process:
        base_name = os.path.splitext(filename)[0]
        
        # Extract username: e.g., 'Zac Efron_34' -> 'Zac Efron'
        if '_' in base_name:
            # Splits at the last underscore in case the name itself contains underscores
            username = base_name.rsplit('_', 1)[0]
        else:
            username = base_name

        print(f"Processing {username} ({filename})...", end=' ', flush=True)

        try:
            # Load the image
            image = face_recognition.load_image_file(file_path)
            # Find face encodings
            encodings = face_recognition.face_encodings(image)

            if not encodings:
                print("FAILED (No face detected)")
                fail_count += 1
                continue

            # Check for existing user to link
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = None

            # Create Face record
            face_record = Face.objects.create(
                username=username,
                face_encoding=pickle.dumps(encodings),
                user=user
            )

            # Save the image to the media folder via the model
            with open(file_path, 'rb') as f:
                face_record.face_image.save(filename, File(f), save=True)

            print("SUCCESS")
            success_count += 1

        except Exception as e:
            print(f"FAILED (Error: {str(e)})")
            fail_count += 1

    print("\nBulk Registration Complete!")
    print(f"Successfully registered: {success_count}")
    print(f"Failed: {fail_count}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bulk_register.py <folder_path>")
    else:
        bulk_register(sys.argv[1])
