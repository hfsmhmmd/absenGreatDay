import json
import os

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")

BASE_URL = "https://app.greatdayhr.com/"
LOGIN_SUCCESS_URL_PART = "features/home"

AGREE_CHECKBOX_JS = """
() => {
  const labels = document.querySelectorAll('ion-label');
  for (const label of labels) {
    if (!(label.textContent || '').includes('I agree')) continue;
    const box = label.parentElement && label.parentElement.querySelector('ion-checkbox');
    if (box) {
      if (!box.checked) box.click();
      return true;
    }
  }
  return false;
}
"""


def load_config():
    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
    for key in ("url", "username", "password", "company"):
        env_value = os.getenv(f"GDHR_{key.upper()}", "").strip()
        if env_value:
            config[key] = env_value
    config.setdefault("headless", True)
    if os.getenv("HEADLESS"):
        config["headless"] = os.getenv("HEADLESS").lower() not in ("0", "false")
    return config


def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"[screenshot] {path}")


def tunggu_url(page, part, timeout_ms=30000):
    langkah = 500
    for _ in range(int(timeout_ms / langkah)):
        if part in page.url:
            return
        toast = page.evaluate(
            "() => { const el = document.querySelector('ion-toast, ion-alert'); return el ? el.textContent : null; }"
        )
        if toast:
            raise RuntimeError(f"login gagal: {toast[:200]}")
        page.wait_for_timeout(langkah)
    raise PlaywrightTimeoutError(f"navigasi ke '{part}' tidak terjadi (url saat ini: {page.url})")


def login(page, config):
    print("[1/5] buka halaman login")
    page.goto(config.get("url", BASE_URL), wait_until="domcontentloaded")
    page.wait_for_selector("input[placeholder='Enter Username']")

    print("[2/5] isi username & password")
    page.fill("input[placeholder='Enter Username']", config["username"])
    page.fill("input[placeholder='Enter Password']", config["password"])

    print("[3/5] pilih company")
    search = page.get_by_role("searchbox")
    search.wait_for(state="visible", timeout=15000)
    search.fill(config["company"])
    opsi = page.get_by_text(config["company"], exact=True).first
    opsi.wait_for(state="visible", timeout=15000)
    opsi.click()
    page.wait_for_timeout(500)

    print("[4/5] centang agree checkbox")
    checked = page.evaluate(AGREE_CHECKBOX_JS)
    if not checked:
        raise RuntimeError("checkbox 'I agree' tidak ditemukan")
    page.wait_for_timeout(500)
    agree = page.locator("ion-checkbox[aria-checked='false']")
    if agree.count() > 1:
        raise RuntimeError("checkbox 'I agree' gagal tercentang")
    screenshot(page, "sebelum-login")

    print("[5/5] klik Login")
    login_btn = page.get_by_role("button", name="Login", exact=True).first
    login_btn.evaluate("el => el.click()")
    tunggu_url(page, LOGIN_SUCCESS_URL_PART)
    page.wait_for_load_state("networkidle")
    screenshot(page, "setelah-login")
    print(f"[ok] login berhasil: {page.url}")


def dump_modal(page):
    modal_html = page.evaluate(
        """() => {
      const modal = document.querySelector('ion-modal');
      if (!modal) return 'TIDAK ADA MODAL';
      const klik = [];
      modal.querySelectorAll('*').forEach(el => {
        if (el.hasAttribute('onclick') || el.getAttribute('role') === 'button' || ['BUTTON', 'ION-BUTTON', 'ION-FAB-BUTTON', 'ION-ICON', 'A'].includes(el.tagName)) {
          klik.push({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 60), icon: el.getAttribute && el.getAttribute('name'), text: (el.textContent || '').trim().slice(0, 30) });
        }
      });
      return { shadow: !!modal.shadowRoot, klik };
    }"""
    )
    print("[modal]", json.dumps(modal_html, ensure_ascii=False, indent=1)[:2000])


def aksi_setelah_login(page, config):
    print("[aksi] klik tombol Record Time")
    page.locator("ion-button", has_text="Record Time").first.click()
    page.wait_for_timeout(3000)

    print("[aksi] klik tombol kamera (btn-capture) di modal")
    page.wait_for_selector("video", timeout=15000)
    print("[aksi] kamera aktif, mengambil foto...")
    page.locator("button.btn-capture").first.click()
    page.wait_for_timeout(3000)

    print("[aksi] klik tombol Save Attendance")
    page.locator("ion-button", has_text="Save Attendance").first.click()

    for _ in range(24):
        page.wait_for_timeout(5000)
        sukses = page.evaluate("() => (document.body.innerText || '').includes('successfully recorded')")
        if sukses:
            print("[ok] absensi tercatat: 'successfully recorded'")
            break
    else:
        print("[peringatan] konfirmasi absen tidak terdeteksi setelah 2 menit")

    dump_state(page, "record-time")
    screenshot(page, "record-time")


def dump_state(page, label):
    state = page.evaluate(
        """() => ({
      url: location.href,
      buttons: Array.from(document.querySelectorAll('ion-button, button')).map(b => b.textContent.trim()).filter(t => t).slice(0, 30),
      videos: Array.from(document.querySelectorAll('video')).map(v => ({ w: v.videoWidth, h: v.videoHeight, playing: !v.paused })),
      canvases: document.querySelectorAll('canvas').length,
      modals: Array.from(document.querySelectorAll('ion-modal')).map(m => (m.textContent || '').trim().slice(0, 300)),
      bodyText: (document.body.innerText || '').replace(/\\n{2,}/g, ' | ').slice(0, 600),
    })"""
    )
    path = os.path.join(SCREENSHOT_DIR, f"state-{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print(f"[state] {path}")
    print(json.dumps(state, ensure_ascii=False, indent=1)[:1500])


def main():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    config = load_config()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config["headless"])
        geo = config.get("lokasi")
        if geo:
            context = browser.new_context(
                geolocation={
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "accuracy": geo.get("accuracy", 10),
                },
                permissions=["geolocation", "camera"],
                locale="id-ID",
                timezone_id="Asia/Jakarta",
            )
            print(f"[lokasi] GPS diset ke {geo['latitude']}, {geo['longitude']}")
        else:
            context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            login(page, config)
            aksi_setelah_login(page, config)
        except PlaywrightTimeoutError as e:
            screenshot(page, "error")
            raise SystemExit(f"[gagal] timeout: {e}")
        finally:
                if not config["headless"] and config.get("keep_open", True):
                    try:
                        input("\n[browser tetap terbuka] Tekan Enter di terminal ini untuk menutup browser... ")
                    except EOFError:
                        print("\n[browser tetap terbuka] Tanpa TTY: browser ditahan 30 menit (hentikan proses untuk menutup).")
                        page.wait_for_timeout(30 * 60 * 1000)
                screenshot(page, "final")
                browser.close()


if __name__ == "__main__":
    main()
