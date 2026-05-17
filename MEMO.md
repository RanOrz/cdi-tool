# 开发备忘录 — 2026-05-14

## 这次做了什么

### 1. 详情页抓取（scraper.py v4）

**CDI 详情页的实际机制**（通过测试发现）：

- 列表页每行执照号的链接 `onclick = SearchLic('LicNbr', 'ID1', 'ID2', 'IND')`
- 实际通过页面内隐藏的 `<form id="form1">` 以 **POST** 提交到 `/cal/LicenseDetail`
- form 原本 `target="_blank"`（新标签页），我改为 `target="_self"` 在同一个 tab 内完成

**参数映射**（待验证）：
- `SearchLicNbr` = params[0]（执照号，如 `0F77495`）
- `SearchType`   = params[3]（如 `IND`）
- `SearchIndvId` = **先试 params[2]，失败再试 params[1]**

  > 测试时用 params[1]='2807158' 收到 "Unable to retrieve license detail data" 错误。
  > params[2]='1098499' 尚未确认，已在代码里设为优先。
  > 如果两个都失败，该条记录的 business_address/phone 留空，查询继续。

**提取方式**：
- `business_address`：正则 `Business Address:\s*(.+)` 匹配 body text
- `business_phone`：正则 `Business Phone:\s*(.+)` 匹配 body text
- `license_type` / `expiration_date`：从详情页表格（`License Type and/or Qualification` 列头）提取 Active 行

**详情页后的导航**：
- 每抓完一条详情，自动导航回 `CDI_SEARCH_URL`（让 form1 重新可用）
- `_first_search = True` 重置，下次 `_submit_search()` 会正常工作

### 2. A-Z 分段查询

- 黑名单（over_limit.json）中的 Last Name 预展开为 26 个子查询（`Li A*`, `Li B*`...）
- 运行中撞到 500 条上限 → 动态在当前位置插入 26 个子查询
- 最多 3 级展开（A → AA → AAA），之后跳过并记录错误

### 3. UI 改动

- **输入框**：主字段改为 "CDI Last Name 搜索词"，"中文姓氏" 改为可选"备注"
- **标签显示**：Last Name 拼音为主（粗体），备注缩小括号内
- **返回按钮**：查询完成/停止后，进度卡片上方出现"← 修改查询列表"，点击回到第1步
- **黑名单展示**：设置区显示已知超限词，可手动移除

### 4. 结果上限行为

- max_results 的检查**移入内层循环**（逐条检查），达到上限立即停止详情抓取
- 不会再把整批结果全跑完才停

---

## 已验证结论（2026-05-16）

1. **SearchIndvId 参数**：✅ **params[2] 正确**。
   实测 License 0F77495（Alan Liang）：params[2]='1098499' 成功拿到地址和电话。
   params[1]='2807158' 会返回 "Unable to retrieve"。代码保持 [params[2], params[1]] 优先顺序不变。

2. **form1 可用性**：✅ CDI 搜索页和详情页都有 form1，模板级组件，全程可用。

3. **Cloudflare 重验证**：✅ undetected_chromedriver 自动通过 Turnstile，
   全程无需手动干预，session 内不重复验证。

4. **First Name 字段 ID**：✅ 实测为 `SearchFirstName`，已是代码里的第一候选，无需修改。

5. **端对端测试结果**：✅ 搜索 Liang，上限3条，全部获得 business_address 和 business_phone。
   共找到 179 条候选，按上限停在第3条，结果写入 results.jsonl 正常。

## 代码改动记录（2026-05-16）

- `scraper.py`：`_is_over_limit()` 恢复宽松判断（搜索页无地址，误判风险可忽略）
- `scraper.py`：`time.sleep(1.0)` → `stop_event.wait(1.0)`，停止按钮立即响应
- `scraper.py`：`_collect_batch()` 每条入库后调用 `store.persist(d)` 写文件
- `app.py`：`AppStore` 新增 `persist()`、`clear_results()` 方法，启动时自动恢复 results.jsonl
- `app.py`：新增 `DELETE /api/results` 接口（清空结果和文件）
- `app.py`：新增 `GET /api/status` 接口（供脚本轮询，含 errors 字段）
- `.gitignore`：新增 `results.jsonl`、`over_limit.json`

---

## 文件结构

```
cdi-tool/
├── app.py          # FastAPI 后端，API 路由，CSV 导出
├── scraper.py      # CDI 爬虫（v4），含详情页抓取
├── index.html      # 前端单页面
├── over_limit.json # 持久化黑名单（自动生成/更新）
├── requirements.txt
├── start.sh / start.bat
└── MEMO.md         # 本文件
```

---

## 快速启动

```bash
bash start.sh        # Mac
# 或
./venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://localhost:8000，建议先用"梁（Liang）"单独测试，上限设 5 条，
看 business_address 和 business_phone 列是否有数据。
