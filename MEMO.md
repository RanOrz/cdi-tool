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

## 待确认事项（需要实际运行验证）

1. **SearchIndvId 参数**：params[2] 是否正确？如果运行后发现 business_address 全部为空，
   可能需要改回 params[1]，或两个 ID 的意义需要进一步探查。
   
2. **form1 位于哪些页面**：当前假设 CDI 所有页面都有 form1（模板级组件）。
   如果某些页面没有，`_post_detail_form()` 会超时并跳过该条记录。

3. **Cloudflare 重验证**：每次 `driver.get(CDI_SEARCH_URL)` 都会检查 session。
   目前假设验证过一次后整个 session 内有效。如果后续出现 CAPTCHA，
   工具会在 `_wait_for_turnstile()` 处暂停等用户手动完成。

4. **First Name 字段 ID**：分段查询时填 First Name 的字段尝试了
   `SearchFirstName`、`FirstName`、`txtFirstName` 三个 ID，没有实测。
   如果 A-Z 分段没效果（每段结果还是一样），可能 First Name 字段 ID 不对。

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
