import os
import re
import asyncio
import httpx
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from bs4 import BeautifulSoup

app = FastAPI()

# Config
DB_FILE = "students.txt"
PORTAL_IP = "82.25.125.30"
SESSION_ID = "a91h1f0n33i73qucmloitsauc5"
STUDENT_CACHE = []

def parse_student_dump():
    global STUDENT_CACHE
    if not os.path.exists(DB_FILE):
        return
    with open(DB_FILE, "r") as f:
        data = f.read()
    # Matches the raw format: studentID:xxx,name:xxx,cys:xxx,status:xxx
    pattern = r"studentID:(.*?),name:(.*?),cys:(.*?),status:(.*?)(?=\n|studentID:|$)"
    matches = re.findall(pattern, data)
    STUDENT_CACHE = [
        {"id": m[0].strip(), "name": m[1].strip(), "cys": m[2].strip(), "status": m[3].strip()}
        for m in matches
    ]

@app.on_event("startup")
async def startup():
    parse_student_dump()

# --- UI ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    # Serves your God Garou index.html from the root directory
    return FileResponse("index.html")

# --- API ROUTES ---

@app.get("/api/search")
async def search(q: str = ""):
    query = q.upper()
    # Returns 26 results to avoid high-digit restrictions
    return [s for s in STUDENT_CACHE if query in s['name'] or query in s['id']][:26]

@app.post("/api/sync")
async def sync_db(background_tasks: BackgroundTasks):
    async def do_sync():
        url = f"https://{PORTAL_IP}/gs/admin-portal/AjaxPHPfiles/students.php?allStudentData=true&buttonSelected=overall"
        headers = {"Host": "sb.ccsjdm.com", "User-Agent": "Mozilla/6.0"}
        cookies = {"PHPSESSID": SESSION_ID}
        async with httpx.AsyncClient(verify=False) as client:
            try:
                r = await client.get(url, headers=headers, cookies=cookies, timeout=6.0)
                if r.status_code == 200:
                    with open(DB_FILE, "w") as f:
                        f.write(r.text)
                    parse_student_dump()
            except Exception: pass
    background_tasks.add_task(do_sync)
    return {"message": "Syncing..."}

@app.get("/api/grades/{sid}")
async def get_grades(sid: str):
    url = f"https://{PORTAL_IP}/gs/admin-portal/view_student_grades.php?id={sid}"
    headers = {"Host": "sb.ccsjdm.com"}
    cookies = {"PHPSESSID": SESSION_ID}

    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url, headers=headers, cookies=cookies, timeout=6.0)
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        tables = soup.find_all('table')
        
        for table in tables:
            caption = table.find('caption')
            semester = caption.get_text(strip=True) if caption else "Semester Data"
            year_header = table.find_previous('h2')
            year = year_header.get_text(strip=True) if year_header else ""

            subjects = []
            rows = table.find_all('tr', class_='bg-white border')
            for row in rows:
                cols = row.find_all(['th', 'td'])
                if len(cols) >= 7:
                    subjects.append({
                        "code": cols[0].get_text(strip=True),
                        "desc": cols[1].get_text(strip=True),
                        "prof": cols[3].get_text(strip=True),
                        "mid": cols[4].get_text(strip=True), 
                        "fin": cols[5].get_text(strip=True),
                        "gwa": cols[6].get_text(strip=True)
                    })
                elif "Total Final Grade" in row.get_text():
                    total = cols[-1].get_text(strip=True)
                    results.append({"year": year, "semester": semester, "data": subjects, "total_gwa": total})
        return results
