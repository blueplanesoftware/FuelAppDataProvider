from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random

PARKOIL_URL = "https://www.parkoil.com.tr/akaryakit-fiyatlar%C4%B1.html"


def _ensure_cookie_accepted(page) -> None:
	try:
		# Common OneTrust accept button (if present)
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _get_city_select(page):
	sel = page.locator("#citySelect")
	return sel if sel.count() > 0 else None


def _get_city_options(page) -> List[Dict[str, str]]:
	sel = _get_city_select(page)
	if sel is None:
		return []
	return sel.evaluate(
		"s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() }))"
	)


def _select_city(page, city_name: str) -> None:
	sel = _get_city_select(page)
	if sel is None:
		raise RuntimeError("Şehir seçimi için #citySelect bulunamadı.")
	# Prefer native select_option by label and value
	try:
		sel.select_option(label=city_name)
		return
	except Exception:
		pass
	try:
		sel.select_option(value=city_name)
		return
	except Exception:
		pass
	# Fallback: set value via JS and dispatch events
	sel.evaluate(
		"(el, val)=>{ el.value = val; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }",
		city_name,
	)


@dataclass
class ParkoilDistrictRow:
	name: str
	benzin: str
	motorin: str


def _wait_prices_loaded(page, timeout_ms: int = 12000) -> None:
	# Wait for the table body with rows to appear and stabilize
	page.wait_for_selector("tbody#parent tr", timeout=timeout_ms)
	page.wait_for_load_state("networkidle")
	# small grace period to allow JS formatting
	page.wait_for_timeout(300)


def _extract_district_rows(page) -> List[ParkoilDistrictRow]:
	rows = page.locator("tbody#parent tr")
	rc = rows.count()
	results: List[ParkoilDistrictRow] = []
	for i in range(rc):
		tr = rows.nth(i)
		tds = tr.locator("td")
		if tds.count() < 3:
			continue
		try:
			name = tds.nth(0).inner_text().strip()
		except Exception:
			name = ""
		try:
			benzin = tds.nth(1).inner_text().strip()
		except Exception:
			benzin = ""
		try:
			motorin = tds.nth(2).inner_text().strip()
		except Exception:
			motorin = ""
		# Skip empty placeholders
		if not name:
			continue
		results.append(ParkoilDistrictRow(name=name, benzin=benzin, motorin=motorin))
	return results


def _write_parkoil_districts_to_text(city_name: str, districts: List[ParkoilDistrictRow], output_file: Path) -> None:
	lines: List[str] = []
	# First line city name (mirrors other brand outputs)
	lines.append(f"{city_name}")
	for d in districts:
		lines.append(f"{d.name} | Benzin: {d.benzin} | Motorin: {d.motorin}")
	output_file.write_text("\n".join(lines), encoding="utf-8")


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = PARKOIL_URL, debug: bool = False) -> Path:
	"""
	Parkoil sayfasını aç, şehir seç, ilçe satırlarını çıkar ve txt olarak yaz.
	Çıktı dosyası: parkoil_<ŞEHİR>_prices.txt
	"""
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		context = browser.new_context(
			user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			locale="tr-TR",
			timezone_id="Europe/Istanbul",
			viewport={"width": 1280, "height": 900},
			ignore_https_errors=True,
		)
		page = context.new_page()
		page.set_default_navigation_timeout(45000)
		page.goto(url, wait_until="domcontentloaded")
		try:
			page.wait_for_load_state("networkidle", timeout=8000)
		except Exception:
			pass
		_ensure_cookie_accepted(page)
		# Ensure controls are visible
		page.wait_for_selector("#citySelect", state="visible", timeout=15000)
		# Select city and wait for prices
		_select_city(page, city_name)
		_wait_prices_loaded(page, timeout_ms=15000)
		# Extract and write
		districts = _extract_district_rows(page)
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"parkoil_{city_name}_prices.txt"
		_write_parkoil_districts_to_text(city_name, districts, fp)
		browser.close()
		return fp


def save_all_cities_prices_txt(
	output_dir: Path,
	url: str = PARKOIL_URL,
	debug: bool = False,
	min_delay: float = 0.6,
	max_delay: float = 1.2,
	retries: int = 1,
) -> List[Path]:
	"""
	Tüm şehirler için #citySelect içindeki seçenekleri sıra ile seçip
	ilçelerin fiyatlarını txt olarak yazar.
	"""
	saved: List[Path] = []
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		context = browser.new_context(
			user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			locale="tr-TR",
			timezone_id="Europe/Istanbul",
			viewport={"width": 1280, "height": 900},
			ignore_https_errors=True,
		)
		page = context.new_page()
		page.set_default_navigation_timeout(45000)
		page.goto(url, wait_until="domcontentloaded")
		try:
			page.wait_for_load_state("networkidle", timeout=8000)
		except Exception:
			pass
		_ensure_cookie_accepted(page)
		output_dir.mkdir(parents=True, exist_ok=True)
		page.wait_for_selector("#citySelect", state="visible", timeout=15000)
		options = _get_city_options(page)
		# Filter out the "Tüm İller" empty option
		city_options = [o for o in options if (o.get("value") or "").strip()]
		for o in city_options:
			city_name = (o.get("text") or "").strip() or (o.get("value") or "").strip()
			for attempt in range(retries + 1):
				try:
					_select_city(page, city_name)
					_wait_prices_loaded(page, timeout_ms=15000)
					districts = _extract_district_rows(page)
					fp = output_dir / f"parkoil_{city_name}_prices.txt"
					_write_parkoil_districts_to_text(city_name, districts, fp)
					saved.append(fp)
					print(f"OK: {city_name} -> {fp.name}")
					break
				except PWTimeoutError:
					if attempt < retries:
						page.wait_for_timeout(int(700 * (attempt + 1) * random.uniform(1.0, 1.5)))
						continue
					else:
						print(f"Atlandı (timeout): {city_name}")
				except Exception as e:
					if attempt < retries:
						page.wait_for_timeout(int(600 * (attempt + 1) * random.uniform(1.0, 1.4)))
						continue
					else:
						print(f"Hata/atlandı: {city_name} -> {e}")
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		browser.close()
	return saved


