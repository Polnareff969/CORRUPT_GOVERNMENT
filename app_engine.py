import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import httpx

app = FastAPI()

# Mount static for logo.jpg
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

DB_FILE = "students.txt"
PORTAL_IP = "82.25.125.30"
SESSION_ID = "a91h1f0n33i73qucmloitsauc5"

def get_student_data():
    """Reads and parses the manual students.txt file."""
    if not os.path.exists(DB_FILE):
        return []
    
    with open(DB_FILE, "r") as f:
        content = f.read()

    # Hardened Regex to handle the '[' at the start and the specific comma-separated pairs
    # Matches: studentID:2025-96-0187,name:JAYSON, LHAIZA DAYOLA,cys:BPA 1D,status:REGULAR
    pattern = r"studentID:(?P<id>.*?),name:(?P<name>.*?),cys:(?P<cys>.*?),status:(?P<status>.*?)(?=\n|studentID:|$)"
    
    results = []
    for match in re.finditer(pattern, content):
        sid = match.group("id").strip().replace("[", "") # Clean the initial bracket
        results.append({
            "id": sid,
            "name": match.group("name").strip(),
            "cys": match.group("cys").strip(),
            "status": match.group("status").strip()
        })
    return results

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("index.html")

@app.get("/api/search")
async def search(q: str = ""):
    query = q.upper()
    all_students = get_student_data()
    
    # Search across Name, ID, and Course
    matches = [
        s for s in all_students 
        if query in s['name'].upper() or query in s['id'] or query in s['cys'].upper()
    ]
    return matches[:26]

@app.get("/api/grades/{sid}")
async def get_grades(sid: str):
    url = f"https://{PORTAL_IP}/gs/admin-portal/view_student_grades.php?id={sid}"
    headers = {"Host": "sb.ccsjdm.com"}
    cookies = {"PHPSESSID": SESSION_ID}
    
    async with httpx.AsyncClient(verify=False) as client:
        try:
            r = await client.get(url, headers=headers, cookies=cookies, timeout=12.0)
            soup = BeautifulSoup(r.text, 'html.parser')
            results = []
            
            for table in soup.find_all('table'):
                caption = table.find('caption')
                semester = caption.get_text(strip=True) if caption else "Academic Term"
                year_tag = table.find_previous('h2')
                year = year_tag.get_text(strip=True) if year_tag else ""
                
                subjects = []
                # Matches the specific row classes in the portal
                for row in table.find_all('tr', class_='bg-white border'):
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 7:
                        subjects.append({
                            "code": cols[0].get_text(strip=True),
                            "desc": cols[1].get_text(strip=True),
                            "prof": cols[3].get_text(strip=True),
                            "mid": cols[4].get_text(strip=True),
                            "fin": cols[5].get_text(strip=True),
                            "gwa": cols[6].get_text(strip=True)
                        })
                
                if subjects:
                    # Find total GWA in the footer row
                    footer = table.find('tr', class_='bg-slate-200')
                    total = footer.find_all('td')[-1].get_text(strip=True) if footer else "N/A"
                    results.append({"year": year, "semester": semester, "data": subjects, "total_gwa": total})
            
            return results
        except Exception:
            return []
