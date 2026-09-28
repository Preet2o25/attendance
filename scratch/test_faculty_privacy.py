import sys
sys.path.insert(0, '.')
from app import app, get_db

client = app.test_client()

print('--- Test 1: Dr. Mehta (FAC001) Login ---')
res_login = client.post('/api/login', json={'role': 'faculty', 'username': 'FAC001', 'password': 'mehta@2026'})
print('Login Status:', res_login.status_code, res_login.get_json())

print('\n--- Test 2: Dr. Mehta Dashboard View ---')
res_dash = client.get('/')
html = res_dash.get_data(as_text=True)
print('Dashboard Status:', res_dash.status_code)

print('\n--- Test 3: Session Starting Privacy Check ---')
with app.app_context():
    db = get_db()
    shah_slot = db.execute("SELECT id, faculty FROM timetable WHERE faculty='Prof. Shah'").fetchone()
    mehta_slot = db.execute("SELECT id, faculty FROM timetable WHERE faculty='Dr. Mehta'").fetchone()

if shah_slot:
    res_start_shah = client.post('/api/sessions/start', json={'timetable_id': shah_slot['id']})
    print('Attempting to start Prof. Shah slot -> Status:', res_start_shah.status_code, res_start_shah.get_json())

if mehta_slot:
    res_start_mehta = client.post('/api/sessions/start', json={'timetable_id': mehta_slot['id']})
    print('Attempting to start Dr. Mehta slot -> Status:', res_start_mehta.status_code, res_start_mehta.get_json())
