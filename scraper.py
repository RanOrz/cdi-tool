"""
CDI执照查询爬虫 v2
目标：https://cdicloud.insurance.ca.gov/cal/IndividualNameSearch
使用 undetected-chromedriver 绕过 Cloudflare Turnstile 检测
首次运行浏览器可见，如需人工验证用户手动完成一次即可
"""

import time
import threading
import uuid
from dataclasses import dataclass

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


CDI_SEARCH_URL = "https://cdicloud.insurance.ca.gov/cal/IndividualNameSearch"

# 已知会触发 CDI 500条上限的拼音（测试确认过，直接跳过节省时间）
KNOWN_OVER_LIMIT = {"Li", "Lee", "Wang", "Chen", "Chan", "Zhang", "Chang"}

# 30个华人常见姓氏及拼音变体
SURNAME_LIST = [
    {"zh": "李", "variants": ["Li", "Lee", "Lei"]},
    {"zh": "王", "variants": ["Wang"]},
    {"zh": "张", "variants": ["Zhang", "Chang"]},
    {"zh": "陈", "variants": ["Chen", "Chan", "Chin"]},
    {"zh": "刘", "variants": ["Liu", "Lew"]},
    {"zh": "杨", "variants": ["Yang"]},
    {"zh": "赵", "variants": ["Zhao", "Chao"]},
    {"zh": "黄", "variants": ["Huang", "Wong"]},
    {"zh": "吴", "variants": ["Wu", "Ng"]},
    {"zh": "周", "variants": ["Zhou", "Chou"]},
    {"zh": "徐", "variants": ["Xu", "Hsu"]},
    {"zh": "孙", "variants": ["Sun", "Suen"]},
    {"zh": "马", "variants": ["Ma"]},
    {"zh": "胡", "variants": ["Hu"]},
    {"zh": "朱", "variants": ["Zhu", "Chu"]},
    {"zh": "林", "variants": ["Lin", "Lim"]},
    {"zh": "何", "variants": ["He", "Ho"]},
    {"zh": "高", "variants": ["Gao", "Kao"]},
    {"zh": "梁", "variants": ["Liang", "Leung"]},
    {"zh": "郑", "variants": ["Zheng", "Cheng"]},
    {"zh": "罗", "variants": ["Luo", "Lo"]},
    {"zh": "宋", "variants": ["Song", "Sung"]},
    {"zh": "谢", "variants": ["Xie", "Hsieh"]},
    {"zh": "唐", "variants": ["Tang"]},
    {"zh": "韩", "variants": ["Han"]},
    {"zh": "曹", "variants": ["Cao", "Tsao"]},
    {"zh": "许", "variants": ["Xu", "Hsu", "Shyu"]},
    {"zh": "邓", "variants": ["Deng", "Teng"]},
    {"zh": "萧", "variants": ["Xiao", "Hsiao"]},
    {"zh": "冯", "variants": ["Feng", "Fong"]},
]


@dataclass
class Licensee:
    id: str
    first_name: str
    last_name: str
    license_number: str
    license_type: str       # 列表页不提供，留空
    expiration_date: str    # 列表页不提供，留空
    status: str
    city: str
    state: str = ""
    linkedin_url: str = ""
    contact_status: str = ""
    notes: str = ""


class CDIScraper:
    def __init__(self):
        self.driver = None
        self._first_search = True
        self._state_filter = "CA"
        self._max_results = 100

    def _init_driver(self):
        """可见 Chrome，undetected-chromedriver 绕过 Cloudflare 检测"""
        opts = uc.ChromeOptions()
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--no-sandbox")
        # headless=False：浏览器可见，用户能手动完成人机验证
        self.driver = uc.Chrome(options=opts, headless=False)

    def _quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _wait_for_turnstile(self):
        """
        等待 Cloudflare Turnstile 完成。
        大多数情况下自动通过；如出现可见验证框，用户手动点击即可。
        最多等待 120 秒。
        """
        try:
            WebDriverWait(self.driver, 120).until(
                lambda d: bool(
                    d.execute_script(
                        "return document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || ''"
                    )
                )
            )
        except TimeoutException:
            pass  # 超时后仍继续尝试提交

    def run(self, surname_config: list, store, stop_event: threading.Event,
            state_filter: str = "CA", max_results: int = 100):
        all_queries = [
            {"zh": s["zh"], "pinyin": v}
            for s in surname_config
            for v in s["variants"]
        ]
        total = len(all_queries)
        store.progress = {"current": "正在启动浏览器...", "done": 0, "total": total}
        seen_license_numbers = set()
        self._state_filter = state_filter.upper()
        self._max_results = max_results

        try:
            self._init_driver()
        except Exception as e:
            store.status = "error"
            store.error_message = f"浏览器启动失败，请重试。\n详情：{e}"
            return

        # 打开 CDI，等待 Cloudflare 验证
        try:
            self.driver.get(CDI_SEARCH_URL)
            store.status = "waiting_captcha"
            store.progress["current"] = "等待人机验证..."
            self._wait_for_turnstile()
            store.status = "running"
        except Exception as e:
            store.status = "error"
            store.error_message = f"加载 CDI 网站失败：{e}"
            self._quit_driver()
            return

        try:
            for i, q in enumerate(all_queries):
                if stop_event.is_set():
                    break

                store.progress = {
                    "current": f"{q['zh']}（{q['pinyin']}）",
                    "done": i,
                    "total": total,
                }

                # 已知超限的拼音直接跳过，不浪费请求
                if q["pinyin"] in KNOWN_OVER_LIMIT:
                    store.errors.append(
                        f'跳过 {q["zh"]}（{q["pinyin"]}）：已知结果超过CDI 500条上限，'
                        f'请前往 CDI 网站手动添加名字筛选'
                    )
                else:
                    try:
                        for r in self._search_one(q["pinyin"]):
                            if r.license_number not in seen_license_numbers:
                                seen_license_numbers.add(r.license_number)
                                store.results.append(r.__dict__.copy())
                    except Exception as e:
                        store.errors.append(f'查询"{q["pinyin"]}"失败：{e}')

                # 达到总数上限时停止
                if self._max_results > 0 and len(store.results) >= self._max_results:
                    store.errors.append(f'已达到设定上限 {self._max_results} 条，提前停止')
                    break

                # 对 CDI 网站友好：每次间隔 ≥2.5 秒
                if i < total - 1 and not stop_event.is_set():
                    time.sleep(2.5)

            store.progress["done"] = total
            store.status = "done"

        except Exception as e:
            store.status = "error"
            store.error_message = f"查询中断，请重启工具后重试。\n详情：{e}"
        finally:
            self._quit_driver()

    def _search_one(self, last_name: str) -> list:
        self._submit_search(last_name)

        # CDI 硬限制：超过 500 条时不返回任何数据
        # 这是 CDI 本身的设计，手工搜也一样，直接跳过并记录提示
        if self._is_over_limit():
            raise Exception(
                f"结果超过500条（CDI限制），已跳过。"
                f"如需查询，请前往 CDI 网站手动添加名字筛选。"
            )

        return self._collect_all_pages()

    def _submit_search(self, last_name: str) -> None:
        """填表并提交"""
        driver = self.driver
        wait = WebDriverWait(driver, 15)

        if self._first_search:
            self._first_search = False
        else:
            try:
                driver.find_element(By.ID, "btnClearSearch").click()
                time.sleep(0.8)
            except Exception:
                driver.get(CDI_SEARCH_URL)
                time.sleep(2)
                self._wait_for_turnstile()

        last_input = wait.until(EC.presence_of_element_located((By.ID, "SearchLastName")))
        last_input.clear()
        last_input.send_keys(last_name)
        driver.find_element(By.ID, "btnSearch").click()
        time.sleep(3)

    def _is_over_limit(self) -> bool:
        """检测 CDI 是否返回了超过500条的提示"""
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            return "500" in body and "refine" in body.lower()
        except Exception:
            return False

    def _collect_all_pages(self) -> list:
        """遍历所有分页，收集全部结果"""
        results = []
        page = 1

        while True:
            results.extend(self._parse_current_page())

            # 检查是否还有下一页（DataTables 分页）
            try:
                next_li = self.driver.find_element(
                    By.CSS_SELECTOR, "li.paginate_button.next, li.next"
                )
                if "disabled" in (next_li.get_attribute("class") or ""):
                    break
                next_li.find_element(By.TAG_NAME, "a").click()
                time.sleep(2)
                page += 1
            except (NoSuchElementException, Exception):
                break

            if page > 100:   # 安全上限
                break

        return results

    def _parse_current_page(self) -> list:
        """
        解析当前页结果表格
        列顺序：Last Name | Middle Name | First Name | License Number | Status | City | State | Resident Status
        """
        driver = self.driver
        results = []

        try:
            wait = WebDriverWait(driver, 10)
            table = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody"))
            )
            rows = table.find_elements(By.TAG_NAME, "tr")
        except TimeoutException:
            return []

        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 5:
                continue
            try:
                last_name      = cells[0].text.strip().title()
                first_name     = cells[2].text.strip().title()
                license_number = cells[3].text.strip()
                status         = cells[4].text.strip()
                city           = cells[5].text.strip().title() if len(cells) > 5 else ""
                state          = cells[6].text.strip()         if len(cells) > 6 else ""
            except IndexError:
                continue

            if status.lower() != "active":
                continue
            if not last_name or not license_number:
                continue
            # 州过滤：ALL 表示不限，否则只保留指定州
            if self._state_filter != "ALL" and state.upper() != self._state_filter:
                continue

            results.append(Licensee(
                id=str(uuid.uuid4()),
                first_name=first_name,
                last_name=last_name,
                license_number=license_number,
                license_type="",
                expiration_date="",
                status=status,
                city=city,
                state=state,
            ))

        return results
