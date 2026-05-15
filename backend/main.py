"""
main.py – Cloud Version
Đọc/ghi Excel từ OneDrive qua Microsoft Graph API
"""
import io
import math
import socket
import traceback
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

import msal
import requests as http_requests
import pandas as pd
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Cấu hình (đọc từ biến môi trường – đặt trên Render.com) ──
import os

TENANT_ID     = os.environ["TENANT_ID"]
CLIENT_ID     = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
USER_EMAIL    = os.environ["USER_EMAIL"]
ONEDRIVE_PATH = os.environ.get("ONEDRIVE_PATH", "D_Data/Thông tin thanh toán tram/Trạm BTS_04_2026v2.xlsx")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ── Microsoft Graph Auth ──────────────────────────────────
def get_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Lỗi xác thực Azure: {result.get('error_description')}")
    return result["access_token"]

def graph_url(path: str) -> str:
    encoded = path.replace(" ", "%20")
    return f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/drive/root:/{encoded}"

# ── Đọc Excel từ OneDrive ─────────────────────────────────
def download_excel_bytes() -> bytes:
    token = get_token()
    url = graph_url(ONEDRIVE_PATH) + ":/content"
    resp = http_requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()
    return resp.content

def upload_excel_bytes(data: bytes):
    token = get_token()
    url = graph_url(ONEDRIVE_PATH) + ":/content"
    resp = http_requests.put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        data=data,
        timeout=60,
    )
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

def _clean_records(df):
    return [{k: _safe(v) for k, v in zip(df.columns, row)} for row in df.itertuples(index=False)]

def _load_from_onedrive(force=False):
    global _cache
    # Kiểm tra ETag để tránh tải lại nếu file không thay đổi
    try:
        token = get_token()
        meta_url = graph_url(ONEDRIVE_PATH)
        meta = http_requests.get(meta_url, headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        etag = meta.get("eTag", "")
        if not force and _cache["data"] and _cache["etag"] == etag:
            return _cache["data"]
    except:
        etag = None
        if _cache["data"] and not force:
            return _cache["data"]

    raw = download_excel_bytes()
    df_th = pd.read_excel(io.BytesIO(raw), sheet_name="2_Danh_Muc_Tram_Tong_Hop")
    df_dt = pd.read_excel(io.BytesIO(raw), sheet_name="3_Quan_Ly_Doanh_Thu_Nha_Mang")

    data = {
        "tong_hop": _clean_records(df_th),
        "doanh_thu": _clean_records(df_dt),
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    _cache["data"] = data
    _cache["etag"] = etag
    return data

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    def _preload():
        try:
            _load_from_onedrive()
            print("[INFO] Đã nạp sẵn dữ liệu từ OneDrive vào cache.")
        except Exception as e:
            print(f"[WARN] Preload thất bại: {e}")
    threading.Thread(target=_preload, daemon=True).start()
    yield

# ── App ───────────────────────────────────────────────────
app = FastAPI(title="BTS Rent Dashboard – Cloud", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class RentUpdate(BaseModel):
    ma_tram: str
    nha_mang: str
    column: str
    value: str

# ── Routes ────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/{filename}")
async def static_file(filename: str):
    p = FRONTEND_DIR / filename
    if p.exists() and p.is_file():
        return FileResponse(str(p))
    raise HTTPException(404, f"{filename} không tồn tại")

@app.get("/api/dashboard/rent-data")
async def get_rent_data():
    import asyncio
    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _load_from_onedrive)
        return data
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.post("/api/dashboard/update-rent")
async def update_rent(req: RentUpdate):
    import asyncio

    def _do():
        global _cache
        raw = download_excel_bytes()
        excel_data = pd.read_excel(io.BytesIO(raw), sheet_name=None)

        sheet = "3_Quan_Ly_Doanh_Thu_Nha_Mang"
        df = excel_data[sheet]
        mask = (df["Mã Trạm Gốc"].astype(str).str.strip() == req.ma_tram.strip()) & \
               (df["Nhà Mạng"].astype(str).str.strip() == req.nha_mang.strip())
        if not mask.any():
            raise ValueError(f"Không tìm thấy {req.ma_tram} – {req.nha_mang}")

        val = req.value.strip()
        if any(k in req.column for k in ["Đơn Giá", "Tiền"]):
            try: val = float(val.replace(",", "").replace("₫", ""))
            except: pass
        if "Trạng Thái" in req.column:
            mp = {"ĐÃ TT": "Đã TT", "CHƯA TT": "Chưa TT", "ĐANG XỬ LÝ": "Đang Xử Lý"}
            val = mp.get(val.upper(), val)

        df.loc[mask, req.column] = val

        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            for sname, sdf in excel_data.items():
                sdf.to_excel(w, sheet_name=sname, index=False)
        upload_excel_bytes(out.getvalue())
        _cache["etag"] = None  # Invalidate

    try:
        await asyncio.get_event_loop().run_in_executor(None, _do)
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.get("/api/network-info")
async def network_info():
    return {"url": "https://bts-dashboard.onrender.com", "type": "cloud", "note": "Cloud server"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
