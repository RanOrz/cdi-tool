"""
CDI猎头工具 — FastAPI后端
所有数据存储在内存中，进程退出后清空
"""

import asyncio
import csv
import io
import json
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from scraper import CDIScraper, SURNAME_LIST

app = FastAPI(title="CDI猎头工具", docs_url=None, redoc_url=None)


# ── 内存存储（进程级单例，重启即清空） ──────────────────────────────────────────

class AppStore:
    def __init__(self):
        self.surnames = [s.copy() for s in SURNAME_LIST]
        self.status = "idle"           # idle | running | waiting_captcha | done | error
        self.progress = {"current": "", "done": 0, "total": 0}
        self.results: list = []        # List[dict]，查询到的执照记录
        self.errors: list = []         # List[str]，单条查询失败的错误信息
        self.error_message = ""        # 全局错误（浏览器崩溃等）
        # ── 用户可配置项 ──
        self.state_filter = "CA"       # 只保留指定州；"ALL" 表示不过滤
        self.max_results = 100         # 找到此数量 Active 执照后停止（0 = 不限）
        self._stop_event = threading.Event()
        self._thread = None


store = AppStore()


# ── 启动时自动打开浏览器 ────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    async def _open_browser():
        await asyncio.sleep(1.5)
        webbrowser.open("http://localhost:8000")
    asyncio.create_task(_open_browser())


# ── 页面入口 ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = Path(__file__).parent / "index.html"
    try:
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HTMLResponse(content="<h1>找不到 index.html，请确保文件在同一目录下</h1>", status_code=500)


# ── 姓氏列表 ────────────────────────────────────────────────────────────────────

@app.get("/api/surnames")
async def get_surnames():
    return store.surnames


class SurnamesBody(BaseModel):
    surnames: list


@app.put("/api/surnames")
async def update_surnames(body: SurnamesBody):
    if store.status == "running":
        raise HTTPException(status_code=400, detail="查询进行中，无法修改姓氏列表")
    store.surnames = body.surnames
    return {"ok": True}


# ── 查询控制 ────────────────────────────────────────────────────────────────────

@app.post("/api/search/start")
async def start_search():
    if store.status == "running":
        raise HTTPException(status_code=400, detail="查询已在进行中，请等待完成")

    # 重置本次查询状态（保留姓氏配置）
    store.status = "running"
    store.results = []
    store.errors = []
    store.error_message = ""
    store.progress = {"current": "", "done": 0, "total": 0}
    store._stop_event.clear()

    def _worker():
        scraper = CDIScraper()
        scraper.run(store.surnames, store, store._stop_event,
                    state_filter=store.state_filter,
                    max_results=store.max_results)

    store._thread = threading.Thread(target=_worker, daemon=True)
    store._thread.start()
    return {"ok": True}


@app.post("/api/search/stop")
async def stop_search():
    store._stop_event.set()
    # 状态由爬虫线程在退出时设置为done/idle，这里只标记中止意图
    return {"ok": True}


# ── SSE进度流 ─────────────────────────────────────────────────────────────────

@app.get("/api/search/progress")
async def progress_stream():
    """
    Server-Sent Events端点
    前端用 new EventSource('/api/search/progress') 订阅，每0.8秒推送一次状态
    """
    async def generate():
        while True:
            payload = json.dumps({
                "status":        store.status,
                "progress":      store.progress,
                "result_count":  len(store.results),
                "errors":        store.errors[-5:],   # 最近5条单项错误
                "error_message": store.error_message,
            })
            yield f"data: {payload}\n\n"

            if store.status in ("done", "error"):
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 禁用nginx缓冲，保证实时性
        },
    )


# ── 结果操作 ────────────────────────────────────────────────────────────────────

@app.get("/api/results")
async def get_results():
    return store.results


class LinkedInBody(BaseModel):
    linkedin_url: str


@app.patch("/api/results/{result_id}/linkedin")
async def update_linkedin(result_id: str, body: LinkedInBody):
    for r in store.results:
        if r["id"] == result_id:
            r["linkedin_url"] = body.linkedin_url.strip()
            return {"ok": True}
    raise HTTPException(status_code=404, detail="记录不存在")


# ── 查询设置 ────────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return {"state_filter": store.state_filter, "max_results": store.max_results}


class SettingsBody(BaseModel):
    state_filter: str
    max_results: int


@app.put("/api/settings")
async def update_settings(body: SettingsBody):
    if store.status == "running":
        raise HTTPException(status_code=400, detail="查询进行中，无法修改设置")
    store.state_filter = body.state_filter.strip().upper() or "ALL"
    store.max_results = max(0, body.max_results)
    return {"ok": True}


# ── CSV导出 ─────────────────────────────────────────────────────────────────────

# 严格按照指定顺序输出列
CSV_COLUMNS = [
    "linkedin_profile_url",
    "first_name",
    "last_name",
    "license_type",
    "license_number",
    "expiration_date",
    "contact_status",
    "notes",
]


@app.get("/api/export")
async def export_csv():
    if not store.results:
        raise HTTPException(status_code=400, detail="暂无数据可导出，请先完成查询")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    for r in store.results:
        writer.writerow({
            "linkedin_profile_url": r.get("linkedin_url", ""),
            "first_name":           r.get("first_name", ""),
            "last_name":            r.get("last_name", ""),
            "license_type":         r.get("license_type", ""),
            "license_number":       r.get("license_number", ""),
            "expiration_date":      r.get("expiration_date", ""),
            "contact_status":       r.get("contact_status", ""),
            "notes":                r.get("notes", ""),
        })

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",   # utf-8-sig让Excel正确显示中文
        headers={"Content-Disposition": "attachment; filename=cdi_leads.csv"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
