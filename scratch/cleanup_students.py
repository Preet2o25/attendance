import sys
sys.path.insert(0, '.')
import db

conn = db.connect()
allowed_names = ["Preet", "Chitransh", "Mitesh"]

# Delete attendance records of students not in allowed list
conn.execute("""
    DELETE FROM attendance WHERE student_id IN (
        SELECT id FROM students WHERE name NOT IN ('Preet', 'Chitransh', 'Mitesh')
    )
""")

# Delete students not in allowed list
conn.execute("DELETE FROM students WHERE name NOT IN ('Preet', 'Chitransh', 'Mitesh')")
conn.commit()

# Ensure Preet, Chitransh, Mitesh are in the DB
targets = [
    ("STU001", "Preet", "CSE001", "preet@example.com", "preet@2026"),
    ("STU002", "Chitransh", "CSE002", "chitransh@example.com", "chitransh@2026"),
    ("STU003", "Mitesh", "CSE003", "mitesh@example.com", "mitesh@2026")
]

for sid, name, roll, email, pwd in targets:
    st = conn.execute("SELECT id FROM students WHERE name=?", (name,)).fetchone()
    if not st:
        conn.execute(
            "INSERT INTO students(student_id, name, roll_number, email, course, semester, password) VALUES(?,?,?,?,?,?,?)",
            (sid, name, roll, email, "CSE", 7, pwd)
        )
    else:
        conn.execute(
            "UPDATE students SET student_id=?, roll_number=?, email=?, password=? WHERE id=?",
            (sid, roll, email, pwd, st["id"])
        )

conn.commit()
print("Database cleanup complete! Current students in DB:")
for r in conn.execute("SELECT id, student_id, name, roll_number, email, password FROM students").fetchall():
    print(dict(r))
