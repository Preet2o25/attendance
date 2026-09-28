import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "database.db")
DATASET_DIR = os.path.join(BASE_DIR, "dataset", "students")

# ---- Classroom location (seeded into DB settings table on first run) ----
CLASSROOM_LATITUDE = 23.065684
CLASSROOM_LONGITUDE = 72.440104
ALLOWED_RADIUS_METERS = 100

# ---- Attendance ----
WINDOW_MINUTES = 5
FACE_TOLERANCE = 0.5          # lower = stricter (face_recognition default is 0.6)

# ---- Demo mode: uses fixed coordinates instead of browser GPS (face recognition stays real) ----
DEMO_MODE = True
DEMO_LATITUDE = 23.065684       # Classroom coordinates for demo mode
DEMO_LONGITUDE = 72.440104
