import os
import re
import asyncio
import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup

app = FastAPI()

# Configuration
DB_FILE = "students.txt"
PORTAL_IP = "82.25.125.30"
# Session ID from your Termux test
SESSION_ID = "a91h1f0n33i73qucmloitsauc5"

# RAM Cache for fast searching on Render
STUDENT_CACHE = []

def parse_student_dump():
    """Parses the raw text dump into a searchable list."""
    global STUDENT_CACHE
    if not os.path.exists(DB_FILE):
        return
    
    with open(DB_FILE, "r") as f:
        data = f.read()
    
    # Regex matching the specific format in your students.txt
    pattern = r"studentID:(.*?),name:(.*?),cys:(.*?),status:(.*?)(?=\n|studentID:|$)"
    matches = re.findall(pattern, data)
    
    STUDENT_CACHE = [
        {"id": m[0].strip(), "name": m[1].strip(), "cys": m[2].strip(), "status": m[3].strip()}
        for m in matches
    ]

@app.on_event("startup")
async def startup():
    parse_student_dump()

@app.get("/api/search")
async def search(q: str = ""):
    query = q.upper()
    # Returns top 26 matches to stay within limits
    return [s for s in STUDENT_CACHE if query in s['name'] or query in s['id']][:26]

@app.post("/api/sync")
async def sync_db(background_tasks: BackgroundTasks):
    """Triggers the full database dump."""
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
            except Exception:
                pass

    background_tasks.add_task(do_sync)
    return {"message": "Syncing database..."}

@app.get("/api/grades/{sid}")
async def get_grades(sid: str):
    """Scrapes multiple semesters using index-based column parsing."""
    url = f"https://{PORTAL_IP}/gs/admin-portal/view_student_grades.php?id={sid}"
    headers = {"Host": "sb.ccsjdm.com"}
    cookies = {"PHPSESSID": SESSION_ID}

    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url, headers=headers, cookies=cookies, timeout=6.0)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        results = []
        # Find all table sections
        tables = soup.find_all('table')
        for table in tables:
            caption = table.find('caption')
            semester = caption.get_text(strip=True) if caption else "Unknown"
            
            # Find the Year Header (H2) preceding the table
            year_header = table.find_previous('h2')
            year = year_header.get_text(strip=True) if year_header else ""

            subjects = []
            rows = table.find_all('tr', class_='bg-white border')
            for row in rows:
                cols = row.find_all(['th', 'td'])
                
                # Grade Data Row (Matches your imissyou.txt structure)
                if len(cols) >= 7:
                    subjects.append({
                        "code": cols[0].get_text(strip=True),
                        "desc": cols[1].get_text(strip=True),
                        "prof": cols[3].get_text(strip=True),
                        "mid": cols[4].get_text(strip=True),  # 9x.xx
                        "fin": cols[5].get_text(strip=True),  # 9x.xx
                        "gwa": cols[6].get_text(strip=True)   # 1.xx
                    })
                
                # Total Semester GWA Row
                elif "Total Final Grade" in row.get_text():
                    summary_gwa = cols[-1].get_text(strip=True)
                    results.append({
                        "year": year,
                        "semester": semester,
                        "data": subjects,
                        "total_gwa": summary_gwa
                    })
        return results
