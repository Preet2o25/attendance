import sys
sys.path.insert(0, '.')
from app import app

client = app.test_client()

print('=== Test 1: Student Login (Preet) ===')
res_login = client.post('/api/login', json={'role': 'student', 'username': 'STU001', 'password': 'preet@2026'})
print('Login Status:', res_login.status_code, res_login.get_json())

print('\n=== Test 2: Student Dashboard View ===')
res_dash = client.get('/')
stu_dash_html = res_dash.get_data(as_text=True)
print('Dashboard Status:', res_dash.status_code)
print('- Mark Attendance button removed from Student Header:', '📸 Mark Attendance' not in stu_dash_html)
print('- Smart Attendance Portal branding present:', 'Smart Attendance Portal' in stu_dash_html)
print('- Yellow DEMO MODE banner removed:', 'DEMO MODE' not in stu_dash_html)

print('\n=== Test 3: Student Timetable Page View ===')
res_tt = client.get('/timetable')
tt_html = res_tt.get_data(as_text=True)
print('Timetable Status:', res_tt.status_code)
print('- Student can view Weekly Timetable:', 'Weekly Timetable Schedule' in tt_html)
print('- Admin Add/Edit form hidden from Student:', 'Add / edit class' not in tt_html)

print('\n=== Test 4: Student restricted from /attendance ===')
res_att_stu = client.get('/attendance', follow_redirects=False)
print('Student accessing /attendance -> Status:', res_att_stu.status_code, 'Redirected to:', res_att_stu.headers.get('Location'))

print('\n=== Test 5: Faculty Login (Dr. Mehta) ===')
client.get('/logout')
client.post('/api/login', json={'role': 'faculty', 'username': 'FAC001', 'password': 'mehta@2026'})

res_fac_att = client.get('/attendance')
print('Faculty accessing /attendance -> Status:', res_fac_att.status_code)

res_fac_tt = client.get('/timetable')
fac_tt_html = res_fac_tt.get_data(as_text=True)
print('Faculty accessing /timetable -> Admin Add/Edit form present:', 'Add / edit class' in fac_tt_html)
