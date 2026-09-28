import ast
import base64
import csv
import io
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request, session
from flask_cors import CORS

try:
    import face_recognition
except Exception:  # pragma: no cover
    face_recognition = None

app = Flask(__name__)
app.secret_key = "face_attendance_student_secure_2026"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["DEMO_MODE"] = True
app.config["CLASSROOM_LATITUDE"] = 22.97579228473351
app.config["CLASSROOM_LONGITUDE"] = 72.59593138172853
app.config["ALLOWED_RADIUS_METERS"] = 100
app.config["SESSION_DURATION_MINUTES"] = 5
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance_system.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calculate_distance(lat1, lon1, lat2, lon2):
    radius = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_classroom_config():
    conn = get_db_connection()
    row = conn.execute(
        "SELECT latitude, longitude, allowed_radius_meters, demo_mode FROM classroom_config ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {
            "latitude": app.config["CLASSROOM_LATITUDE"],
            "longitude": app.config["CLASSROOM_LONGITUDE"],
            "allowed_radius_meters": app.config["ALLOWED_RADIUS_METERS"],
        }
    return {
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "allowed_radius_meters": float(row["allowed_radius_meters"]),
        "demo_mode": bool(row["demo_mode"]),
    }


def close_expired_sessions():
    conn = get_db_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE attendance_sessions SET status = 'closed' WHERE status = 'active' AND end_time <= ?",
        (now,),
    )
    conn.commit()
    conn.close()


def require_role(role):
    return session.get("role") == role


def decode_base64_image(image_data):
    if not image_data:
        return None
    header, _, payload = image_data.partition(",")
    if not payload:
        return None
    try:
        raw = base64.b64decode(payload)
    except Exception:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return image


def serialize_student(row):
    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "name": row["name"],
        "roll_number": row["roll_number"],
        "email": row["email"],
        "course": row["course"],
        "semester": row["semester"],
    }


def parse_face_encoding(value):
    if not value:
        return None
    if isinstance(value, str) and value.startswith("data:image"):
        return value
    try:
        return np.array(ast.literal_eval(value), dtype=np.float64)
    except Exception:
        return None


def compare_histogram_similarity(image_a, image_b):
    if image_a is None or image_b is None:
        return 0.0

    gray_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2GRAY)
    try:
        hist_a = cv2.calcHist([gray_a], [0], None, [256], [0, 256])
        hist_b = cv2.calcHist([gray_b], [0], None, [256], [0, 256])
        cv2.normalize(hist_a, hist_a)
        cv2.normalize(hist_b, hist_b)
        return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))
    except Exception:
        return 0.0


def generate_face_encoding(image):
    if image is None:
        return None
    if face_recognition is None:
        raise RuntimeError("face_recognition library is not installed.")
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    faces = face_recognition.face_locations(rgb)
    if len(faces) != 1:
        raise ValueError("Please ensure that exactly one face is visible.")
    encodings = face_recognition.face_encodings(rgb, faces)
    if not encodings:
        raise ValueError("No face encoding could be generated.")
    return encodings[0]


def verify_face(image_data, student_record):
    image = decode_base64_image(image_data)
    if image is None:
        return False, "No face image was received."

    student_encoding = parse_face_encoding(student_record.get("face_encoding"))
    if student_encoding is None:
        return False, "This student has no registered face image."

    if face_recognition is None:
        if isinstance(student_encoding, str) and student_encoding.startswith("data:image"):
            stored_image = decode_base64_image(student_encoding)
            if stored_image is None:
                return False, "Stored student photo could not be decoded."
            score = compare_histogram_similarity(stored_image, image)
            if score >= 0.80:
                return True, f"Face verified using stored photo match ({score:.3f})."
            return False, f"Face not recognized. Match score {score:.3f}."
        return False, "face_recognition is not available on this server."

    try:
        if isinstance(student_encoding, str) and student_encoding.startswith("data:image"):
            stored_image = decode_base64_image(student_encoding)
            if stored_image is None:
                return False, "Stored student photo could not be decoded."
            score = compare_histogram_similarity(stored_image, image)
            if score >= 0.80:
                return True, f"Face verified using stored photo match ({score:.3f})."
            return False, f"Face not recognized. Match score {score:.3f}."

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb)
        if len(face_locations) != 1:
            return False, "Please ensure that only one person is visible."
        encodings = face_recognition.face_encodings(rgb, face_locations)
        if not encodings:
            return False, "Face could not be matched."
        distances = face_recognition.face_distance([student_encoding], encodings[0])
        if distances.size == 0:
            return False, "Face recognition failed."
        score = float(distances[0])
        if score <= 0.45:
            return True, f"Face verified (distance {score:.3f})."
        return False, f"Face not recognized. Match score {score:.3f}."
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def create_default_database():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE,
            name TEXT,
            roll_number TEXT,
            email TEXT,
            course TEXT,
            semester INTEGER,
            face_encoding TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT,
            start_time TEXT,
            end_time TEXT,
            subject_name TEXT,
            room TEXT,
            faculty TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timetable_id INTEGER,
            subject_name TEXT,
            room TEXT,
            faculty TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            student_name TEXT,
            roll_number TEXT,
            subject TEXT,
            faculty TEXT,
            class_id INTEGER,
            date TEXT,
            check_in_time TEXT,
            latitude REAL,
            longitude REAL,
            distance_from_classroom REAL,
            face_verified INTEGER,
            location_verified INTEGER,
            attendance_status TEXT,
            UNIQUE(student_id, class_id, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS classroom_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL,
            longitude REAL,
            allowed_radius_meters REAL,
            demo_mode INTEGER
        )
        """
    )

    conn.execute("DELETE FROM attendance_sessions WHERE status = 'active'")

    existing_config = conn.execute("SELECT COUNT(*) AS total FROM classroom_config").fetchone()["total"]
    if existing_config == 0:
        conn.execute(
            "INSERT INTO classroom_config (latitude, longitude, allowed_radius_meters, demo_mode) VALUES (?, ?, ?, ?)",
            (
                app.config["CLASSROOM_LATITUDE"],
                app.config["CLASSROOM_LONGITUDE"],
                app.config["ALLOWED_RADIUS_METERS"],
                int(app.config["DEMO_MODE"]),
            ),
        )
    else:
        conn.execute(
            "UPDATE classroom_config SET latitude = ?, longitude = ?, allowed_radius_meters = ?, demo_mode = ? WHERE id = (SELECT id FROM classroom_config ORDER BY id DESC LIMIT 1)",
            (
                app.config["CLASSROOM_LATITUDE"],
                app.config["CLASSROOM_LONGITUDE"],
                app.config["ALLOWED_RADIUS_METERS"],
                int(app.config["DEMO_MODE"]),
            ),
        )

    required_student_rows = [
        ("STU001", "Preet", "CSE001", "preet@example.com", "CSE", 7),
        ("STU002", "Chitransh", "CSE002", "chitransh@example.com", "CSE", 7),
        ("STU003", "Mitesh", "CSE003", "mitesh@example.com", "CSE", 7),
    ]
    existing_students = conn.execute("SELECT COUNT(*) AS total FROM students").fetchone()["total"]
    if existing_students == 0:
        conn.executemany(
            "INSERT INTO students (student_id, name, roll_number, email, course, semester) VALUES (?, ?, ?, ?, ?, ?)",
            required_student_rows,
        )
    else:
        for student_row in required_student_rows:
            conn.execute(
                "INSERT INTO students (student_id, name, roll_number, email, course, semester) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(student_id) DO UPDATE SET name=excluded.name, roll_number=excluded.roll_number, email=excluded.email, course=excluded.course, semester=excluded.semester",
                student_row,
            )

    existing_classes = conn.execute("SELECT COUNT(*) AS total FROM timetable").fetchone()["total"]
    if existing_classes == 0:
        timetable_rows = [
            ("Monday", "09:00", "10:00", "Machine Learning", "A101", "Dr. Mehta"),
            ("Monday", "10:00", "11:00", "Database Management System", "A101", "Prof. Shah"),
            ("Monday", "11:00", "12:00", "Computer Networks", "A101", "Prof. Patel"),
            ("Tuesday", "09:00", "10:00", "Artificial Intelligence", "A101", "Dr. Mehta"),
            ("Tuesday", "10:00", "11:00", "Web Development", "A101", "Prof. Shah"),
            ("Tuesday", "11:00", "12:00", "Machine Learning", "A101", "Dr. Mehta"),
            ("Wednesday", "09:00", "10:00", "Database Management System", "A101", "Prof. Patel"),
            ("Wednesday", "10:00", "11:00", "Artificial Intelligence", "A101", "Dr. Mehta"),
            ("Wednesday", "11:00", "12:00", "Computer Networks", "A101", "Prof. Patel"),
            ("Thursday", "09:00", "10:00", "Machine Learning", "A101", "Dr. Mehta"),
            ("Thursday", "10:00", "11:00", "Web Development", "A101", "Prof. Shah"),
            ("Thursday", "11:00", "12:00", "Database Management System", "A101", "Prof. Patel"),
            ("Friday", "09:00", "10:00", "Artificial Intelligence", "A101", "Dr. Mehta"),
            ("Friday", "10:00", "11:00", "Machine Learning", "A101", "Dr. Mehta"),
            ("Friday", "11:00", "12:00", "Web Development", "A101", "Prof. Shah"),
        ]
        conn.executemany(
            "INSERT INTO timetable (day, start_time, end_time, subject_name, room, faculty) VALUES (?, ?, ?, ?, ?, ?)",
            timetable_rows,
        )

    existing_attendance = conn.execute("SELECT COUNT(*) AS total FROM attendance").fetchone()["total"]
    if existing_attendance == 0:
        today = datetime.now()
        for offset in range(3):
            record_day = today - timedelta(days=offset)
            date_str = record_day.strftime("%Y-%m-%d")
            class_row = conn.execute(
                "SELECT id, subject_name, faculty FROM timetable WHERE day = ? ORDER BY start_time LIMIT 1",
                (record_day.strftime("%A"),),
            ).fetchone()
            if not class_row:
                continue
            students = conn.execute("SELECT id, student_id, name, roll_number FROM students ORDER BY id").fetchall()
            for idx, student in enumerate(students[:3]):
                conn.execute(
                    "INSERT INTO attendance (student_id, student_name, roll_number, subject, faculty, class_id, date, check_in_time, latitude, longitude, distance_from_classroom, face_verified, location_verified, attendance_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        student["id"],
                        student["name"],
                        student["roll_number"],
                        class_row["subject_name"],
                        class_row["faculty"],
                        class_row["id"],
                        date_str,
                        (datetime.combine(record_day.date(), datetime.strptime(class_row["subject_name"] and "09:00", "%H:%M").time()) + timedelta(minutes=idx * 3)).strftime("%H:%M:%S"),
                        23.0225,
                        72.5714,
                        25.0 + idx * 10,
                        1,
                        1,
                        "Present",
                    ),
                )
            if len(students) > 3:
                absent_student = students[3]
                conn.execute(
                    "INSERT INTO attendance (student_id, student_name, roll_number, subject, faculty, class_id, date, check_in_time, latitude, longitude, distance_from_classroom, face_verified, location_verified, attendance_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        absent_student["id"],
                        absent_student["name"],
                        absent_student["roll_number"],
                        class_row["subject_name"],
                        class_row["faculty"],
                        class_row["id"],
                        date_str,
                        "--:--:--",
                        None,
                        None,
                        None,
                        0,
                        0,
                        "Absent",
                    ),
                )

    conn.commit()
    conn.close()


def load_courses_from_csv():
    csv_path = BASE_DIR / "Courses.csv"
    if not csv_path.exists():
        return []

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            courses = []
            for row in reader:
                name = (row.get("Course Name") or "").strip()
                code = (row.get("Course Code") or "").strip()
                if name or code:
                    courses.append({"Course Name": name, "Course Code": code})
            return courses
    except Exception:
        return []


def get_students():
    conn = get_db_connection()
    students = conn.execute("SELECT * FROM students ORDER BY name").fetchall()
    conn.close()
    return [serialize_student(student) for student in students]


def get_timetable_for_day(day_name):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM timetable WHERE day = ? ORDER BY start_time",
        (day_name,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "day": row["day"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "subject_name": row["subject_name"],
            "room": row["room"],
            "faculty": row["faculty"],
        }
        for row in rows
    ]


def list_session_status(class_id):
    conn = get_db_connection()
    session_row = conn.execute(
        "SELECT * FROM attendance_sessions WHERE timetable_id = ? AND status = 'active' ORDER BY start_time DESC LIMIT 1",
        (class_id,),
    ).fetchone()
    conn.close()
    if not session_row:
        return None
    return {
        "id": session_row["id"],
        "timetable_id": session_row["timetable_id"],
        "subject_name": session_row["subject_name"],
        "room": session_row["room"],
        "faculty": session_row["faculty"],
        "start_time": session_row["start_time"],
        "end_time": session_row["end_time"],
        "status": session_row["status"],
    }


def get_active_session_for_class(class_id):
    close_expired_sessions()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM attendance_sessions WHERE timetable_id = ? AND status = 'active' ORDER BY start_time DESC LIMIT 1",
        (class_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    end_time = datetime.strptime(row["end_time"], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > end_time:
        conn = get_db_connection()
        conn.execute("UPDATE attendance_sessions SET status = 'closed' WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return None
    return row


def get_student_dashboard_data(student_id):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    rows = conn.execute(
        "SELECT * FROM attendance WHERE student_id = ? ORDER BY date DESC, check_in_time DESC LIMIT 10",
        (student_id,),
    ).fetchall()
    conn.close()
    if student is None:
        return None
    return {
        "student": serialize_student(student),
        "records": [dict(r) for r in rows],
    }


def get_dashboard_summary():
    conn = get_db_connection()
    total_students = conn.execute("SELECT COUNT(*) AS total FROM students").fetchone()["total"]
    present_today = conn.execute(
        "SELECT COUNT(*) AS total FROM attendance WHERE date = ? AND attendance_status = 'Present'",
        (datetime.now().strftime("%Y-%m-%d"),),
    ).fetchone()["total"]
    total_sessions = conn.execute("SELECT COUNT(*) AS total FROM attendance_sessions WHERE date(created_at) = date('now')").fetchone()["total"]
    active_sessions = conn.execute("SELECT COUNT(*) AS total FROM attendance_sessions WHERE status = 'active'").fetchone()["total"]
    conn.close()
    percentage = 0 if total_students == 0 else round((present_today / total_students) * 100, 2)
    return {
        "students": total_students,
        "present_today": present_today,
        "active_sessions": active_sessions,
        "sessions": total_sessions,
        "percentage": percentage,
    }


@app.before_request
def enforce_session_cleanup():
    close_expired_sessions()


@app.route("/")
def home():
    today_name = datetime.now().strftime("%A")
    day_schedule = get_timetable_for_day(today_name)
    dashboard = get_dashboard_summary()
    return render_template(
        "index.html",
        students=get_students(),
        timetable=day_schedule,
        classroom=get_classroom_config(),
        summary=dashboard,
        demo_mode=app.config["DEMO_MODE"],
        current_day=today_name,
        courses=load_courses_from_csv(),
    )


@app.route("/attendance")
def attendance_page():
    students = get_students()
    student_id = request.args.get("student_id")
    if not student_id and students:
        student_id = str(students[0]["id"])
    student_records = []
    if student_id:
        data = get_student_dashboard_data(student_id)
        if data:
            student_records = data["records"]
    return render_template("attendance.html", student_records=student_records, students=students, selected_student_id=student_id)


@app.route("/admin")
def admin_page():
    return render_template("admin.html", timetable=get_timetable_for_day(datetime.now().strftime("%A")), students=get_students())


@app.route("/reports")
def reports_page():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT student_id, student_name, roll_number, subject, faculty, date, attendance_status FROM attendance ORDER BY date DESC, student_name"
    ).fetchall()
    conn.close()
    return render_template("reports.html", records=[dict(r) for r in rows])


@app.route("/api/login", methods=["POST"])
@app.route("/student_login", methods=["POST"])
def api_login():
    role = request.form.get("role", "student").strip().lower()
    code = request.form.get("access_code", "").strip()

    if role == "student" and code == "student123":
        session["role"] = "student"
        return jsonify({"status": "success", "message": "Student login successful."})
    if role == "admin" and code == "admin123":
        session["role"] = "admin"
        return jsonify({"status": "success", "message": "Administrator login successful."})

    if not request.form.get("role") and code == "student123":
        session["role"] = "student"
        return jsonify({"status": "success", "message": "Student login successful."})
    if not request.form.get("role") and code == "admin123":
        session["role"] = "admin"
        return jsonify({"status": "success", "message": "Administrator login successful."})

    return jsonify({"status": "error", "message": "Invalid access code."})


@app.route("/api/logout", methods=["POST"])
@app.route("/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully."})


@app.route("/start", methods=["POST"])
def start_student_session():
    if not require_role("student"):
        return jsonify({"status": "error", "message": "Student access required."}), 401

    course = request.form.get("course", "").strip()
    latitude = request.form.get("latitude")
    longitude = request.form.get("longitude")

    if not course:
        return jsonify({"status": "error", "message": "Please select a course."})
    if latitude is None or longitude is None:
        return jsonify({"status": "error", "message": "Location permission is required."})

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid location values received."})

    config = get_classroom_config()
    if app.config.get("DEMO_MODE") or config.get("demo_mode"):
        distance = 0.0
    else:
        distance = calculate_distance(latitude, longitude, config["latitude"], config["longitude"])
        if distance > config["allowed_radius_meters"]:
            return jsonify({"status": "error", "message": f"Attendance denied. You are {distance:.1f} meters away. Allowed radius: {config['allowed_radius_meters']}m."})

    session["attendance_active"] = True
    session["selected_course"] = course
    return jsonify({"status": "success", "message": f"Location verified. Attendance started for {course}.", "distance": round(distance, 2)})


@app.route("/stop", methods=["POST"])
def stop_student_session():
    if not require_role("student"):
        return jsonify({"status": "error", "message": "Student access required."}), 401

    session["attendance_active"] = False
    session.pop("selected_course", None)
    return jsonify({"status": "success", "message": "Attendance stopped."})


@app.route("/api/student_list")
def api_student_list():
    return jsonify({"students": get_students()})


@app.route("/api/timetable")
def api_timetable():
    day_name = request.args.get("day", datetime.now().strftime("%A"))
    rows = get_timetable_for_day(day_name)
    sessions = []
    for item in rows:
        session_row = list_session_status(item["id"])
        item["session_status"] = "ACTIVE" if session_row else "CLOSED"
        item["session"] = session_row
        sessions.append(item)
    return jsonify({"day": day_name, "classes": sessions})


@app.route("/api/start_session", methods=["POST"])
def api_start_session():
    if not require_role("admin"):
        return jsonify({"status": "error", "message": "Admin access required."}), 401

    timetable_id = request.form.get("timetable_id")
    if not timetable_id:
        return jsonify({"status": "error", "message": "A class must be selected."})

    conn = get_db_connection()
    timetable_row = conn.execute("SELECT * FROM timetable WHERE id = ?", (timetable_id,)).fetchone()
    if timetable_row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Selected class was not found."})

    active = conn.execute(
        "SELECT * FROM attendance_sessions WHERE timetable_id = ? AND status = 'active' ORDER BY start_time DESC LIMIT 1",
        (timetable_id,),
    ).fetchone()
    if active is not None:
        conn.close()
        return jsonify({"status": "error", "message": "An attendance session is already active for this class."})

    now = datetime.now()
    start_time = now.strftime("%Y-%m-%d %H:%M:%S")
    end_time = (now + timedelta(minutes=app.config["SESSION_DURATION_MINUTES"])).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        "INSERT INTO attendance_sessions (timetable_id, subject_name, room, faculty, start_time, end_time, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
        (
            timetable_row["id"],
            timetable_row["subject_name"],
            timetable_row["room"],
            timetable_row["faculty"],
            start_time,
            end_time,
            now.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Attendance session started."})


@app.route("/api/stop_session", methods=["POST"])
def api_stop_session():
    if not require_role("admin"):
        return jsonify({"status": "error", "message": "Admin access required."}), 401

    timetable_id = request.form.get("timetable_id")
    if not timetable_id:
        return jsonify({"status": "error", "message": "A class must be selected."})
    conn = get_db_connection()
    conn.execute(
        "UPDATE attendance_sessions SET status = 'closed' WHERE timetable_id = ? AND status = 'active'",
        (timetable_id,),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Attendance session closed."})


@app.route("/api/current_class")
def api_current_class():
    day_name = datetime.now().strftime("%A")
    classes = get_timetable_for_day(day_name)
    if not classes:
        return jsonify({"status": "error", "message": "No timetable entries found for today."})
    now = datetime.now().strftime("%H:%M")
    current = None
    for item in classes:
        start = datetime.strptime(item["start_time"], "%H:%M")
        end = datetime.strptime(item["end_time"], "%H:%M")
        current_time = datetime.strptime(now, "%H:%M")
        if start <= current_time <= end:
            current = item
            break
    if current is None:
        return jsonify({"status": "info", "message": "No class is active right now."})
    sessionRow = get_active_session_for_class(current["id"])
    remaining = None
    if sessionRow is not None:
        end_time = datetime.strptime(sessionRow["end_time"], "%Y-%m-%d %H:%M:%S")
        remaining = max(0, int((end_time - datetime.now()).total_seconds()))
    return jsonify({"status": "success", "class": current, "active_session": sessionRow, "time_remaining_seconds": remaining})


@app.route("/api/report")
def api_report():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM attendance ORDER BY date DESC, student_name"
    ).fetchall()
    conn.close()
    return jsonify({"records": [dict(r) for r in rows]})


@app.route("/api/export_student_attendance_csv")
def api_export_student_attendance_csv():
    student_id = request.args.get("student_id")
    if not student_id:
        return jsonify({"status": "error", "message": "Student ID is required."}), 400

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT student_name, roll_number, subject, faculty, date, check_in_time, attendance_status FROM attendance WHERE student_id = ? ORDER BY date DESC, check_in_time DESC",
        (student_id,),
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name", "Roll Number", "Subject", "Faculty", "Date", "Check-in Time", "Status"])
    for row in rows:
        writer.writerow([
            row["student_name"],
            row["roll_number"],
            row["subject"],
            row["faculty"],
            row["date"],
            row["check_in_time"],
            row["attendance_status"],
        ])

    csv_data = output.getvalue()
    response = Response(csv_data, mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=student_attendance_report.csv"
    return response


@app.route("/api/create_student", methods=["POST"])
def api_create_student():
    if not require_role("admin"):
        return jsonify({"status": "error", "message": "Admin access required."}), 401

    name = (request.form.get("name") or "").strip()
    roll_number = (request.form.get("roll_number") or "").strip()
    email = (request.form.get("email") or "").strip()
    course = (request.form.get("course") or "CSE").strip()
    semester = request.form.get("semester", "7").strip()
    image_data = request.form.get("image_data")

    if not name or not roll_number:
        return jsonify({"status": "error", "message": "Student name and roll number are required."})

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM students WHERE roll_number = ? OR LOWER(name) = LOWER(?)", (roll_number, name)).fetchone()
    if existing:
        conn.close()
        return jsonify({"status": "error", "message": "A student with this name or roll number already exists."})

    student_id = f"STU{(conn.execute('SELECT COUNT(*) FROM students').fetchone()[0] + 1):03d}"
    try:
        semester_number = int(semester)
    except ValueError:
        conn.close()
        return jsonify({"status": "error", "message": "Semester must be a number."})

    encoding_value = None
    if image_data:
        image = decode_base64_image(image_data)
        if image is None:
            conn.close()
            return jsonify({"status": "error", "message": "Invalid image data received."})
        try:
            if face_recognition is not None:
                encoding = generate_face_encoding(image)
                encoding_value = str(list(map(float, encoding.tolist())))
            else:
                encoding_value = image_data
        except ValueError as exc:
            conn.close()
            return jsonify({"status": "error", "message": str(exc)})
        except RuntimeError as exc:
            conn.close()
            return jsonify({"status": "error", "message": str(exc)})

    conn.execute(
        "INSERT INTO students (student_id, name, roll_number, email, course, semester, face_encoding) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (student_id, name, roll_number, email or f"{roll_number.lower()}@example.com", course, semester_number, encoding_value),
    )
    conn.commit()
    student = conn.execute("SELECT * FROM students WHERE roll_number = ?", (roll_number,)).fetchone()
    conn.close()
    return jsonify({
        "status": "success",
        "message": f"Student {name} registered successfully.",
        "student_id": student["id"],
        "student_name": student["name"],
    })


@app.route("/api/register_face", methods=["POST"])
def api_register_face():
    if not require_role("admin") and not require_role("student"):
        return jsonify({"status": "error", "message": "Admin or student access required."}), 401

    student_id = request.form.get("student_id")
    image_data = request.form.get("image_data")
    if not student_id or not image_data:
        return jsonify({"status": "error", "message": "Student and a captured face image are required."})

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        conn.close()
        return jsonify({"status": "error", "message": "Student record not found."})

    image = decode_base64_image(image_data)
    if image is None:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid image data received."})
    try:
        if face_recognition is not None:
            encoding = generate_face_encoding(image)
            encoding_string = str(list(map(float, encoding.tolist())))
        else:
            encoding_string = image_data
        conn.execute(
            "UPDATE students SET face_encoding = ? WHERE id = ?",
            (encoding_string, student_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"Face registered for {student['name']}"})
    except ValueError as exc:
        conn.close()
        return jsonify({"status": "error", "message": str(exc)})
    except RuntimeError as exc:
        conn.close()
        return jsonify({"status": "error", "message": str(exc)})


@app.route("/api/mark_attendance", methods=["POST"])
def api_mark_attendance():
    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id")
    class_id = payload.get("class_id")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    image_data = payload.get("image_data")

    if not student_id:
        return jsonify({"status": "error", "message": "Student details are required."})

    if not class_id:
        day_classes = get_timetable_for_day(datetime.now().strftime("%A"))
        if not day_classes:
            return jsonify({"status": "error", "message": "No timetable is available for today."})
        class_id = day_classes[0]["id"]

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    class_row = conn.execute("SELECT * FROM timetable WHERE id = ?", (class_id,)).fetchone()
    if student is None or class_row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid student or class selection."})

    session_row = get_active_session_for_class(class_id)
    if session_row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Attendance window has expired or no session is active."})

    if not latitude or not longitude:
        conn.close()
        return jsonify({"status": "error", "message": "Location permission is required to verify attendance."})
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"status": "error", "message": "Invalid geolocation values received."})

    config = get_classroom_config()
    if app.config["DEMO_MODE"] or config.get("demo_mode"):
        latitude = float(config["latitude"])
        longitude = float(config["longitude"])
        distance = 0.0
        location_verified = True
    else:
        latitude = float(payload.get("latitude") or config["latitude"])
        longitude = float(payload.get("longitude") or config["longitude"])
        distance = calculate_distance(latitude, longitude, config["latitude"], config["longitude"])
        location_verified = distance <= config["allowed_radius_meters"]
        if not location_verified:
            conn.close()
            return jsonify({"status": "error", "message": f"You are {distance:.1f} meters away from the classroom. Attendance rejected."})

    if not image_data:
        conn.close()
        return jsonify({"status": "error", "message": "A face photo is required for validation."})

    face_verified, face_message = verify_face(image_data, dict(student))
    if not face_verified:
        conn.close()
        return jsonify({"status": "error", "message": face_message})

    duplicate = conn.execute(
        "SELECT 1 FROM attendance WHERE student_id = ? AND class_id = ? AND date = ?",
        (student["id"], class_id, datetime.now().strftime("%Y-%m-%d")),
    ).fetchone()
    if duplicate:
        conn.close()
        return jsonify({"status": "error", "message": "This student has already been marked present for this class."})

    now = datetime.now().strftime("%H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO attendance (student_id, student_name, roll_number, subject, faculty, class_id, date, check_in_time, latitude, longitude, distance_from_classroom, face_verified, location_verified, attendance_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Present')",
        (
            student["id"],
            student["name"],
            student["roll_number"],
            class_row["subject_name"],
            class_row["faculty"],
            class_id,
            today,
            now,
            latitude,
            longitude,
            round(distance, 2),
            1,
            1,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({
        "status": "success",
        "message": "Attendance marked successfully.",
        "distance": round(distance, 2),
        "class": class_row["subject_name"],
        "face_message": face_message,
    })


@app.route("/api/attendance_summary")
def api_attendance_summary():
    conn = get_db_connection()
    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND attendance_status = 'Present'", (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    absent = max(total_students - present, 0)
    percentage = round((present / total_students * 100), 2) if total_students else 0
    conn.close()
    return jsonify({"total_students": total_students, "present": present, "absent": absent, "percentage": percentage})


create_default_database()

if __name__ == "__main__":
    print("Starting Face Recognition Attendance System")
    app.run(host="0.0.0.0", port=5000, debug=True)
