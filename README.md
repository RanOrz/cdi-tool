# CDI 猎头工具

自动查询加州保险局（CDI）执照持有人，辅助招募持有加州保险执照的华人从业者。

**数据来源**：[California Department of Insurance 公开查询系统](https://cdicloud.insurance.ca.gov/cal/IndividualNameSearch)  
**所有操作在本地运行，不上传任何数据到第三方。**

---

## 功能

- 按华人常见姓氏（30个预设，可自定义）批量查询 CDI 执照
- 自动翻页，汇总所有结果
- 结果按州过滤（默认仅 CA）
- 可设定总数上限（找到 N 条后停止）
- 每行提供 LinkedIn 搜索链接，方便确认身份后粘贴 URL
- 一键导出 CSV，列名与 InTouch 兼容

---

## 环境要求

| 要求 | 说明 |
|------|------|
| Python | 3.10 或以上 |
| Chrome 浏览器 | 已安装即可，工具自动匹配驱动 |
| 操作系统 | macOS / Windows |
| 网络 | 能访问 cdicloud.insurance.ca.gov |

---

## 快速开始

### Mac

```bash
# 1. 下载代码
git clone https://github.com/RanOrz/cdi-tool.git
cd cdi-tool

# 2. 启动（首次约需 2-3 分钟安装依赖）
bash start.sh
```

> **让 start.sh 可双击运行（可选）：**
> ```bash
> chmod +x start.sh
> ```
> 之后右键文件 → 打开方式 → 终端 即可双击启动。

### Windows

```
1. 下载代码（绿色 Code 按钮 → Download ZIP，解压）
2. 双击 start.bat
```

首次启动会自动创建虚拟环境并安装依赖，之后每次启动只需几秒。

---

## 使用流程

启动后浏览器自动打开 `http://localhost:8000`。

| 步骤 | 操作 |
|------|------|
| **1. 配置姓氏** | 检查预设的30个华人姓氏，可删除或添加 |
| **2. 设置过滤** | 选择州（默认仅CA）、设定结果上限（默认100条） |
| **3. 开始查询** | 点击「开始查询」，Chrome 窗口自动弹出并开始抓取 |
| **4. 确认 LinkedIn** | 对每条记录点击 🔍 按钮，在新标签页确认是目标人选，粘贴 LinkedIn URL |
| **5. 导出 CSV** | 点击「导出 CSV」，文件保存至浏览器下载目录 |

### 关于人机验证

首次查询时 CDI 网站会触发 Cloudflare 验证，通常**自动通过**，无需操作。  
如出现验证框，在弹出的 Chrome 窗口中手动完成一次即可，后续查询全程自动。

### 关于超过500条的姓氏

CDI 限制单次查询上限为 500 条。李（Li/Lee）、王（Wang）、陈（Chen）等大姓会触发此限制，工具会自动跳过并在进度区显示提示，建议前往 CDI 网站手动加名字筛选。

---

## 导出 CSV 列说明

| 列名 | 说明 |
|------|------|
| `linkedin_profile_url` | 粘贴的 LinkedIn 个人页 URL |
| `first_name` | CDI 记录中的名 |
| `last_name` | CDI 记录中的姓 |
| `license_type` | 执照类型（列表页暂不提供，留空） |
| `license_number` | CDI 执照编号 |
| `expiration_date` | 到期日（列表页暂不提供，留空） |
| `contact_status` | 联系状态（在 InTouch 中填写） |
| `notes` | 备注（在 InTouch 中填写） |

---

## ⚠️ 注意事项

- **请勿刷新浏览器页面**：所有数据仅保存在内存中，刷新后永久清空，请及时导出
- 本工具每次请求间隔 ≥2.5 秒，对 CDI 网站友好，请勿修改此参数
- 数据仅供招募参考，请遵守相关法律法规和 CDI 使用条款

---

## 常见问题

**Q：首次启动很慢？**  
A：首次需要下载 ChromeDriver 并安装依赖，约 2-5 分钟，之后启动只需几秒。

**Q：查询结果为0，或提示"找不到输入框"？**  
A：CDI 网站偶尔维护，请稍后重试。如持续失败，请提 Issue。

**Q：公司网络无法下载 ChromeDriver？**  
A：请联系 IT 开放对 `chromedriver.storage.googleapis.com` 的访问权限。

**Q：端口8000被占用？**  
A：在 `start.sh` / `start.bat` 中将 `--port 8000` 改为其他端口（如 8001）。

---

## 技术栈

- **后端**：Python 3.10+ · FastAPI · undetected-chromedriver · Selenium 4.x
- **前端**：原生 HTML / CSS / JavaScript，无外部框架依赖
- **数据**：仅存于内存，不写磁盘，不联网上传
