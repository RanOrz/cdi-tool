"""
CDI执照查询爬虫 v4
- 超500条大姓自动 A-Z 分段，必要时继续展开 AA/AB...
- 每批列表结果收集完后，逐条用 form1 POST 进详情页提取
  business_address / business_phone / license_type / expiration_date
"""

import json
import re
import string
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


CDI_SEARCH_URL = "https://cdicloud.insurance.ca.gov/cal/IndividualNameSearch"
CDI_DETAIL_URL = "https://cdicloud.insurance.ca.gov/cal/LicenseDetail"

_OVER_LIMIT_FILE = Path(__file__).parent / "over_limit.json"


def load_over_limit() -> set:
    try:
        data = json.loads(_OVER_LIMIT_FILE.read_text(encoding="utf-8"))
        return set(data.get("over_limit", []))
    except Exception:
        return set()


def save_over_limit(s: set) -> None:
    try:
        _OVER_LIMIT_FILE.write_text(
            json.dumps({"over_limit": sorted(s)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


class OverLimitError(Exception):
    pass


# 加州华人最常见英文名（女性 + 男性）
FIRST_NAME_LIST = [
    # 女性
    "Alice", "Amy", "Angela", "Annie", "Betty", "Carol", "Cathy",
    "Christine", "Cindy", "Diana", "Emily", "Grace", "Helen", "Janet",
    "Jennifer", "Jenny", "Jessica", "Julie", "Karen", "Kelly", "Laura",
    "Linda", "Lisa", "Mary", "Michelle", "Nancy", "Rebecca", "Rose",
    "Sarah", "Susan", "Tina", "Vivian", "Wendy", "Yvonne",
    # 男性
    "Aaron", "Alan", "Albert", "Allen", "Andy", "Anthony", "Brian",
    "Charles", "Chris", "Daniel", "David", "Dennis", "Derek", "Eric",
    "Frank", "Gary", "George", "Henry", "Jack", "James", "Jason",
    "Jeff", "Jimmy", "John", "Kevin", "Larry", "Mark", "Michael",
    "Patrick", "Paul", "Peter", "Raymond", "Richard", "Robert",
    "Roger", "Ryan", "Sam", "Simon", "Stephen", "Thomas", "Tony",
    "Victor", "William", "Wilson",
]


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
    license_type: str
    expiration_date: str
    status: str
    city: str
    state: str = ""
    business_address: str = ""
    business_phone: str = ""
    linkedin_url: str = ""
    contact_status: str = ""
    notes: str = ""
    # internal scraping fields — stripped before storing in AppStore
    _onclick_params: list = field(default_factory=list, repr=False)


def _make_query(zh: str, pinyin: str, prefix: str = "") -> dict:
    return {"zh": zh, "pinyin": pinyin, "prefix": prefix}


class CDIScraper:
    def __init__(self):
        self.driver = None
        self._first_search = True
        self._state_filter = "CA"
        self._max_results = 10
        self._over_limit: set = load_over_limit()
        self._fn_field_id: str = None   # discovered at runtime

    # ── Driver ────────────────────────────────────────────────────

    def _init_driver(self):
        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=900,620")
        self.driver = uc.Chrome(options=opts, headless=False)

    def _quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _wait_for_turnstile(self):
        try:
            WebDriverWait(self.driver, 120).until(
                lambda d: bool(d.execute_script(
                    "return document.querySelector"
                    "('input[name=\"cf-turnstile-response\"]')?.value || ''"
                ))
            )
        except TimeoutException:
            pass

    # ── Query list ────────────────────────────────────────────────

    def _build_query_list(self, surname_config: list) -> list:
        queries = []
        for s in surname_config:
            for v in s["variants"]:
                queries.append(_make_query(s["zh"], v, ""))
        return queries

    # ── Main loop ─────────────────────────────────────────────────

    def run(self, surname_config: list, store, stop_event: threading.Event,
            state_filter: str = "CA", max_results: int = 10):

        self._state_filter = state_filter.upper()
        self._max_results = max_results
        all_queries = self._build_query_list(surname_config)
        # 用已有结果的执照号初始化去重集合，避免追加时产生重复记录
        seen_numbers: set = {r.get("license_number", "") for r in store.results if r.get("license_number")}
        # max_results 按本次运行新增量计算，不计入之前批次的存量
        self._run_start = len(store.results)

        store.progress = {"current": "正在启动浏览器...", "done": 0, "total": len(all_queries)}

        try:
            self._init_driver()
        except Exception as e:
            store.status = "error"
            store.error_message = f"浏览器启动失败：{e}"
            return

        try:
            self.driver.get(CDI_SEARCH_URL)
            store.status = "waiting_captcha"
            store.progress["current"] = "等待人机验证..."
            self._wait_for_turnstile()
            store.status = "running"
        except Exception as e:
            store.status = "error"
            store.error_message = f"加载CDI失败：{e}"
            self._quit_driver()
            return

        try:
            for i, q in enumerate(all_queries):
                if stop_event.is_set():
                    break
                if self._max_results > 0 and (len(store.results) - self._run_start) >= self._max_results:
                    store.errors.append(f'已达到设定上限 {self._max_results} 条，停止')
                    break

                store.progress["done"] = i
                self._search_trie(q["pinyin"], "", store, seen_numbers, q["zh"], stop_event)

                if not stop_event.is_set():
                    stop_event.wait(1.0)

            store.progress["done"] = len(all_queries)
            store.status = "done"

        except Exception as e:
            store.status = "error"
            store.error_message = f"查询中断：{e}"
        finally:
            self._quit_driver()

    # ── Search ────────────────────────────────────────────────────

    def _search_trie(self, last_name: str, prefix: str, store, seen_numbers: set,
                     zh: str, stop_event: threading.Event, depth: int = 0) -> None:
        """DFS trie traversal over first-name prefixes.

        - over 500 → recurse into prefix+'a' … prefix+'z'
        - ≤500 (including 0) → collect results, return; parent loop advances to next letter
        - depth > 4 → give up on this branch (safety cap)
        """
        if stop_event.is_set():
            return
        if self._max_results > 0 and (len(store.results) - self._run_start) >= self._max_results:
            return
        if depth > 4:
            store.errors.append(f'⚠️ "{last_name} {prefix}*" 超过最大深度，跳过')
            return

        label = f"{zh}（{last_name}" + (f" {prefix}*" if prefix else "") + "）"
        store.progress["current"] = label

        try:
            batch = self._search_one(last_name, prefix)
            before = len(store.results)
            self._collect_batch(batch, store, seen_numbers, label, stop_event)
            store.log_query(zh, last_name, prefix, len(store.results) - before, "ok")

        except OverLimitError:
            store.log_query(zh, last_name, prefix, 0, "over_limit")
            for letter in string.ascii_lowercase:
                if stop_event.is_set():
                    break
                if self._max_results > 0 and (len(store.results) - self._run_start) >= self._max_results:
                    break
                self._search_trie(last_name, prefix + letter, store, seen_numbers,
                                  zh, stop_event, depth + 1)
                if not stop_event.is_set():
                    stop_event.wait(0.5)

        except Exception as e:
            store.errors.append(f'查询"{label}"失败：{e}')
            store.log_query(zh, last_name, prefix, 0, "error")

    def _collect_batch(self, batch, store, seen_numbers, label, stop_event):
        """Process a list of Licensee records into store.results."""
        for j, r in enumerate(batch):
            if stop_event.is_set():
                break
            if self._max_results > 0 and (len(store.results) - self._run_start) >= self._max_results:
                break
            if r.license_number in seen_numbers:
                continue
            seen_numbers.add(r.license_number)
            if r._onclick_params:
                store.progress["current"] = f"{label} 详情 {j + 1}/{len(batch)}"
                self._fetch_detail_into(r)
                stop_event.wait(1.0)
            d = r.__dict__.copy()
            d.pop("_onclick_params", None)
            store.results.append(d)
            store.persist(d)

    def _search_one(self, last_name: str, prefix: str = "") -> list:
        self._submit_search(last_name, prefix)
        if self._is_over_limit():
            raise OverLimitError(f"{last_name} {prefix}*".strip())
        return self._collect_all_pages()

    def _find_first_name_field(self):
        """Locate the First Name input on the CDI search page, cache the result."""
        if self._fn_field_id:
            try:
                return self.driver.find_element(By.ID, self._fn_field_id)
            except Exception:
                self._fn_field_id = None

        # 1) try known IDs
        for fid in ("SearchFirstName", "FirstName", "txtFirstName", "first_name", "fname"):
            try:
                el = self.driver.find_element(By.ID, fid)
                self._fn_field_id = fid
                return el
            except NoSuchElementException:
                continue

        # 2) try finding via label text
        try:
            label = self.driver.find_element(
                By.XPATH, "//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'first')]"
            )
            for_id = label.get_attribute("for")
            if for_id:
                el = self.driver.find_element(By.ID, for_id)
                self._fn_field_id = for_id
                return el
        except Exception:
            pass

        # 3) fallback: second text input on page (first is Last Name)
        try:
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            for inp in inputs:
                if inp.get_attribute("id") != "SearchLastName":
                    self._fn_field_id = inp.get_attribute("id") or "__positional__"
                    return inp
        except Exception:
            pass

        return None

    def _submit_search(self, last_name: str, prefix: str = "") -> None:
        driver = self.driver
        wait = WebDriverWait(driver, 15)

        if self._first_search:
            self._first_search = False
        else:
            try:
                driver.find_element(By.ID, "btnClearSearch").click()
                wait.until(lambda d: d.find_element(By.ID, "SearchLastName").get_attribute("value") == "")
            except Exception:
                driver.get(CDI_SEARCH_URL)
                self._wait_for_turnstile()

        last_input = wait.until(EC.presence_of_element_located((By.ID, "SearchLastName")))
        last_input.clear()
        last_input.send_keys(last_name)

        # 每次都清 First Name 字段，避免上次的字母前缀残留
        fn_el = self._find_first_name_field()
        if fn_el:
            fn_el.clear()
            if prefix:
                fn_el.send_keys(prefix)

        # Grab a reference to an existing row (if any) so we can detect page refresh
        existing_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        stale_ref = existing_rows[0] if existing_rows else None

        driver.find_element(By.ID, "btnSearch").click()
        try:
            # Wait for old rows to go stale first — prevents reading previous search's data
            if stale_ref:
                WebDriverWait(driver, 10).until(EC.staleness_of(stale_ref))
            WebDriverWait(driver, 15).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".alert, .no-results, #noResults")),
                )
            )
        except TimeoutException:
            time.sleep(2)

    def _is_over_limit(self) -> bool:
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            # Search result pages never contain addresses, so checking both keywords
            # anywhere in the body is safe and matches CDI's over-limit message.
            return "500" in body and "refine" in body.lower()
        except Exception:
            return False

    def _collect_all_pages(self) -> list:
        results = []
        page = 1
        while True:
            results.extend(self._parse_current_page())
            try:
                next_li = self.driver.find_element(
                    By.CSS_SELECTOR, "li.paginate_button.next, li.next"
                )
                if "disabled" in (next_li.get_attribute("class") or ""):
                    break
                next_li.find_element(By.TAG_NAME, "a").click()
                time.sleep(2)
                page += 1
            except Exception:
                break
            if page > 100:
                break
        return results

    def _parse_current_page(self) -> list:
        """
        Columns: Last Name | Middle | First | License# | Status | City | State | Resident
        Also extracts onclick params for detail fetching.
        """
        results = []
        try:
            table = WebDriverWait(self.driver, 10).until(
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
            if self._state_filter != "ALL" and state.upper() != self._state_filter:
                continue

            # Extract onclick params from license number link
            onclick_params = []
            try:
                link = cells[3].find_element(By.TAG_NAME, "a")
                onclick = link.get_attribute("onclick") or ""
                onclick_params = re.findall(r"'([^']+)'", onclick)
            except Exception:
                pass

            licensee = Licensee(
                id=str(uuid.uuid4()),
                first_name=first_name,
                last_name=last_name,
                license_number=license_number,
                license_type="",
                expiration_date="",
                status=status,
                city=city,
                state=state,
                _onclick_params=onclick_params,
            )
            results.append(licensee)

        return results

    # ── Detail page ───────────────────────────────────────────────

    def _fetch_detail_into(self, licensee: Licensee) -> None:
        """
        Submit form1 (target=_self) with license params, extract detail data.
        Tries onclick_params[2] as SearchIndvId first, then [1] as fallback.
        After extraction, navigates back to CDI_SEARCH_URL so form1 is available next time.
        """
        params = licensee._onclick_params
        if not params or len(params) < 3:
            return

        lic_nbr     = params[0]
        search_type = params[3] if len(params) > 3 else "IND"

        for indv_id in [params[2], params[1]]:
            try:
                success = self._post_detail_form(lic_nbr, indv_id, search_type)
                if not success:
                    continue

                body = self.driver.find_element(By.TAG_NAME, "body").text

                if "Unable to retrieve" in body or not body.strip():
                    continue

                # Extract address and phone
                addr  = re.search(r'Business Address:\s*(.+)', body)
                phone = re.search(r'Business Phone:\s*(.+)', body)
                if addr:
                    licensee.business_address = addr.group(1).strip()
                if phone:
                    licensee.business_phone = phone.group(1).strip()

                # Extract license types and expiration from table
                self._extract_license_table(licensee)

                break  # success — stop trying alternate IndvId

            except Exception:
                continue

        # Return browser to search page so next detail fetch can use form1
        try:
            self.driver.get(CDI_SEARCH_URL)
            self._wait_for_turnstile()
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "SearchLastName"))
            )
            self._first_search = True
        except Exception:
            pass

    def _post_detail_form(self, lic_nbr: str, indv_id: str, search_type: str) -> bool:
        """Submit form1 in same tab. Returns True if page changed to LicenseDetail."""
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "form1"))
            )
            self.driver.execute_script("""
                var f = document.getElementById('form1');
                f.target = '_self';
                document.getElementById('SearchLicNbr').value = arguments[0];
                document.getElementById('SearchIndvId').value = arguments[1];
                document.getElementById('SearchType').value   = arguments[2];
                f.submit();
            """, lic_nbr, indv_id, search_type)
            # 等详情页关键元素出现，而不是固定等 2.5 秒
            WebDriverWait(self.driver, 10).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")),
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Business Address')]")),
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Unable to retrieve')]")),
                )
            )
            return CDI_DETAIL_URL in self.driver.current_url
        except Exception:
            return False

    def _extract_license_table(self, licensee: Licensee) -> None:
        """
        Parse the license type table on the detail page.
        Columns: License Type | Original Issue Date | Status | Status Date | Expiration Date
        """
        try:
            tables = self.driver.find_elements(By.CSS_SELECTOR, "table")
            for tbl in tables:
                headers = " ".join(
                    th.text for th in tbl.find_elements(By.TAG_NAME, "th")
                )
                if "License Type" not in headers and "Qualification" not in headers:
                    continue
                types, exps = [], []
                for tr in tbl.find_elements(By.CSS_SELECTOR, "tbody tr"):
                    tds = tr.find_elements(By.TAG_NAME, "td")
                    if len(tds) >= 5:
                        lic_type = tds[0].text.strip()
                        lic_stat = tds[2].text.strip()
                        exp_date = tds[4].text.strip()
                        if lic_stat.lower() == "active" and lic_type:
                            types.append(lic_type)
                            if exp_date:
                                exps.append(exp_date)
                if types:
                    licensee.license_type = ", ".join(types)
                if exps:
                    licensee.expiration_date = exps[0]
                break
        except Exception:
            pass
