import sys
sys.path.insert(0, '.')
from app import app, get_db

client = app.test_client()

print('=== Test 1: Verify current students ===')
with app.app_context():
    db = get_db()
    students = db.execute("SELECT id, student_id, name, roll_number, face_encoding FROM students").fetchall()
    print("Students count:", len(students))
    for s in students:
        print(dict(s))

print('\n=== Test 2: Face Deletion Endpoint Test ===')
# Login as Faculty
client.post('/api/login', json={'role': 'faculty', 'username': 'FAC001', 'password': 'mehta@2026'})
target_id = students[0]['id']
target_name = students[0]['name']

res_del = client.delete(f'/api/students/{target_id}/face')
print('Face Deletion Status:', res_del.status_code, res_del.get_json())

with app.app_context():
    st_check = get_db().execute("SELECT id, name, face_encoding FROM students WHERE id=?", (target_id,)).fetchone()
    print('Face encoding after removal:', st_check['face_encoding'])

print('\n=== Test 3: Recent Attendance Query (Present & Absent) ===')
res_dash = client.get('/')
print('Dashboard Status:', res_dash.status_code)
html = res_dash.get_data(as_text=True)
print('Recent Attendance Section Present:', 'Recent attendance' in html)
