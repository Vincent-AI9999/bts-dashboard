"""
main.py – Cloud Version dùng GitHub làm data store
"""
import io, json, math, os, base64, traceback, threading
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

import requests as http_requests
import pandas as pd
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Cấu hình ──────────────────────────────────────────────
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "Vincent-AI9999/bts-data")
GITHUB_FILE  = os.environ.get("GITHUB_FILE", "data.json")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

GH_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ── GitHub API ─────────────────────────────────────────────
def gh_get_file():
    """Tải JSON từ GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    resp = http_requests.get(url, headers=GH_HEADERS, timeout=15)
    resp.raise_for_status()
    info = resp.json()
    content = base64.b64decode(info["content"]).decode("utf-8")
    return json.loads(content), info["sha"]

def gh_put_file(data: dict, sha: str, msg: str = "Update via Dashboard"):
    """Ghi JSON lên GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    content = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()
    resp = http_requests.put(url, headers=GH_HEADERS, timeout=30, json={
        "message": msg, "content": content, "sha": sha
    })
    resp.raise_for_status()
    return resp.json()["content"]["sha"]

# ── Cache ──────────────────────────────────────────────────
_cache = {"data": None, "sha": None}

def _load(force=False):
    global _cache
    try:
        data, sha = gh_get_file()
        # Dùng cache nếu SHA không đổi
        if not force and _cache["sha"] == sha and _cache["data"]:
            return _cache["data"]
        _cache["data"] = data
        _cache["sha"] = sha
        return data
    except Exception as e:
        if _cache["data"]:
            return _cache["data"]  # Trả cache cũ nếu GitHub lỗi tạm thời
        raise

# ── Lifespan ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    def _preload():
        try:
            _load()
            print("[INFO] Preload GitHub data OK")
        except Exception as e:
            print(f"[WARN] Preload failed: {e}")
    threading.Thread(target=_preload, daemon=True).start()
    yield

# ── App ────────────────────────────────────────────────────
app = FastAPI(title="BTS Dashboard – Cloud", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class RentUpdate(BaseModel):
    ma_tram: str; nha_mang: str; column: str; value: str

# ══ API ROUTES (trước wildcard) ════════════════════════════

@app.get("/api/debug")
async def debug():
    try:
        data, sha = gh_get_file()
        return {
            "status": "OK",
            "sha": sha[:8],
            "tong_hop": len(data.get("tong_hop", [])),
            "doanh_thu": len(data.get("doanh_thu", [])),
            "last_updated": data.get("last_updated"),
        }
    except Exception as e:
        return {"status": "ERROR", "detail": str(e)}

@app.get("/api/dashboard/rent-data")
async def get_rent_data():
    import asyncio
    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _load)
        return data
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.post("/api/dashboard/update-rent")
async def update_rent(req: RentUpdate):
    import asyncio

    def _do():
        global _cache
        data, sha = gh_get_file()
        rows = data.get("doanh_thu", [])

        # Tìm dòng cần update
        found = False
        for row in rows:
            if (str(row.get("Mã Trạm Gốc","")).strip() == req.ma_tram.strip() and
                str(row.get("Nhà Mạng","")).strip() == req.nha_mang.strip()):
                # Chuẩn hóa giá trị
                val = req.value.strip()
                if any(k in req.column for k in ["Đơn Giá","Tiền"]):
                    try: val = float(val.replace(",","").replace("₫",""))
                    except: pass
                if "Trạng Thái" in req.column:
                    val = {"ĐÃ TT":"Đã TT","CHƯA TT":"Chưa TT","ĐANG XỬ LÝ":"Đang Xử Lý"}.get(val.upper(), val)
                row[req.column] = val
                found = True
                break

        if not found:
            raise ValueError(f"Không tìm thấy {req.ma_tram} – {req.nha_mang}")

        data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_sha = gh_put_file(data, sha, f"Update {req.ma_tram} – {req.column}")
        _cache["sha"] = new_sha
        _cache["data"] = data

    try:
        await asyncio.get_event_loop().run_in_executor(None, _do)
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.get("/api/network-info")
async def network_info():
    host = os.environ.get("RENDER_EXTERNAL_URL", "https://bts-dashboard.onrender.com")
    return {"url": host, "type": "cloud", "note": "Cloud – Render.com"}

# ══ STATIC (sau wildcard) ══════════════════════════════════

@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/{filename}")
async def static_file(filename: str):
    p = FRONTEND_DIR / filename
    if p.exists() and p.is_file():
        return FileResponse(str(p))
    raise HTTPException(404, f"{filename} not found")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
