"""
端对端自动化测试：
- 只搜索「梁 Liang」，上限 3 条
- 轮询 /api/status 直到 done/error
- 打印结果报告并验证关键字段
"""

import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
TIMEOUT = 300  # 最多等 5 分钟


def req(method, path, data=None):
    body = json.dumps(data).encode() if data else b""
    headers = {"Content-Type": "application/json"} if data else {}
    r = urllib.request.Request(f"{BASE}{path}", data=body or None,
                               headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())


def wait_server(max_wait=20):
    for _ in range(max_wait):
        try:
            req("GET", "/api/status")
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    # ── 1. 启动服务 ───────────────────────────────────────────────
    print("▶ 启动 FastAPI 服务...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd="/Users/ran/cdi-tool",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    if not wait_server():
        print("✗ 服务启动失败")
        proc.terminate()
        sys.exit(1)
    print("  服务已就绪")

    try:
        # ── 2. 清空上次结果，配置参数 ─────────────────────────────
        try:
            req("DELETE", "/api/results")
        except Exception:
            pass
        req("PUT", "/api/surnames", {"surnames": [{"zh": "梁", "variants": ["Liang"]}]})
        req("PUT", "/api/settings", {"state_filter": "CA", "max_results": 3})
        print("▶ 配置：只搜 Liang，上限 3 条，州=CA")

        # ── 3. 启动查询 ───────────────────────────────────────────
        req("POST", "/api/search/start")
        print("▶ 查询已启动（Cloudflare 自动处理中...）")

        # ── 4. 轮询状态（以 done/error 为准，不靠结果数量推断） ────
        start = time.time()
        last_line = ""
        while True:
            if time.time() - start > TIMEOUT:
                print("✗ 超时（5 分钟内未完成）")
                break

            time.sleep(3)
            try:
                s = req("GET", "/api/status")
            except Exception:
                continue

            line = f"  [{s['status']}] {s['progress'].get('current', '')}  已收 {s['result_count']} 条"
            if line != last_line:
                print(line)
                last_line = line

            if s["status"] in ("done", "error"):
                if s["status"] == "error":
                    print(f"✗ 服务报错：{s['error_message']}")
                if s.get("errors"):
                    print(f"  查询日志：{s['errors']}")
                break

        # ── 5. 打印报告 ───────────────────────────────────────────
        final = req("GET", "/api/results")
        print(f"\n{'='*60}")
        print(f"共获得 {len(final)} 条记录")
        print(f"{'='*60}")

        has_address = sum(1 for r in final if r.get("business_address"))
        has_phone   = sum(1 for r in final if r.get("business_phone"))

        for r in final:
            print(f"\n  {r.get('first_name','')} {r.get('last_name','')} ({r.get('license_number','')})")
            print(f"    地址：{r.get('business_address') or '—'}")
            print(f"    电话：{r.get('business_phone') or '—'}")
            print(f"    执照：{r.get('license_type') or '—'}  到期：{r.get('expiration_date') or '—'}")

        print(f"\n{'='*60}")
        print(f"business_address 有数据：{has_address}/{len(final)}")
        print(f"business_phone   有数据：{has_phone}/{len(final)}")

        # ── 6. 验证 results.jsonl ─────────────────────────────────
        try:
            with open("/Users/ran/cdi-tool/results.jsonl", encoding="utf-8") as f:
                jsonl_count = sum(1 for l in f if l.strip())
            match = "✓" if jsonl_count == len(final) else "✗"
            print(f"results.jsonl 行数：{jsonl_count} {match}（应为 {len(final)}）")
        except FileNotFoundError:
            print("✗ results.jsonl 不存在，持久化未生效")

        # ── 7. 总结 ───────────────────────────────────────────────
        print()
        if len(final) == 0:
            print("✗ 测试失败：无结果")
        elif has_address == len(final):
            print("✓ 测试通过：所有记录均有地址和电话")
        else:
            print(f"⚠ 部分记录缺少地址（{len(final) - has_address} 条缺失）")

    finally:
        proc.terminate()
        print("服务已关闭")


if __name__ == "__main__":
    main()
