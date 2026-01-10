from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re
import time
import random

ALPET_URL = "https://www.alpet.com.tr/tr-TR/akaryakit-fiyatlari"


def _ensure_cookie_accepted(page) -> None:
	try:
		btn = page.locator('a.cc-btn.cc-dismiss, .cc-dismiss')
		if btn.count() > 0 and btn.first.is_visible():
			btn.first.click(timeout=2000)
			page.wait_for_timeout(500)
	except Exception:
		pass


def _normalize_city_name(city_name: str) -> str:
	replacements = {"İ": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g", "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c", "-": "_", " ": "_"}
	n = city_name
	for src, dst in replacements.items():
		n = n.replace(src, dst)
	return re.sub(r"[^A-Z0-9_]", "", n.upper())


def _get_city_select(page):
	sel = page.locator('select[name="city"]')
	if sel.count() > 0:
		return sel.first
	for s in page.locator("select").all():
		try:
			opts = s.evaluate("el => Array.from(el.options).map(o => o.textContent?.trim())")
			if opts and len(opts) >= 20 and any(x and x.upper() in ["ADANA", "ANKARA", "ISTANBUL", "İSTANBUL"] for x in opts):
				return s
		except Exception:
			continue
	return None


@dataclass
class AlpetPriceRow:
	district: str
	motorin: str
	motorin_perf: str
	benzin_95: str
	fuel_oil_4: str
	fuel_oil_3: str
	fuel_oil_6: str


def _extract_price(text: str) -> str:
	match = re.search(r"(\d+[.,]\d+)", (text or "").replace("TL/LT", "").strip())
	return match.group(1).replace(",", ".") if match else ""


def _extract_prices_from_table(page) -> List[AlpetPriceRow]:
	try:
		page.wait_for_selector("table.prices tbody tr", state="visible", timeout=15000)
		page.wait_for_timeout(1500)
	except PWTimeoutError:
		return []

	results = []
	for row in page.locator("table.prices tbody tr").all():
		cells = row.locator("td")
		if cells.count() < 8:
			continue
		try:
			cell_text = lambda i: (cells.nth(i).inner_text() or "").strip()
			city, district = cell_text(0), cell_text(1)
			if not city or not district or city.upper() in ["ŞEHİR", "CITY"] or district.upper() in ["İLÇE", "ILCE", "DISTRICT"]:
				continue
			prices = [_extract_price(cell_text(i)) for i in range(2, 8)]
			if any(prices):
				results.append(AlpetPriceRow(district=district.strip(), motorin=prices[0], motorin_perf=prices[1], benzin_95=prices[2], fuel_oil_4=prices[3], fuel_oil_3=prices[4], fuel_oil_6=prices[5]))
		except Exception:
			continue
	return results


def _write_file(city_name: str, prices: List[AlpetPriceRow], output_file: Path) -> None:
	if not prices:
		return
	labels = ["Motorin", "Motorin Performans +", "95 Oktan Kurşunsuz", "Fuel Oil 4", "Fuel Oil 3", "Fuel Oil 6(Yüksek kükürt)"]
	lines = []
	for p in prices:
		parts = [f"{labels[i]}: {price}" for i, price in enumerate([p.motorin, p.motorin_perf, p.benzin_95, p.fuel_oil_4, p.fuel_oil_3, p.fuel_oil_6]) if price]
		if parts:
			lines.append(f"{p.district}: {', '.join(parts)}")
	if lines:
		output_file.write_text("\n".join(lines), encoding="utf-8")


def _select_and_get_prices(page, select_handle, city_value: str) -> List[AlpetPriceRow]:
	try:
		select_handle.select_option(city_value)
		page.wait_for_timeout(500)
		btn = page.locator('button[type="submit"], button.btn-success')
		if btn.count() > 0:
			btn.first.click()
		else:
			select_handle.press("Enter")
		try:
			page.wait_for_selector("table.prices tbody tr", state="visible", timeout=15000)
			page.wait_for_load_state("networkidle", timeout=10000)
		except Exception:
			page.wait_for_timeout(2000)
		return _extract_prices_from_table(page)
	except Exception:
		return []


def _init_page(browser, url: str):
	context = browser.new_context(
		user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
	page.wait_for_timeout(1000)
	return page


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = ALPET_URL, debug: bool = False) -> Path:
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		city_select = _get_city_select(page)
		if not city_select:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = city_select.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value)""")
		target = next((o for o in options if (o.get("text") or "").strip().upper() == city_name.upper() or city_name.upper() in (o.get("text") or "").strip().upper()), None)
		if not target:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		prices = _select_and_get_prices(page, city_select, target["value"])
		if not prices:
			raise RuntimeError(f"Fiyat verisi alınamadı: {city_name}")
		output_dir.mkdir(parents=True, exist_ok=True)
		output_file = output_dir / f"alpet_{_normalize_city_name(city_name)}_prices.txt"
		_write_file(city_name, prices, output_file)
		browser.close()
		return output_file


def save_all_cities_prices_txt(output_dir: Path, url: str = ALPET_URL, debug: bool = False, min_delay: float = 0.8, max_delay: float = 1.6) -> List[Path]:
	output_dir.mkdir(parents=True, exist_ok=True)
	saved_files = []
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		city_select = _get_city_select(page)
		if not city_select:
			if debug:
				page.screenshot(path=str(output_dir / "debug_no_select.png"))
			browser.close()
			return saved_files
		options = city_select.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value && o.text !== 'Tüm Şehirler')""")
		print(f"Alpet: {len(options)} şehir bulundu.")
		for idx, opt in enumerate(options, 1):
			city_value, city_text = opt.get("value", "").strip(), (opt.get("text") or "").strip()
			if not city_value or not city_text:
				continue
			print(f"\n[{idx}/{len(options)}] Şehir: {city_text}")
			try:
				page.goto(url, wait_until="domcontentloaded")
				try:
					page.wait_for_load_state("networkidle", timeout=8000)
				except Exception:
					pass
				_ensure_cookie_accepted(page)
				page.wait_for_timeout(1000)
				city_select = _get_city_select(page)
				if not city_select:
					print(f"  ⚠ Select bulunamadı: {city_text}")
					continue
				prices = _select_and_get_prices(page, city_select, city_value)
				if not prices:
					print(f"  ⚠ Fiyat alınamadı: {city_text}")
					continue
				print(f"  {len(prices)} ilçe için fiyat bulundu")
				output_file = output_dir / f"alpet_{_normalize_city_name(city_text)}_prices.txt"
				_write_file(city_text, prices, output_file)
				saved_files.append(output_file)
				print(f"  ✓ Kaydedildi: {output_file.name}")
				time.sleep(random.uniform(min_delay, max_delay))
			except Exception as e:
				print(f"  ✗ Hata: {city_text} -> {e}")
				if debug:
					import traceback
					traceback.print_exc()
		browser.close()
	print(f"\nToplam {len(saved_files)} dosya yazıldı -> {output_dir}")
	return saved_files
