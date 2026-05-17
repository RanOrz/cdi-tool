"""
Test CDI License Number search page as alternative to form-POST approach.
Also tests params[2] for SearchIndvId.
"""
import re, time, sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

CDI_URL = "https://cdicloud.insurance.ca.gov/cal/IndividualNameSearch"

opts = uc.ChromeOptions()
opts.add_argument("--window-size=1280,900")
driver = uc.Chrome(options=opts, headless=False)

def wait_turnstile(driver, secs=20):
    try:
        WebDriverWait(driver, secs).until(lambda d: bool(d.execute_script(
            "return document.querySelector('input[name=\"cf-turnstile-response\"]')?.value||''")))
    except TimeoutException:
        pass
    time.sleep(1)

def extract_detail(body):
    addr  = re.search(r'Business Address:\s*(.+)', body)
    phone = re.search(r'Business Phone:\s*(.+)', body)
    return (addr.group(1).strip() if addr else ""), (phone.group(1).strip() if phone else "")

try:
    # ── Search by name, get a license number ──────────────────────
    driver.get(CDI_URL)
    wait_turnstile(driver)
    wait = WebDriverWait(driver, 15)
    inp = wait.until(EC.presence_of_element_located((By.ID,"SearchLastName")))
    inp.send_keys("Liang")
    driver.find_element(By.ID,"btnSearch").click()
    time.sleep(3)

    table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,"table tbody")))
    target_lic = None
    onclick_params = None
    for row in table.find_elements(By.TAG_NAME,"tr"):
        cells = row.find_elements(By.TAG_NAME,"td")
        if len(cells)<7: continue
        if cells[4].text.strip().lower()=="active" and cells[6].text.strip().upper()=="CA":
            links = cells[3].find_elements(By.TAG_NAME,"a")
            if links:
                target_lic = cells[3].text.strip()
                onclick = links[0].get_attribute("onclick") or ""
                onclick_params = re.findall(r"'([^']+)'", onclick)
                print(f"Target license: {target_lic}  |  onclick params: {onclick_params}")
                break

    if not target_lic:
        print("No target found"); sys.exit(1)

    # ── Approach A: License Number search page ────────────────────
    print("\n=== APPROACH A: LicenseNumberSearch ===")
    for path in ["/cal/LicenseNumberSearch", "/cal/LicenseSearch", "/cal/LicenseDetail"]:
        url = f"https://cdicloud.insurance.ca.gov{path}"
        driver.get(url)
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME,"body").text
        print(f"{url} → first 150: {body[:150].replace(chr(10),' ')}")
        if "Business Address" in body:
            print("✓ Found Business Address directly!")
            break

    # Try searching by license number on whatever search page loads
    try:
        fields = driver.find_elements(By.CSS_SELECTOR,"input[type='text'],input[type='search']")
        if fields:
            print(f"Found input field: id={fields[0].get_attribute('id')}")
            fields[0].clear()
            fields[0].send_keys(target_lic)
            btns = driver.find_elements(By.CSS_SELECTOR,"input[type='submit'],button[type='submit'],button#btnSearch")
            if btns:
                btns[0].click()
                time.sleep(3)
                body = driver.find_element(By.TAG_NAME,"body").text
                addr, phone = extract_detail(body)
                print(f"After submit → Address: {addr or 'NOT FOUND'}  Phone: {phone or 'NOT FOUND'}")
                print("BODY SNIPPET:", body[:500])
    except Exception as e:
        print(f"Input/submit error: {e}")

    # ── Approach B: form1 POST with params[2] as SearchIndvId ─────
    print("\n=== APPROACH B: form1 POST params[2] as SearchIndvId ===")
    driver.get(CDI_URL)
    wait_turnstile(driver)
    inp2 = wait.until(EC.presence_of_element_located((By.ID,"SearchLastName")))
    inp2.send_keys("Liang")
    driver.find_element(By.ID,"btnSearch").click()
    time.sleep(3)

    if onclick_params and len(onclick_params)>=3:
        p0 = onclick_params[0]
        p2 = onclick_params[2]
        ptype = onclick_params[3] if len(onclick_params)>3 else 'IND'
        print(f"Submitting: LicNbr={p0}, IndvId={p2}, Type={ptype}")
        driver.execute_script("""
            var f=document.getElementById('form1');
            f.target='_self';
            document.getElementById('SearchLicNbr').value=arguments[0];
            document.getElementById('SearchIndvId').value=arguments[1];
            document.getElementById('SearchType').value=arguments[2];
            f.submit();
        """, p0, p2, ptype)
        time.sleep(3)
        body = driver.find_element(By.TAG_NAME,"body").text
        addr, phone = extract_detail(body)
        print(f"has_error={'Unable to retrieve' in body}")
        print(f"Address: {addr or 'NOT FOUND'}")
        print(f"Phone:   {phone or 'NOT FOUND'}")
        print("PAGE SNIPPET:", body[:600])

        if addr:
            # Test going back via re-search (not driver.back())
            print("\n--- Re-search test after detail ---")
            driver.get(CDI_URL)
            time.sleep(2)
            inp3 = wait.until(EC.presence_of_element_located((By.ID,"SearchLastName")))
            print(f"Re-search available: {bool(inp3)}")

finally:
    time.sleep(3)
    driver.quit()
    print("\nDONE")
