from pathlib import Path
from typing import List
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re
import time
import random

ENERJI_URL = "https://www.enerjipetrol.com/tr/past-prices/"


def _normalize_city_name(city_name: str) -> str:
	replacements = {"İ": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g", "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c", "-": "_", " ": "_", "(": "", ")": ""}
	n = city_name.replace("İstanbul (Anadolu)", "ISTANBUL").replace("İstanbul (Avrupa)", "ISTANBUL")
	for src, dst in replacements.items():
		n = n.replace(src, dst)
	return re.sub(r"[^A-Z0-9_]", "", n.upper())


@dataclass
class EnerjiPriceRow:
	district: str
	benzin_95: str
	motorin: str
	highdizel: str
	kalorifer: str
	fuel_oil: str
	yuksek_kukurtlu: str


def _extract_price(text: str) -> str:
	match = re.search(r"(\d+[.,]\d+)", (text or "").strip())
	return match.group(1).replace(",", ".") if match else ""


def _extract_prices_from_table(page) -> List[EnerjiPriceRow]:
	try:
		page.wait_for_selector("table.table-bordered tbody tr", state="visible", timeout=15000)
		page.wait_for_timeout(1500)
	except PWTimeoutError:
		return []

	results = []
	for row in page.locator("table.table-bordered tbody tr").all():
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
				results.append(EnerjiPriceRow(district=district.strip(), benzin_95=prices[0], motorin=prices[1], highdizel=prices[2], kalorifer=prices[3], fuel_oil=prices[4], yuksek_kukurtlu=prices[5]))
		except Exception:
			continue
	return results


def _write_file(city_name: str, prices: List[EnerjiPriceRow], output_file: Path) -> None:
	if not prices:
		return
	labels = ["Kurşunsuz Benzin 95 Oktan", "Motorin", "HighDizel", "Kalorifer Yakıtı", "Fuel Oil", "Yüksek Kükürtlü"]
	lines = []
	for p in prices:
		parts = [f"{labels[i]}: {price}" for i, price in enumerate([p.benzin_95, p.motorin, p.highdizel, p.kalorifer, p.fuel_oil, p.yuksek_kukurtlu]) if price]
		if parts:
			lines.append(f"{p.district}: {', '.join(parts)}")
	if lines:
		output_file.write_text("\n".join(lines), encoding="utf-8")


def _select_latest_date(page):
	date_select = page.locator('select[name="tarih"]')
	if date_select.count() > 0:
		options = date_select.first.evaluate("""s => Array.from(s.options).filter(o => o.value).map(o => ({ value: o.value, text: o.textContent?.trim() }))""")
		if options:
			latest_value = options[0]["value"]
			current = date_select.first.evaluate("el => el.value")
			if current != latest_value:
				date_select.first.select_option(latest_value)
				page.wait_for_timeout(1200)
				try:
					page.wait_for_load_state("networkidle", timeout=10000)
				except Exception:
					page.wait_for_timeout(1500)
			return latest_value
	return None


def _select_city(page, city_value: str):
	city_select = page.locator('select[name="sehir"]').first
	city_select.select_option(city_value)
	page.wait_for_timeout(1000)
	try:
		page.wait_for_selector("table.table-bordered tbody tr", state="visible", timeout=15000)
		page.wait_for_load_state("networkidle", timeout=10000)
	except Exception:
		page.wait_for_timeout(2000)


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
	page.wait_for_timeout(1000)
	return page


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = ENERJI_URL, debug: bool = False) -> Path:
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		_select_latest_date(page)
		city_select = page.locator('select[name="sehir"]')
		if city_select.count() == 0:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = city_select.first.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value && o.value !== '0')""")
		target = next((o for o in options if city_name.upper() in (o.get("text") or "").replace("_", " ").strip().upper() or (o.get("text") or "").replace("_", " ").strip().upper() == city_name.upper()), None)
		if not target:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		_select_city(page, target["value"])
		prices = _extract_prices_from_table(page)
		if not prices:
			raise RuntimeError(f"Fiyat verisi alınamadı: {city_name}")
		output_dir.mkdir(parents=True, exist_ok=True)
		output_file = output_dir / f"enerji_{_normalize_city_name(target['text'])}_prices.txt"
		_write_file(target["text"], prices, output_file)
		browser.close()
		return output_file


def save_all_cities_prices_txt(output_dir: Path, url: str = ENERJI_URL, debug: bool = False, min_delay: float = 0.8, max_delay: float = 1.6) -> List[Path]:
	output_dir.mkdir(parents=True, exist_ok=True)
	saved_files = []
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		city_select = page.locator('select[name="sehir"]')
		if city_select.count() == 0:
			if debug:
				page.screenshot(path=str(output_dir / "debug_no_select.png"))
			browser.close()
			return saved_files
		
		# Select latest date ONCE at the beginning
		print("En son tarih seçiliyor...")
		_select_latest_date(page)
		print("✓ Tarih seçildi")
		
		options = city_select.first.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value && o.value !== '0')""")
		print(f"Enerji: {len(options)} şehir bulundu.")
		
		istanbul_prices: List[EnerjiPriceRow] = []
		
		for idx, opt in enumerate(options, 1):
			city_value, city_text = opt.get("value", "").strip(), (opt.get("text") or "").strip()
			if not city_value or not city_text:
				continue
			is_istanbul = "ISTANBUL" in city_text.upper() or city_value in ["82", "34"]
			print(f"\n[{idx}/{len(options)}] Şehir: {city_text}")
			try:
				# Just select the city - date is already selected
				_select_city(page, city_value)
				prices = _extract_prices_from_table(page)
				if not prices:
					print(f"  ⚠ Fiyat alınamadı: {city_text}")
					continue
				print(f"  {len(prices)} ilçe için fiyat bulundu")
				if is_istanbul:
					istanbul_prices.extend(prices)
					print(f"  → İstanbul birleştirilecek")
				else:
					output_file = output_dir / f"enerji_{_normalize_city_name(city_text)}_prices.txt"
					_write_file(city_text, prices, output_file)
					saved_files.append(output_file)
					print(f"  ✓ Kaydedildi: {output_file.name}")
				time.sleep(random.uniform(min_delay, max_delay))
			except Exception as e:
				print(f"  ✗ Hata: {city_text} -> {e}")
				if debug:
					import traceback
					traceback.print_exc()
		
		if istanbul_prices:
			seen = set()
			unique_prices = []
			for p in istanbul_prices:
				if p.district.upper() not in seen:
					seen.add(p.district.upper())
					unique_prices.append(p)
			output_file = output_dir / "enerji_ISTANBUL_prices.txt"
			_write_file("ISTANBUL", unique_prices, output_file)
			saved_files.append(output_file)
			print(f"\n✓ İstanbul birleştirildi: {output_file.name} ({len(unique_prices)} ilçe)")
		
		browser.close()
	print(f"\nToplam {len(saved_files)} dosya yazıldı -> {output_dir}")
	return saved_files
