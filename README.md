# Face Recognition and Geolocation Based Student Attendance System

**Objective:** a student can be marked present only if (1) the face is recognized, (2) the GPS location is within the classroom radius, (3) the 5-minute session window is open (server-side), and (4) they have not already been marked for that class/date.

## Features
Dashboard · editable weekly timetable · teacher-started 5-minute sessions · browser geolocation + Haversine check · webcam face registration & recognition · duplicate prevention (DB UNIQUE constraint) · reports with filters + CSV export · Demo Mode.

## Tech
Python, Flask, SQLite, OpenCV, face_recognition (dlib), NumPy, HTML/CSS/JS, Browser Geolocation + getUserMedia.

## Architecture (flow)
Student opens page → active session (timetable + 5-min window, checked on server) → browser GPS → server computes Haversine distance → inside radius? → webcam frame → face detection → encoding → compare with registered encodings → duplicate check → insert in `attendance`.

Files: `app.py` (routes + validation), `config.py`, `db.py`, `init_db.py` (schema + seed), `geo.py` (`calculate_distance`), `face_utils.py` (detect/encode/match), `templates/`, `static/`.

## Database
`students`, `subjects`, `timetable`, `attendance_sessions`, `attendance` (+ `settings` for classroom lat/lon/radius). `attendance` has `UNIQUE(student_id, timetable_id, date)`. Face encodings are stored as JSON (128 floats) in `students.face_encoding`; face photos in `dataset/students/`.

## Face workflow
Registration (Students page): select student → webcam → exactly one face required → encoding stored. Rejects: no face, multiple faces, bad image, already registered, face belonging to another student.
Attendance: frame sent to server → one face required → `face_distance` to all registered encodings → best match accepted if distance <= `FACE_TOLERANCE` (0.5).

## Geolocation workflow
Browser sends lat/lon → server calculates distance (Haversine, R = 6371000 m) to classroom coordinates stored in `settings` → `location_received`, `distance_calculated`, `location_verified` are separate; distance stored with each record.

## 5-minute window
Teacher clicks *Start* → `start_time = server now`, `end_time = +5 min`. Every request re-checks server time; expired sessions are auto-closed and unmarked students get an `Absent` record. JS countdown is display only.

## Timetable
Sample Mon–Fri schedule from the spec is seeded; add/edit/delete on the Timetable page.

## Install & run
```
python -m venv venv
venv\Scripts\activate        (Windows)   |   source venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
python init_db.py            # optional: app.py also creates/seeds the DB automatically
python app.py                # open http://127.0.0.1:5000
```
`face_recognition` needs dlib. Windows: install *Visual Studio Build Tools (C++)* + CMake first, or use `pip install dlib-bin` then `pip install face_recognition`. Use `localhost` (not a LAN IP) so the browser allows camera/GPS without HTTPS.

## Test procedure
1. **Students** → *Register face* for each student (webcam).
2. **Dashboard/Timetable** → *Start session* on any class.
3. **Mark Attendance** → location check runs, webcam opens → *Capture / Verify Face* → "Attendance marked successfully."
4. Verify again → "already marked" · wait 5 min or press *Stop* → "window expired" · **Reports** shows results.

## Demo mode (`config.py`)
`DEMO_MODE = True`: server uses `DEMO_LATITUDE/LONGITUDE` (~30 m from classroom), any timetable slot can be started at any time, sessions can be restarted. The Haversine check still runs and face recognition is always real.
Set `DEMO_MODE = False` to use real GPS, and set `CLASSROOM_LATITUDE/LONGITUDE` (delete `database/database.db` after changing, since values are seeded into DB) and only allow sessions during the scheduled class.

## Limitations
No login system; browser GPS can be spoofed on rooted/dev tools setups; no liveness detection (a photo could fool it); SQLite single-server.

## Future enhancements
Teacher/student login, liveness detection, IP/Wi-Fi checks, email alerts, per-classroom geofences.
