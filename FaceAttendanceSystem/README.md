# Face Recognition and Geolocation Based Student Attendance System

## Project objective
This project implements a Flask-based student attendance system in which attendance is marked only when:
- the student is physically in the classroom area,
- the attendance session is currently active,
- the student identity is verified through face recognition,
- and the student is not already marked present for the same class/date.

## Features
- Student and admin login flows
- SQLite-backed student and attendance data storage
- Timetable with weekday classes and active attendance sessions
- 5-minute server-side attendance window enforcement
- Geolocation verification using Haversine distance
- Demo mode for demonstration without physical GPS movement
- Face registration and attendance verification using face_recognition
- Dashboard, attendance records, and reports

## Technologies used
- Python 3
- Flask
- SQLite
- OpenCV
- face_recognition
- NumPy
- Pandas
- HTML/CSS/JavaScript

## System architecture
The application is a single-file Flask service using a SQLite database for persistent state. It serves a simple dashboard, student attendance page, admin interface, and reports page. Face verification is performed on captured images; geolocation is validated on the server side using the classroom coordinates and allowed radius.

## Database structure
The project uses SQLite tables:
- students
- timetable
- attendance_sessions
- attendance
- classroom_config

## Face recognition workflow
1. Admin selects a student.
2. Webcam captures a face image.
3. The image is processed using OpenCV and face_recognition.
4. A single face is required.
5. A face encoding is stored for later comparison.
6. During attendance, the live image is processed and compared to the student encoding.

## Geolocation workflow
- The browser requests the current location.
- The backend calculates the distance to the configured classroom center using the Haversine formula.
- Attendance is rejected if the student is beyond the allowed radius.
- In demo mode, predefined values are used to simulate acceptable coordinates.

## 5-minute attendance workflow
- An admin starts a class session.
- The server stores start_time and end_time.
- Attendance is accepted only while the current time is within the session window.
- Expired sessions are marked closed on the server automatically.

## Timetable implementation
The timetable is stored in SQLite and seeded with sample weekly classes for Monday to Friday. The dashboard reads the current day and shows the active course list.

## Installation
1. Open the project folder in VS Code.
2. Use the workspace virtual environment or create one.
3. Install the base project dependencies:

   pip install -r requirements.txt

4. For full face recognition on Windows, install Visual Studio C++ Build Tools and then install:

   pip install face-recognition

## Database initialization
Run:

   python database/init_db.py

This creates the SQLite database and seed data for students, timetable, and attendance records.

## How to register student faces
1. Log in as admin using code `admin123`.
2. Use the admin page to select a student and capture their face image.
3. The backend stores the encoding in the `students` table.

## How to start Flask server
From the project root:

   python app.py

Then open the browser to:

   http://localhost:5000/

## How to test attendance
1. Log in as student with code `student123`.
2. Open the dashboard and allow location access.
3. Choose a class and trigger attendance.
4. Capture the face image and confirm the geolocation and duplicate checks.

## Demo mode
Demo mode is enabled by default in the app config. It allows a demonstration workflow without requiring actual GPS movement while keeping the real geolocation calculation in place.

## Limitations
- Real face recognition requires a working camera and compatible environment.
- Browser geolocation requires device permission.
- The demo mode is intended for evaluation, not real production use.

## Future enhancements
- Teacher authentication and role-based management
- More advanced report filters and CSV export
- Real campus room mapping and multiple classrooms
- Better face recognition tuning and enrollment management
- Automatic attendance export to Excel/PDF
