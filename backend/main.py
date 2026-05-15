"""
main.py – Cloud Version
Đọc/ghi Excel từ OneDrive qua Microsoft Graph API
"""
import io, math, os, socket, traceback, threading
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

import msal
import requests as http_requests
import pandas as pd
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Cấu hình (đọc từ biến môi trường – đặt trên Render.com) ──
TENANT_ID     = os.environ["TENANT_ID"]
CLIENT_ID     = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
USER_EMAIL    = os.environ["USER_EMAIL"]
ONEDRIVE_PATH = os.environ.get("ONEDRIVE_PATH", "D_Data/Thông tin thanh toán tram/Trạm BTS_04_2026v2.xlsx")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ── Microsoft Graph ───────────────────────────────────────
def get_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Azure auth error: {result.get('error_description','unknown')}")
    return result["access_token"]

def graph_url(path: str) -> str:
    return f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/drive/root:/{path}"

def download_excel() -> bytes:
    token = get_token()
    resp = http_requests.get(graph_url(ONEDRIVE_PATH) + ":/content",
                             headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()
    return resp.content

def upload_excel(data: bytes):
    token = get_token()
    resp = http_requests.put(graph_url(ONEDRIVE_PATH) + ":/content",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/octet-stream"},
                             data=data, timeout=60)
    resp.raise_for_status()

# ── Cache ─────────────────────────────────────────────────
_cache = {"data": None, "etag": None}

def _safe(v):
    if v is None: return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
    try:
        import pandas as _pd
        if isinstance(v, _pd.Timestamp): return None if _pd.isna(v) else v.strftime('%Y-%m-%d')
        if v is _pd.NaT: return None
    except: pass
    return v

def _clean(df):
    return [{k: _safe(v) for k, v in zip(df.columns, row)} for row in df.itertuples(index=False)]

def _load(force=False):
    global _cache
    # Lấy ETag để kiểm tra file có thay đổi không
    try:
        token = get_token()
        meta = http_requests.get(graph_url(ONEDRIVE_PATH),
                                 headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        etag = meta.get("eTag", "")
        if not force and _cache["data"] and _cache["etag"] == etag:
            return _cache["data"]
    except:
        etag = None
        if not force and _cache["data"]:
            return _cache["data"]

    raw = download_excel()
    df_th = pd.read_excel(io.BytesIO(raw), sheet_name="2_Danh_Muc_Tram_Tong_Hop")
    df_dt = pd.read_excel(io.BytesIO(raw), sheet_name="3_Quan_Ly_Doanh_Thu_Nha_Mang")
    data = {
        "tong_hop": _clean(df_th),
        "doanh_thu": _clean(df_dt),
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    _cache.update({"data": data, "etag": etag})
    return data

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    def _preload():
        try:
            _load()
            print("[INFO] Preload OneDrive OK")
        except Exception as e:
            print(f"[WARN] Preload failed: {e}")
    threading.Thread(target=_preload, daemon=True).start()
    yield

# ── App ───────────────────────────────────────────────────
app = FastAPI(title="BTS Rent Dashboard – Cloud", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class RentUpdate(BaseModel):
    ma_tram: str; nha_mang: str; column: str; value: str

# ══════════════════════════════════════════════════════════
# API ROUTES – phải đứng TRƯỚC route wildcard /{filename}
# ══════════════════════════════════════════════════════════

@app.get("/api/debug")
async def debug():
    results = {}
    try:
        token = get_token()
        results["azure_auth"] = "OK"
    except Exception as e:
        results["azure_auth"] = f"FAIL: {e}"
        return results
    try:
        meta = http_requests.get(graph_url(ONEDRIVE_PATH),
                                 headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if meta.status_code == 200:
            m = meta.json()
            results["onedrive_file"] = f"OK – {m.get('name')} ({m.get('size',0)//1024}KB)"
        else:
            results["onedrive_file"] = f"FAIL {meta.status_code}: {meta.text[:300]}"
    except Exception as e:
        results["onedrive_file"] = f"ERROR: {e}"
    results["config"] = {
        "user_email": USER_EMAIL,
        "onedrive_path": ONEDRIVE_PATH,
    }
    return results

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
        raw = download_excel()
        excel_data = pd.read_excel(io.BytesIO(raw), sheet_name=None)
        df = excel_data["3_Quan_Ly_Doanh_Thu_Nha_Mang"]
        mask = (df["Mã Trạm Gốc"].astype(str).str.strip() == req.ma_tram.strip()) & \
               (df["Nhà Mạng"].astype(str).str.strip() == req.nha_mang.strip())
        if not mask.any():
            raise ValueError(f"Không tìm thấy {req.ma_tram} – {req.nha_mang}")
        val = req.value.strip()
        if any(k in req.column for k in ["Đơn Giá","Tiền"]):
            try: val = float(val.replace(",","").replace("₫",""))
            except: pass
        if "Trạng Thái" in req.column:
            val = {"ĐÃ TT":"Đã TT","CHƯA TT":"Chưa TT","ĐANG XỬ LÝ":"Đang Xử Lý"}.get(val.upper(), val)
        df.loc[mask, req.column] = val
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            for s, d in excel_data.items(): d.to_excel(w, sheet_name=s, index=False)
        upload_excel(out.getvalue())
        _cache["etag"] = None
    try:
        await asyncio.get_event_loop().run_in_executor(None, _do)
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.get("/api/network-info")
async def network_info():
    import os
    host = os.environ.get("RENDER_EXTERNAL_URL", "https://bts-dashboard.onrender.com")
    return {"url": host, "type": "cloud", "note": "Cloud – Render.com"}

# ══════════════════════════════════════════════════════════
# STATIC ROUTES – wildcard CUỐI CÙNG
# ══════════════════════════════════════════════════════════

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
