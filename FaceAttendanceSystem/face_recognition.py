import os
import math
from datetime import datetime
from threading import Thread

import cv2
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file, session
from flask_cors import CORS

try:
    import face_recognition
except ImportError:
    face_recognition = None

app = Flask(__name__)
app.secret_key = "face_attendance_student_secure_2026"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "Dataset")
ATTENDANCE_DIR = os.path.join(BASE_DIR, "Attendance")
COURSES_FILE = os.path.join(BASE_DIR, "Courses.csv")

GEOFENCE_LATITUDE = 23.064413
GEOFENCE_LONGITUDE = 72.440341
GEOFENCE_RADIUS = 100

os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(ATTENDANCE_DIR, exist_ok=True)

if not os.path.exists(COURSES_FILE):
  pd.DataFrame(columns=["Course Name", "Course Code"]).to_csv(COURSES_FILE, index=False)

known_faces = []
known_names = []

face_cascade = None
cascade_path = os.path.join(os.path.dirname(cv2.__file__), "data", "haarcascade_frontalface_default.xml")

if hasattr(cv2, "CascadeClassifier") and os.path.exists(cascade_path):
    face_cascade = cv2.CascadeClassifier(cascade_path)
else:
    print("Warning: Haar cascade file not available. Face detection will stay disabled.")

for file_name in os.listdir(DATASET_DIR):
    if not file_name.lower().endswith((".jpg", ".jpeg", ".png")):
        continue

    image = cv2.imread(os.path.join(DATASET_DIR, file_name))
    if image is None:
        continue

    if face_recognition is not None:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb)
        if encodings:
            known_faces.append(encodings[0])
            known_names.append(os.path.splitext(file_name)[0].upper())
    else:
        if face_cascade is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) > 0:
            known_faces.append(np.random.randn(128))
            known_names.append(os.path.splitext(file_name)[0].upper())
def require_role(role):
    return session.get("role") == role
def distance_between(lat1, lon1, lat2, lon2):
    r = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
def check_geofence(lat, lon):
    d = distance_between(lat, lon, GEOFENCE_LATITUDE, GEOFENCE_LONGITUDE)
    return d <= GEOFENCE_RADIUS, d
def clean_course_name(course):
    out = []
    for ch in course:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def mark_attendance(name, course):
    today = datetime.now().strftime("%Y-%m-%d")
    file_name = f"Attendance_{clean_course_name(course)}_{today}.csv"
    path = os.path.join(ATTENDANCE_DIR, file_name)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("Name,Course,Time,Date\n")

    with open(path, "r+", encoding="utf-8") as f:
        rows = f.readlines()
        names = {line.split(",")[0].upper() for line in rows[1:] if line.strip()}
        if name.upper() in names:
            return False

        now = datetime.now()
        f.write(f"{name},{course},{now.strftime('%H:%M:%S')},{now.strftime('%Y-%m-%d')}\n")
        return True


video_running = False
video_capture = None
video_thread = None
current_course = ""


def process_video():
    global video_running, video_capture, current_course

    while video_running:
        if video_capture is None:
            break

        ok, frame = video_capture.read()
        if not ok:
            break

        small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        if face_recognition is not None:
            face_locs = face_recognition.face_locations(rgb)
            face_encs = face_recognition.face_encodings(rgb, face_locs)
        else:
            if face_cascade is None:
                break
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            face_locs = [(y, x + w, y + h, x) for (x, y, w, h) in faces]
            face_encs = [np.random.randn(128) for _ in faces]

        for enc, loc in zip(face_encs, face_locs):
            name = "Unknown"
            accuracy = 0

            if known_faces:
                if face_recognition is not None:
                    dists = face_recognition.face_distance(known_faces, enc)
                else:
                    dists = [np.linalg.norm(np.array(f) - np.array(enc)) for f in known_faces]

                i = int(np.argmin(dists))
                acc = 1 - dists[i]
                accuracy = acc * 100

                if dists[i] < 0.6 and accuracy >= 50:
                    name = known_names[i]

            y1, x2, y2, x1 = [v * 4 for v in loc]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.rectangle(frame, (x1, y2 - 40), (x2, y2), (0, 0, 0), cv2.FILLED)
            label = f"{name} {accuracy:.1f}%" if name != "Unknown" else "Unknown"
            cv2.putText(frame, label, (x1 + 5, y2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            if name != "Unknown":
                mark_attendance(name, current_course)

        cv2.imshow("Face Attendance", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            video_running = False
            break

    if video_capture is not None:
        video_capture.release()
    cv2.destroyAllWindows()


def start_video(course):
    global video_running, video_capture, video_thread, current_course

    if video_running:
        return False, "Attendance already running."

    current_course = course
    video_capture = cv2.VideoCapture(0)
    if not video_capture.isOpened():
        video_capture = None
        return False, "Could not open webcam."

    video_running = True
    video_thread = Thread(target=process_video, daemon=True)
    video_thread.start()
    return True, "Attendance started successfully."


def stop_video():
    global video_running, video_capture, video_thread, current_course
    video_running = False
    if video_capture is not None:
        video_capture.release()
        video_capture = None
    if video_thread and video_thread.is_alive():
        video_thread.join(timeout=2)
    video_thread = None
    current_course = ""
    cv2.destroyAllWindows()


@app.route("/")
def home():
    try:
        courses = pd.read_csv(COURSES_FILE).to_dict("records")
    except Exception:
        courses = []
    return render_template("index.html", courses=courses, radius=GEOFENCE_RADIUS)


@app.route("/student_login", methods=["POST"])
def student_login():
    code = request.form.get("access_code", "").strip()
    if code == "student123":
        session["role"] = "student"
        return jsonify({"status": "success", "message": "Student access granted."})
    return jsonify({"status": "error", "message": "Invalid access code."})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success", "message": "Logged out."})


@app.route("/add_course", methods=["POST"])
def add_course():
    if not require_role("admin"):
        return jsonify({"status": "error", "message": "Admin access required."}), 403

    name = request.form.get("course_name", "").strip()
    code = request.form.get("course_code", "").strip()
    if not name or not code:
        return jsonify({"status": "error", "message": "Course name and code are required."})

    df = pd.read_csv(COURSES_FILE)
    df = pd.concat([df, pd.DataFrame({"Course Name": [name], "Course Code": [code]})], ignore_index=True)
    df.to_csv(COURSES_FILE, index=False)
    return jsonify({"status": "success", "message": "Course added successfully."})


@app.route("/start", methods=["POST"])
def start_attendance():
    if not require_role("student"):
        return jsonify({"status": "error", "message": "Student access required."}), 401

    course = request.form.get("course", "").strip()
    lat = request.form.get("latitude")
    lon = request.form.get("longitude")

    if not course:
        return jsonify({"status": "error", "message": "Select a course."})
    if lat is None or lon is None:
        return jsonify({"status": "error", "message": "Location permission is required."})

    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid location."})

    inside, distance = check_geofence(lat, lon)
    if not inside:
        return jsonify({"status": "error", "message": f"Attendance denied. You are {distance:.1f} meters away. Allowed: {GEOFENCE_RADIUS} meters."})

    ok, msg = start_video(course)
    if not ok:
        return jsonify({"status": "error", "message": msg})

    return jsonify({"status": "success", "message": f"Location verified. You are {distance:.1f} meters away. Face attendance started.", "distance": round(distance, 2)})


@app.route("/stop", methods=["POST"])
def stop_attendance():
    if not require_role("student"):
        return jsonify({"status": "error", "message": "Student access required."}), 401

    stop_video()
    return jsonify({"status": "success", "message": "Attendance stopped."})


@app.route("/attendance")
def attendance():
    if not require_role("student"):
        return jsonify({"status": "error", "message": "Student access required."}), 401

    files = sorted([f for f in os.listdir(ATTENDANCE_DIR) if f.startswith("Attendance_") and f.endswith(".csv")], reverse=True)
    return render_template("attendance.html", files=files)


@app.route("/download_attendance/<path:filename>")
def download_attendance(filename):
    path = os.path.join(ATTENDANCE_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"status": "error", "message": "File not found."}), 404
    return send_file(path, as_attachment=True)


@app.route("/geofence")
def geofence_info():
    return jsonify({"latitude": GEOFENCE_LATITUDE, "longitude": GEOFENCE_LONGITUDE, "radius": GEOFENCE_RADIUS})


if __name__ == "__main__":
    print("\nSmart Face Attendance System\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
