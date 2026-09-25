import os, random
from datetime import date, datetime, timedelta
import config
from db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  roll_number TEXT UNIQUE NOT NULL, email TEXT, course TEXT, semester INTEGER, face_encoding TEXT);
CREATE TABLE IF NOT EXISTS subjects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_name TEXT UNIQUE NOT NULL, faculty TEXT, room TEXT);
CREATE TABLE IF NOT EXISTS timetable(
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  subject_id INTEGER NOT NULL REFERENCES subjects(id), faculty TEXT, room TEXT);
CREATE TABLE IF NOT EXISTS attendance_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, timetable_id INTEGER NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
  date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE');
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id),
  session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
  timetable_id INTEGER NOT NULL, subject TEXT, faculty TEXT, date TEXT NOT NULL, check_in_time TEXT,
  latitude REAL, longitude REAL, distance REAL, face_verified INTEGER DEFAULT 0,
  location_verified INTEGER DEFAULT 0, status TEXT NOT NULL,
  UNIQUE(student_id, timetable_id, date));
"""

STUDENTS = [("STU001", "Aarav Patel", "CSE001", "aarav@example.com"),
            ("STU002", "Riya Shah", "CSE002", "riya@example.com"),
            ("STU003", "Dev Mehta", "CSE003", "dev@example.com"),
            ("STU004", "Anaya Patel", "CSE004", "anaya@example.com"),
            ("STU005", "Krish Shah", "CSE005", "krish@example.com")]
M, D, S, P, A = "Dr. Mehta", "Prof. Shah", None, "Prof. Patel", None
ML, DBMS, CN, AI, WD = "Machine Learning", "Database Management System", "Computer Networks", "Artificial Intelligence", "Web Development"
FAC = {ML: "Dr. Mehta", AI: "Dr. Mehta", DBMS: "Prof. Patel", CN: "Prof. Patel", WD: "Prof. Shah"}
TT = {"Monday": [ML, DBMS, CN], "Tuesday": [AI, WD, ML], "Wednesday": [DBMS, AI, CN],
      "Thursday": [ML, WD, DBMS], "Friday": [AI, ML, WD]}
# Timetable per spec (Wednesday DBMS is Prof. Patel etc. - faculty follows the subject)
SLOTS = [("09:00", "10:00"), ("10:00", "11:00"), ("11:00", "12:00")]


def init():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    os.makedirs(config.DATASET_DIR, exist_ok=True)
    db = connect()
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0:
        seed(db)
    db.commit()
    db.close()


def seed(db):
    for k, v in [("classroom_lat", config.CLASSROOM_LATITUDE), ("classroom_lon", config.CLASSROOM_LONGITUDE),
                 ("radius", config.ALLOWED_RADIUS_METERS)]:
        db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)))
    for sid, name, roll, mail in STUDENTS:
        db.execute("INSERT INTO students(student_id,name,roll_number,email,course,semester) VALUES(?,?,?,?,?,?)",
                   (sid, name, roll, mail, "CSE", 7))
    for name, fac in FAC.items():
        db.execute("INSERT INTO subjects(subject_name,faculty,room) VALUES(?,?,?)", (name, fac, "A101"))
    sub = {r["subject_name"]: r["id"] for r in db.execute("SELECT * FROM subjects")}
    for day, subs in TT.items():
        for (st, en), name in zip(SLOTS, subs):
            db.execute("INSERT INTO timetable(day,start_time,end_time,subject_id,faculty,room) VALUES(?,?,?,?,?,?)",
                       (day, st, en, sub[name], FAC[name], "A101"))
    # ---- historical sessions + attendance (last ~3 weeks) ----
    rnd = random.Random(42)
    prob = [0.92, 0.86, 0.95, 0.80, 0.88]
    students = db.execute("SELECT * FROM students").fetchall()
    tts = db.execute("SELECT t.*, s.subject_name FROM timetable t JOIN subjects s ON s.id=t.subject_id").fetchall()
    for back in range(1, 22):
        d = date.today() - timedelta(days=back)
        if d.weekday() > 4:
            continue
        for t in [x for x in tts if x["day"] == d.strftime("%A")]:
            start = datetime.strptime(f"{d} {t['start_time']}", "%Y-%m-%d %H:%M")
            cur = db.execute("INSERT INTO attendance_sessions(timetable_id,date,start_time,end_time,status) VALUES(?,?,?,?,'CLOSED')",
                             (t["id"], str(d), start.strftime("%Y-%m-%d %H:%M:%S"),
                              (start + timedelta(minutes=config.WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")))
            sess = cur.lastrowid
            for i, s in enumerate(students):
                if rnd.random() < prob[i]:
                    dist = rnd.randint(15, 70)
                    ci = start + timedelta(minutes=rnd.randint(0, 4), seconds=rnd.randint(0, 59))
                    db.execute("""INSERT INTO attendance(student_id,session_id,timetable_id,subject,faculty,date,check_in_time,
                               latitude,longitude,distance,face_verified,location_verified,status) VALUES(?,?,?,?,?,?,?,?,?,?,1,1,'Present')""",
                               (s["id"], sess, t["id"], t["subject_name"], t["faculty"], str(d), ci.strftime("%H:%M:%S"),
                                config.CLASSROOM_LATITUDE + dist / 111320 * 0.7, config.CLASSROOM_LONGITUDE + dist / 111320 * 0.7, dist))
                else:
                    db.execute("""INSERT INTO attendance(student_id,session_id,timetable_id,subject,faculty,date,status)
                               VALUES(?,?,?,?,?,?,'Absent')""", (s["id"], sess, t["id"], t["subject_name"], t["faculty"], str(d)))


if __name__ == "__main__":
    init()
    print("Database ready:", config.DB_PATH)
