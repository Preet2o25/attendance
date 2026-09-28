import csv, io, json, os, re, sqlite3
from datetime import datetime, timedelta
import cv2
import numpy as np
from flask import Flask, jsonify, request, render_template, Response, session, redirect, url_for

import config, init_db
from db import get_db, close_db, get_setting
from geo import calculate_distance
import face_utils
from face_utils import FaceError

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "face_geo_attendance_secret_2026")
app.teardown_appcontext(close_db)

FMT = "%Y-%m-%d %H:%M:%S"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SESSION_SQL = """SELECT s.id, s.timetable_id, s.date, s.start_time, s.end_time, s.status,
  t.day, t.start_time AS slot_start, t.end_time AS slot_end, sub.subject_name AS subject, t.faculty, t.room
  FROM attendance_sessions s JOIN timetable t ON t.id=s.timetable_id JOIN subjects sub ON sub.id=t.subject_id """


def err(msg, status=400, **extra):
    return jsonify(success=False, message=msg, **extra), status


EXEMPT_ENDPOINTS = {"login_page", "api_login", "static"}

@app.before_request
def require_login():
    if request.endpoint in EXEMPT_ENDPOINTS or (request.endpoint and request.endpoint.startswith("static")):
        return
    user = session.get("user")
    if not user:
        if request.path.startswith("/api/"):
            return err("Unauthorized. Please log in.", 401)
        return redirect("/login")
    
    # Role-based restriction: students cannot access faculty-only management pages/APIs
    faculty_only_paths = ["/attendance", "/students", "/reports"]
    faculty_only_api_prefixes = ["/api/timetable", "/api/students", "/api/sessions/start", "/api/sessions/stop"]
    
    if user.get("role") == "student":
        if any(request.path == p or request.path.startswith(p + "/") for p in faculty_only_paths):
            return redirect("/")
        if any(request.path.startswith(p) for p in faculty_only_api_prefixes):
            return err("Access denied. Faculty permission required.", 403)


# ------------------------------------------------------------ session helpers
def finalize_session(db, sess_id):
    """Close a session and mark every student without a record as Absent."""
    s = db.execute(SESSION_SQL + "WHERE s.id=?", (sess_id,)).fetchone()
    db.execute("UPDATE attendance_sessions SET status='CLOSED' WHERE id=?", (sess_id,))
    for st in db.execute("SELECT id FROM students").fetchall():
        db.execute("""INSERT OR IGNORE INTO attendance(student_id,session_id,timetable_id,subject,faculty,date,status)
                   VALUES(?,?,?,?,?,?,'Absent')""", (st["id"], sess_id, s["timetable_id"], s["subject"], s["faculty"], s["date"]))
    db.commit()


def close_expired(db):
    """Server-side enforcement: any ACTIVE session past its end time is closed."""
    for r in db.execute("SELECT id FROM attendance_sessions WHERE status='ACTIVE' AND end_time < ?",
                        (datetime.now().strftime(FMT),)).fetchall():
        finalize_session(db, r["id"])


def session_dict(r):
    d = dict(r)
    remaining = (datetime.strptime(r["end_time"], FMT) - datetime.now()).total_seconds()
    d["remaining_seconds"] = max(0, int(remaining)) if r["status"] == "ACTIVE" else 0
    return d


def active_sessions(db):
    close_expired(db)
    return [session_dict(r) for r in db.execute(SESSION_SQL + "WHERE s.status='ACTIVE' ORDER BY s.start_time")]


# ------------------------------------------------------------ authentication
@app.route("/login", methods=["GET"])
def login_page():
    if session.get("user"):
        return redirect("/attendance" if session["user"].get("role") == "student" else "/")
    return render_template("login.html")


@app.post("/api/login")
def api_login():
    d = request.get_json(silent=True) or {}
    role = str(d.get("role", "")).strip().lower()
    username = str(d.get("username", "")).strip()
    password = str(d.get("password", "")).strip()

    if not role or not username or not password:
        return err("Role, username/ID, and password are required.")

    db = get_db()
    if role == "student":
        st = db.execute(
            """SELECT * FROM students WHERE
               LOWER(student_id)=LOWER(?) OR LOWER(roll_number)=LOWER(?)
               OR LOWER(email)=LOWER(?) OR LOWER(name)=LOWER(?)""",
            (username, username, username, username)
        ).fetchone()

        if not st:
            return err("Student account not found.", 404)

        first_name = st["name"].strip().split()[0].lower()
        expected_pwd = st["password"] or f"{first_name}@2026"
        if password.lower() != expected_pwd.lower():
            return err("Invalid password.", 401)

        session["user"] = {
            "id": st["id"],
            "code": st["student_id"],
            "name": st["name"],
            "roll": st["roll_number"],
            "role": "student"
        }
        return jsonify(success=True, message=f"Welcome, {st['name']}!", redirect="/")

    elif role == "faculty":
        fac = db.execute(
            """SELECT * FROM faculty WHERE
               LOWER(faculty_id)=LOWER(?) OR LOWER(email)=LOWER(?) OR LOWER(name)=LOWER(?)""",
            (username, username, username)
        ).fetchone()

        if not fac:
            return err("Faculty account not found.", 404)

        first_name = fac["name"].strip().split()[-1].lower()
        expected_pwd = fac["password"] or f"{first_name}@2026"
        if password.lower() != expected_pwd.lower():
            return err("Invalid password.", 401)

        session["user"] = {
            "id": fac["id"],
            "code": fac["faculty_id"],
            "name": fac["name"],
            "role": "faculty"
        }
        return jsonify(success=True, message=f"Welcome, {fac['name']}!", redirect="/")

    else:
        return err("Invalid login role specified.")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ------------------------------------------------------------ pages
@app.route("/")
def dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    day = datetime.now().strftime("%A")
    user = session.get("user")

    if user and user.get("role") == "student":
        student_id = user["id"]
        student = db.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()

        # Today's timetable with active session & attendance status for this student
        tt_rows = db.execute("""SELECT t.*, sub.subject_name AS subject FROM timetable t
                                JOIN subjects sub ON sub.id=t.subject_id
                                WHERE day=? ORDER BY start_time""", (day,)).fetchall()

        active_sess = active_sessions(db)
        active_tt_ids = {s["timetable_id"]: s for s in active_sess}

        attended_tt_ids = set()
        for r in db.execute("SELECT timetable_id FROM attendance WHERE student_id=? AND date=? AND status='Present'",
                            (student_id, today)).fetchall():
            attended_tt_ids.add(r["timetable_id"])

        today_timetable = []
        for t in tt_rows:
            d = dict(t)
            tid = t["id"]
            if tid in attended_tt_ids:
                d["status_label"] = "Present"
                d["status_class"] = "ok"
                d["can_mark"] = False
            elif tid in active_tt_ids:
                d["status_label"] = "Session Active"
                d["status_class"] = "wait"
                d["can_mark"] = True
                d["session_id"] = active_tt_ids[tid]["id"]
            else:
                d["status_label"] = "Scheduled"
                d["status_class"] = "wait"
                d["can_mark"] = False
            today_timetable.append(d)

        # Personal attendance stats
        total_sessions = db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=?", (student_id,)).fetchone()[0]
        present_count = db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Present'", (student_id,)).fetchone()[0]
        absent_count = total_sessions - present_count
        pct = round(100 * present_count / total_sessions, 1) if total_sessions else 0

        # Subject-wise attendance summary
        sub_stats = db.execute("""
            SELECT subject,
                   COUNT(*) as total,
                   SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as present,
                   SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) as absent
            FROM attendance
            WHERE student_id=?
            GROUP BY subject
            ORDER BY subject
        """, (student_id,)).fetchall()

        subject_summary = []
        for s in sub_stats:
            spct = round(100 * s["present"] / s["total"], 1) if s["total"] else 0
            subject_summary.append({
                "subject": s["subject"],
                "total": s["total"],
                "present": s["present"],
                "absent": s["absent"],
                "pct": spct
            })

        # Calendar map: { 'YYYY-MM-DD': [ {subject, faculty, status, time, distance}, ... ] }
        att_records = db.execute("""
            SELECT date, subject, faculty, status, check_in_time, distance
            FROM attendance
            WHERE student_id=?
            ORDER BY date DESC, check_in_time DESC
        """, (student_id,)).fetchall()

        calendar_map = {}
        for r in att_records:
            d = r["date"]
            if d not in calendar_map:
                calendar_map[d] = []
            calendar_map[d].append({
                "subject": r["subject"],
                "faculty": r["faculty"],
                "status": r["status"],
                "time": r["check_in_time"] or "-",
                "distance": f"{round(r['distance'], 0)} m" if r["distance"] is not None else "-"
            })

        return render_template("dashboard_student.html",
                               day=day, today=today, student=student,
                               today_timetable=today_timetable,
                               total_sessions=total_sessions, present_count=present_count,
                               absent_count=absent_count, pct=pct,
                               subject_summary=subject_summary,
                               calendar_map=calendar_map,
                               recent_records=att_records[:10])

    # Faculty Dashboard (Admin View) - Filtered to assigned subjects for privacy
    faculty_name = user["name"]
    sessions = [s for s in active_sessions(db) if s["faculty"] == faculty_name]
    timetable = db.execute("""SELECT t.*, sub.subject_name AS subject FROM timetable t JOIN subjects sub ON sub.id=t.subject_id
                              WHERE day=? AND t.faculty=? ORDER BY start_time""", (day, faculty_name)).fetchall()
    total_students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    present_today = db.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date=? AND status='Present' AND faculty=?", (today, faculty_name)).fetchone()[0]
    overall = db.execute("SELECT SUM(status='Present'), COUNT(*) FROM attendance WHERE faculty=?", (faculty_name,)).fetchone()
    pct = round(100 * (overall[0] or 0) / overall[1], 1) if (overall and overall[1]) else 0
    recent = db.execute("""SELECT a.*, st.name, st.roll_number FROM attendance a JOIN students st ON st.id=a.student_id
                           WHERE a.faculty=? ORDER BY a.date DESC, a.id DESC LIMIT 10""", (faculty_name,)).fetchall()
    return render_template("dashboard.html", day=day, today=today, timetable=timetable, sessions=sessions,
                           total_students=total_students, present_today=present_today,
                           absent_today=total_students - present_today, pct=pct, recent=recent)


@app.route("/attendance")
def attendance_page():
    return render_template("attendance.html")


@app.route("/timetable")
def timetable_page():
    db = get_db()
    user = session.get("user")
    if user and user.get("role") == "faculty":
        rows = db.execute("""SELECT t.*, sub.subject_name AS subject FROM timetable t JOIN subjects sub ON sub.id=t.subject_id WHERE t.faculty=?""", (user["name"],)).fetchall()
    else:
        rows = db.execute("""SELECT t.*, sub.subject_name AS subject FROM timetable t JOIN subjects sub ON sub.id=t.subject_id""").fetchall()
    rows = sorted(rows, key=lambda r: (DAYS.index(r["day"]), r["start_time"]))
    return render_template("timetable.html", rows=rows, days=DAYS)


@app.route("/students")
def students_page():
    rows = get_db().execute("SELECT * FROM students ORDER BY roll_number").fetchall()
    return render_template("students.html", students=rows)


@app.route("/reports")
def reports_page():
    db = get_db()
    close_expired(db)
    user = session.get("user")
    f = {k: request.args.get(k, "").strip() for k in ("student", "subject", "date", "faculty")}
    
    # Privacy Policy: Faculty members can ONLY view attendance reports for their own subjects
    if user and user.get("role") == "faculty":
        f["faculty"] = user["name"]
        
    where, params = ["s.status='CLOSED'"], []
    if f["subject"]: where.append("sub.subject_name=?"); params.append(f["subject"])
    if f["date"]: where.append("s.date=?"); params.append(f["date"])
    if f["faculty"]: where.append("t.faculty=?"); params.append(f["faculty"])
    W = " AND ".join(where)
    JOIN = " JOIN timetable t ON t.id=s.timetable_id JOIN subjects sub ON sub.id=t.subject_id "
    total = db.execute("SELECT COUNT(*) FROM attendance_sessions s" + JOIN + "WHERE " + W, params).fetchone()[0]
    present = {r[0]: r[1] for r in db.execute(
        "SELECT a.student_id, COUNT(*) FROM attendance a JOIN attendance_sessions s ON s.id=a.session_id" + JOIN +
        "WHERE a.status='Present' AND " + W + " GROUP BY a.student_id", params)}
    students = db.execute("SELECT * FROM students ORDER BY roll_number").fetchall()
    summary = []
    for st in students:
        if f["student"] and str(st["id"]) != f["student"]:
            continue
        p = present.get(st["id"], 0)
        summary.append(dict(name=st["name"], roll=st["roll_number"], total=total, present=p, absent=total - p,
                            pct=round(100 * p / total, 1) if total else 0))
    rec_where, rec_params = W, list(params)
    if f["student"]: rec_where += " AND a.student_id=?"; rec_params.append(f["student"])
    records = db.execute("""SELECT a.*, st.name, st.roll_number FROM attendance a JOIN students st ON st.id=a.student_id
        JOIN attendance_sessions s ON s.id=a.session_id""" + JOIN + "WHERE " + rec_where +
        " ORDER BY a.date DESC, a.check_in_time DESC LIMIT 300", rec_params).fetchall()
    if request.args.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Student", "Roll", "Total", "Present", "Absent", "Attendance %"])
        for r in summary: w.writerow([r["name"], r["roll"], r["total"], r["present"], r["absent"], r["pct"]])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})
        
    if user and user.get("role") == "faculty":
        subjects = [r[0] for r in db.execute("SELECT DISTINCT sub.subject_name FROM timetable t JOIN subjects sub ON sub.id=t.subject_id WHERE t.faculty=? ORDER BY 1", (user["name"],))]
        faculties = [user["name"]]
    else:
        subjects = [r[0] for r in db.execute("SELECT subject_name FROM subjects ORDER BY 1")]
        faculties = [r[0] for r in db.execute("SELECT DISTINCT faculty FROM subjects ORDER BY 1")]
    return render_template("reports.html", summary=summary, records=records, f=f, students=students,
                           subjects=subjects, faculties=faculties)


# ------------------------------------------------------------ config / sessions API
@app.get("/api/config")
def api_config():
    db = get_db()
    return jsonify(demo_mode=config.DEMO_MODE, radius=get_setting(db, "radius"), window_minutes=config.WINDOW_MINUTES)


@app.get("/api/sessions/active")
def api_active():
    return jsonify(sessions=active_sessions(get_db()))


@app.post("/api/sessions/start")
def api_start():
    db = get_db()
    close_expired(db)
    user = session.get("user")
    tid = (request.get_json(silent=True) or {}).get("timetable_id")
    t = db.execute("SELECT * FROM timetable WHERE id=?", (tid,)).fetchone()
    if not t:
        return err("Invalid timetable entry.", 404)
        
    # Privacy enforcement: Faculty can only start attendance sessions for their own subjects
    if user and user.get("role") == "faculty" and t["faculty"] != user["name"]:
        return err(f"Privacy Policy: You can only start attendance sessions for your own assigned subjects ({t['faculty']} is assigned to this slot).", 403)

    now = datetime.now()
    if not config.DEMO_MODE:  # real mode: class must be running now
        if t["day"] != now.strftime("%A") or not (t["start_time"] <= now.strftime("%H:%M") < t["end_time"]):
            return err("This class is not scheduled right now.")
    today = now.strftime("%Y-%m-%d")
    existing = db.execute("SELECT id, status FROM attendance_sessions WHERE timetable_id=? AND date=?", (tid, today)).fetchone()
    if existing:
        if not config.DEMO_MODE:
            return err("An attendance session for this class was already held today.")
        db.execute("DELETE FROM attendance_sessions WHERE timetable_id=? AND date=?", (tid, today))  # demo: allow restart
    end = now + timedelta(minutes=config.WINDOW_MINUTES)
    db.execute("INSERT INTO attendance_sessions(timetable_id,date,start_time,end_time,status) VALUES(?,?,?,?,'ACTIVE')",
               (tid, today, now.strftime(FMT), end.strftime(FMT)))
    db.commit()
    return jsonify(success=True, message=f"Attendance session started. Closes in {config.WINDOW_MINUTES} minutes.")


@app.post("/api/sessions/<int:sid>/stop")
def api_stop(sid):
    db = get_db()
    user = session.get("user")
    s = db.execute("""SELECT s.status, t.faculty FROM attendance_sessions s
                      JOIN timetable t ON t.id=s.timetable_id WHERE s.id=?""", (sid,)).fetchone()
    if not s:
        return err("Session not found.", 404)
    if user and user.get("role") == "faculty" and s["faculty"] != user["name"]:
        return err("Privacy Policy: You can only stop your own attendance sessions.", 403)
    if s["status"] == "ACTIVE":
        finalize_session(db, sid)
    return jsonify(success=True, message="Attendance session stopped.")


# ------------------------------------------------------------ location + attendance
def resolve_location(db, data):
    """Returns (lat, lon, distance, verified) or raises ValueError with a user message."""
    if config.DEMO_MODE:
        lat, lon = config.DEMO_LATITUDE, config.DEMO_LONGITUDE
    else:
        try:
            lat, lon = float(data.get("latitude")), float(data.get("longitude"))
        except (TypeError, ValueError):
            raise ValueError("Location not received. Please allow location access.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid location received.")
    dist = calculate_distance(lat, lon, get_setting(db, "classroom_lat"), get_setting(db, "classroom_lon"))
    return lat, lon, dist, dist <= get_setting(db, "radius")


def get_open_session(db, sid):
    close_expired(db)
    s = db.execute(SESSION_SQL + "WHERE s.id=?", (sid,)).fetchone()
    if not s:
        return None, err("No active class found.", 404)
    if s["status"] != "ACTIVE" or datetime.now() > datetime.strptime(s["end_time"], FMT):
        return None, err("Attendance window has expired.", 403, code="expired")
    return s, None


@app.post("/api/location/check")
def api_location():
    db = get_db()
    data = request.get_json(silent=True) or {}
    s, e = get_open_session(db, data.get("session_id"))
    if e: return e
    try:
        lat, lon, dist, ok = resolve_location(db, data)
    except ValueError as ex:
        return err(str(ex))
    msg = "Location verified." if ok else f"You are {dist:.0f} m from the classroom. Allowed radius is {get_setting(db, 'radius'):.0f} m."
    return jsonify(success=True, location_received=True, distance_calculated=round(dist, 1), location_verified=ok,
                   latitude=lat, longitude=lon, message=msg)


@app.post("/api/attendance/mark")
def api_mark():
    db = get_db()
    data = request.get_json(silent=True) or {}
    s, e = get_open_session(db, data.get("session_id"))          # 1. session + timetable + server time
    if e: return e
    try:                                                          # 2. geolocation (server-side distance)
        lat, lon, dist, loc_ok = resolve_location(db, data)
    except ValueError as ex:
        return err(str(ex))
    if not loc_ok:
        return err(f"Outside allowed area ({dist:.0f} m away). Attendance rejected.", 403, distance=round(dist, 1), location_verified=False)
    known = []                                                    # 3. face verification
    for r in db.execute("SELECT id, face_encoding FROM students WHERE face_encoding IS NOT NULL"):
        known.append((r["id"], np.array(json.loads(r["face_encoding"]))))
    try:
        enc, _ = face_utils.encode_single_face(data.get("image"))
        m = face_utils.best_match(enc, known)
    except FaceError as ex:
        return err(ex.message, 500 if ex.code == "server_error" else 422, code=ex.code)
    if not m:
        return err("Face not recognized. Please try again.", 422, code="not_recognized")
    student = db.execute("SELECT * FROM students WHERE id=?", (m[0],)).fetchone()
    if db.execute("SELECT 1 FROM attendance WHERE student_id=? AND timetable_id=? AND date=?",   # 4. duplicate
                  (student["id"], s["timetable_id"], s["date"])).fetchone():
        return err(f"{student['name']}, you are already marked present for this class.", 409, code="duplicate")
    now = datetime.now()
    try:                                                          # 5. store
        db.execute("""INSERT INTO attendance(student_id,session_id,timetable_id,subject,faculty,date,check_in_time,
                   latitude,longitude,distance,face_verified,location_verified,status) VALUES(?,?,?,?,?,?,?,?,?,?,1,1,'Present')""",
                   (student["id"], s["id"], s["timetable_id"], s["subject"], s["faculty"], s["date"],
                    now.strftime("%H:%M:%S"), lat, lon, round(dist, 1)))
        db.commit()
    except sqlite3.IntegrityError:
        return err("Attendance already recorded for this class.", 409, code="duplicate")
    except sqlite3.Error:
        return err("Database error. Please try again.", 500)
    return jsonify(success=True, message="Attendance marked successfully.", student=student["name"], roll=student["roll_number"],
                   subject=s["subject"], distance=round(dist, 1), time=now.strftime("%H:%M:%S"),
                   face_verified=True, location_verified=True, status="Present")


# ------------------------------------------------------------ students + face registration
@app.post("/api/students")
def api_add_student():
    d = request.get_json(silent=True) or {}
    if not all(str(d.get(k, "")).strip() for k in ("student_id", "name", "roll_number")):
        return err("Student ID, name and roll number are required.")
    try:
        db = get_db()
        name = d["name"].strip()
        first_name = name.split()[0].lower()
        pwd = f"{first_name}@2026"
        db.execute("INSERT INTO students(student_id,name,roll_number,email,course,semester,password) VALUES(?,?,?,?,?,?,?)",
                   (d["student_id"].strip(), name, d["roll_number"].strip(), d.get("email", ""),
                    d.get("course", "CSE"), int(d.get("semester") or 7), pwd))
        db.commit()
    except sqlite3.IntegrityError:
        return err("Student ID or roll number already exists.", 409)
    return jsonify(success=True, message="Student added.")


@app.post("/api/students/<int:sid>/face")
def api_register_face(sid):
    db = get_db()
    d = request.get_json(silent=True) or {}
    st = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not st:
        return err("Student not found.", 404)
    if st["face_encoding"] and not d.get("replace"):
        return err("Face already registered for this student.", 409, code="already_registered")
    try:
        enc, bgr = face_utils.encode_single_face(d.get("image"))
    except FaceError as ex:
        return err(ex.message, 500 if ex.code == "server_error" else 422, code=ex.code)
    others = [(r["id"], np.array(json.loads(r["face_encoding"]))) for r in
              db.execute("SELECT id, face_encoding FROM students WHERE face_encoding IS NOT NULL AND id<>?", (sid,))]
    m = face_utils.best_match(enc, others)
    if m:
        other = db.execute("SELECT name FROM students WHERE id=?", (m[0],)).fetchone()["name"]
        return err(f"This face is already registered to {other}.", 409)
    db.execute("UPDATE students SET face_encoding=? WHERE id=?", (json.dumps(enc.tolist()), sid))
    db.commit()
    os.makedirs(config.DATASET_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(config.DATASET_DIR, f"{st['student_id']}.jpg"), bgr)
    return jsonify(success=True, message=f"Face registered for {st['name']}.")


@app.delete("/api/students/<int:sid>/face")
@app.post("/api/students/<int:sid>/face/delete")
def api_remove_face(sid):
    db = get_db()
    st = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not st:
        return err("Student not found.", 404)
    db.execute("UPDATE students SET face_encoding=NULL WHERE id=?", (sid,))
    db.commit()
    img_path = os.path.join(config.DATASET_DIR, f"{st['student_id']}.jpg")
    if os.path.exists(img_path):
        try:
            os.remove(img_path)
        except OSError:
            pass
    return jsonify(success=True, message=f"Face registration canceled/removed for {st['name']}.")


# ------------------------------------------------------------ timetable API
def read_slot(d):
    day, st, en = d.get("day"), d.get("start_time", ""), d.get("end_time", "")
    name = (d.get("subject") or "").strip()
    if day not in DAYS or not re.fullmatch(r"\d{2}:\d{2}", st) or not re.fullmatch(r"\d{2}:\d{2}", en) or st >= en or not name:
        return None
    return day, st, en, name, (d.get("faculty") or "").strip(), (d.get("room") or "").strip()


def subject_id(db, name, fac, room):
    r = db.execute("SELECT id FROM subjects WHERE subject_name=?", (name,)).fetchone()
    if r: return r["id"]
    return db.execute("INSERT INTO subjects(subject_name,faculty,room) VALUES(?,?,?)", (name, fac, room)).lastrowid


@app.post("/api/timetable")
@app.put("/api/timetable/<int:tid>")
def api_timetable_save(tid=None):
    slot = read_slot(request.get_json(silent=True) or {})
    if not slot:
        return err("Invalid timetable entry (check day, times and subject).")
    db = get_db()
    day, st, en, name, fac, room = slot
    sub = subject_id(db, name, fac, room)
    if tid:
        db.execute("UPDATE timetable SET day=?,start_time=?,end_time=?,subject_id=?,faculty=?,room=? WHERE id=?", (day, st, en, sub, fac, room, tid))
    else:
        db.execute("INSERT INTO timetable(day,start_time,end_time,subject_id,faculty,room) VALUES(?,?,?,?,?,?)", (day, st, en, sub, fac, room))
    db.commit()
    return jsonify(success=True, message="Timetable saved.")


@app.delete("/api/timetable/<int:tid>")
def api_timetable_delete(tid):
    db = get_db()
    db.execute("DELETE FROM timetable WHERE id=?", (tid,))
    db.commit()
    return jsonify(success=True, message="Entry deleted.")


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return err("Resource not found.", 404)
    return "Not Found", 404


@app.errorhandler(500)
def server_error(_):
    return err("Server error. Please try again.", 500)


init_db.init()

if __name__ == "__main__":
    print("\n------------------------------------------------------------")
    print("Starting Smart Attendance Portal...")
    print("Access via Localhost:  https://127.0.0.1:5000 or http://127.0.0.1:5000")
    print("Access via Network IP: https://<YOUR_IP>:5000 (HTTPS required for camera)")
    print("------------------------------------------------------------\n")
    try:
        app.run(debug=True, host="0.0.0.0", port=5000, ssl_context="adhoc")
    except Exception as ex:
        print("Note: Starting standard HTTP server (Camera requires HTTPS on external IPs):", ex)
        app.run(debug=True, host="0.0.0.0", port=5000)
