from pathlib import Path
from typing import List
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re
import time
import random

TERMO_URL = "https://termopet.com.tr/tr-tr/pompa-fiyatlari"


def _normalize_city_name(city_name: str) -> str:
	replacements = {"İ": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g", "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c", "-": "_", " ": "_"}
	n = city_name
	for src, dst in replacements.items():
		n = n.replace(src, dst)
	return re.sub(r"[^A-Z0-9_]", "", n.upper())


@dataclass
class TermoPriceRow:
	district: str
	benzin_95: str
	motorin: str
	motorin_xtr: str
	gazyagi: str
	fuel_oil3: str
	kalorifer_yakiti: str
	lpg: str


def _extract_price(text: str) -> str:
	match = re.search(r"(\d+[.,]\d+)", (text or "").strip())
	return match.group(1).replace(",", ".") if match else ""


def _select_city_select2(page, city_value: str):
	# Select2: try native select_option first, then use JS to trigger Select2
	city_select = page.locator('select[name="city"]').first
	try:
		city_select.select_option(city_value)
	except Exception:
		# Fallback: use JS to set value and trigger Select2
		city_select.evaluate("""(el, val) => {
			el.value = val;
			if (window.$ && window.$(el).data('select2')) {
				window.$(el).val(val).trigger('change');
			} else {
				el.dispatchEvent(new Event('change', { bubbles: true }));
			}
		}""", city_value)
	page.wait_for_timeout(2000)
	# Wait for district dropdown to be populated (has more than just "Seçiniz: İlçe")
	try:
		page.wait_for_function("""() => {
			const select = document.querySelector('select[name="district"]');
			if (!select) return false;
			const options = Array.from(select.options).filter(o => o.value && o.value !== '');
			return options.length > 0;
		}""", timeout=12000)
	except Exception:
		page.wait_for_timeout(3000)


def _get_district_options(page) -> List[dict]:
	district_select = page.locator('select[name="district"]').first
	options = district_select.evaluate("""s => Array.from(s.options).filter(o => o.value && o.value !== '').map(o => ({ value: o.value, text: o.textContent?.trim() }))""")
	return options if options else []


def _select_district_select2(page, district_value: str):
	district_select = page.locator('select[name="district"]').first
	try:
		district_select.select_option(district_value)
	except Exception:
		# Fallback: use JS to set value and trigger Select2
		district_select.evaluate("""(el, val) => {
			el.value = val;
			if (window.$ && window.$(el).data('select2')) {
				window.$(el).val(val).trigger('change');
			} else {
				el.dispatchEvent(new Event('change', { bubbles: true }));
			}
		}""", district_value)
	page.wait_for_timeout(800)


def _click_submit_button(page):
	submit_btn = page.locator('button.btn-submit-form').first
	submit_btn.click()
	page.wait_for_timeout(1500)
	try:
		page.wait_for_selector('#pricesTable tbody#dataRows tr', state="visible", timeout=15000)
		page.wait_for_load_state("networkidle", timeout=10000)
	except Exception:
		page.wait_for_timeout(2000)


def _extract_prices_from_table(page) -> TermoPriceRow:
	try:
		page.wait_for_selector('#pricesTable tbody#dataRows tr', state="visible", timeout=10000)
		page.wait_for_timeout(800)
	except PWTimeoutError:
		return None
	
	try:
		row = page.locator('#pricesTable tbody#dataRows tr').first
		if row.count() == 0:
			return None
		cells = row.locator('td')
		if cells.count() < 7:
			return None
		
		cell_text = lambda i: (cells.nth(i).inner_text() or "").strip()
		prices = [_extract_price(cell_text(i)) for i in range(7)]
		
		# District name will be set by caller from the selected option
		return TermoPriceRow(
			district="",  # Will be set by caller
			benzin_95=prices[0],
			motorin=prices[1],
			motorin_xtr=prices[2],
			gazyagi=prices[3],
			fuel_oil3=prices[4],
			kalorifer_yakiti=prices[5],
			lpg=prices[6]
		)
	except Exception as e:
		return None


def _write_file(city_name: str, prices: List[TermoPriceRow], output_file: Path) -> None:
	if not prices:
		return
	labels = ["K. Benzin (95 Oktan)", "Motorin", "Motorin XTR", "Gazyağı", "Fuel Oil3", "Kalorifer Yakıtı", "LPG"]
	lines = []
	for p in prices:
		parts = [f"{labels[i]}: {price}" for i, price in enumerate([p.benzin_95, p.motorin, p.motorin_xtr, p.gazyagi, p.fuel_oil3, p.kalorifer_yakiti, p.lpg]) if price]
		if parts:
			lines.append(f"{p.district}: {', '.join(parts)}")
	if lines:
		output_file.write_text("\n".join(lines), encoding="utf-8")


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
	page.wait_for_timeout(2000)  # Wait for Select2 to initialize
	return page


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = TERMO_URL, debug: bool = False) -> Path:
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		
		# Get city options
		city_select = page.locator('select[name="city"]')
		if city_select.count() == 0:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = city_select.first.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value && o.value !== '')""")
		target = next((o for o in options if city_name.upper() in (o.get("text") or "").strip().upper() or (o.get("text") or "").strip().upper() == city_name.upper()), None)
		if not target:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		
		# Select city
		_select_city_select2(page, target["value"])
		
		# Get all districts for this city
		district_options = _get_district_options(page)
		if not district_options:
			raise RuntimeError(f"İlçe seçenekleri bulunamadı: {city_name}")
		
		# Collect prices for all districts
		all_prices: List[TermoPriceRow] = []
		for dist_opt in district_options:
			dist_value, dist_text = dist_opt.get("value", ""), (dist_opt.get("text") or "").strip()
			if not dist_value or not dist_text:
				continue
			try:
				_select_district_select2(page, dist_value)
				_click_submit_button(page)
				price_row = _extract_prices_from_table(page)
				if price_row:
					price_row.district = dist_text  # Use district text from option
					all_prices.append(price_row)
			except Exception as e:
				if debug:
					print(f"  ⚠ İlçe hatası {dist_text}: {e}")
				continue
		
		if not all_prices:
			raise RuntimeError(f"Fiyat verisi alınamadı: {city_name}")
		
		output_dir.mkdir(parents=True, exist_ok=True)
		output_file = output_dir / f"termo_{_normalize_city_name(target['text'])}_prices.txt"
		_write_file(target["text"], all_prices, output_file)
		browser.close()
		return output_file


def save_all_cities_prices_txt(output_dir: Path, url: str = TERMO_URL, debug: bool = False, min_delay: float = 1.0, max_delay: float = 2.0) -> List[Path]:
	output_dir.mkdir(parents=True, exist_ok=True)
	saved_files = []
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		page = _init_page(browser, url)
		
		# Get all city options
		city_select = page.locator('select[name="city"]')
		if city_select.count() == 0:
			if debug:
				page.screenshot(path=str(output_dir / "debug_no_select.png"))
			browser.close()
			return saved_files
		
		options = city_select.first.evaluate("""s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value && o.value !== '')""")
		print(f"Termo: {len(options)} şehir bulundu.")
		
		for idx, opt in enumerate(options, 1):
			city_value, city_text = opt.get("value", "").strip(), (opt.get("text") or "").strip()
			if not city_value or not city_text:
				continue
			print(f"\n[{idx}/{len(options)}] Şehir: {city_text}")
			try:
				# Reload page for each city to ensure clean state
				page.goto(url, wait_until="domcontentloaded")
				try:
					page.wait_for_load_state("networkidle", timeout=8000)
				except Exception:
					pass
				page.wait_for_timeout(2000)
				
				# Select city
				_select_city_select2(page, city_value)
				
				# Get all districts for this city
				district_options = _get_district_options(page)
				if not district_options:
					print(f"  ⚠ İlçe seçenekleri bulunamadı: {city_text}")
					continue
				
				print(f"  {len(district_options)} ilçe bulundu")
				
				# Collect prices for all districts
				all_prices: List[TermoPriceRow] = []
				for dist_idx, dist_opt in enumerate(district_options, 1):
					dist_value, dist_text = dist_opt.get("value", ""), (dist_opt.get("text") or "").strip()
					if not dist_value or not dist_text:
						continue
					try:
						if debug:
							print(f"    [{dist_idx}/{len(district_options)}] İlçe: {dist_text}")
						
						# Verify/reselect city if needed (form submission might reset it)
						current_city = page.locator('select[name="city"]').first.evaluate("el => el.value")
						if current_city != city_value:
							_select_city_select2(page, city_value)
						
						_select_district_select2(page, dist_value)
						_click_submit_button(page)
						price_row = _extract_prices_from_table(page)
						if price_row:
							price_row.district = dist_text
							all_prices.append(price_row)
							if debug:
								print(f"      ✓ Fiyat alındı: {dist_text}")
						time.sleep(random.uniform(0.5, 1.0))
					except Exception as e:
						if debug:
							print(f"      ⚠ İlçe hatası {dist_text}: {e}")
							import traceback
							traceback.print_exc()
						continue
				
				if not all_prices:
					print(f"  ⚠ Fiyat alınamadı: {city_text}")
					continue
				
				print(f"  ✓ {len(all_prices)} ilçe için fiyat toplandı")
				output_file = output_dir / f"termo_{_normalize_city_name(city_text)}_prices.txt"
				_write_file(city_text, all_prices, output_file)
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
