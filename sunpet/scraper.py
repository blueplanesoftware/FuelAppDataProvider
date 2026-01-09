from pathlib import Path
from typing import List, Dict, Set
import random
import time
import re

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError

SUNPET_URL = "https://www.sunpettr.com.tr/yakit-fiyatlari"


def _normalize_city_name_for_filename(city_name: str) -> str:
	"""Normalize city name for filenames (uppercase ASCII-ish)."""
	replacements = {
		"İ": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g",
		"Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c",
		"-": "_", " ": "_",
	}
	n = city_name
	for src, dst in replacements.items():
		n = n.replace(src, dst)
	return re.sub(r"[^A-Z0-9_]", "", n.upper())


def _get_city_options(page: Page, debug: bool = False) -> List[Dict[str, str]]:
	"""Return list of unique city options from the Sunpet dropdown."""
	options_data = page.evaluate("""
		() => {
			const allItems = document.querySelectorAll('.choices__item');
			const results = [];
			for (const el of allItems) {
				const text = (el.innerText || el.textContent || '').trim();
				const value = el.getAttribute('data-value') || '';
				if (text && value && value.startsWith('http') && text !== 'İl Seçiniz') {
					results.push({ text: text, value: value });
				}
			}
			if (results.length === 0) {
				const select = document.querySelector('select.choices__input');
				if (select) {
					for (const opt of select.options) {
						const text = opt.textContent.trim();
						const value = opt.value || opt.getAttribute('data-value') || '';
						if (text && value && value.startsWith('http') && text !== 'İl Seçiniz') {
							results.push({ text: text, value: value });
						}
					}
				}
			}
			return results;
		}
	""")
	
	result: List[Dict[str, str]] = []
	seen_cities: Set[str] = set()
	for opt_data in options_data:
		text = opt_data['text'].strip()
		value = opt_data['value'].strip()
		city_key = re.sub(r"\s+", " ", text.upper()).strip()
		if city_key not in seen_cities:
			seen_cities.add(city_key)
			result.append({"value": value, "text": text})
	return result


def _extract_price_from_cell(cell) -> str:
	"""Extract price from a table cell."""
	try:
		price_span = cell.locator("span b")
		if price_span.count() > 0:
			price_text = price_span.first.inner_text().strip()
			return re.sub(r"[^\d,.]", "", price_text).replace(",", ".")
	except Exception:
		pass
	return ""


def _extract_fuel_prices_from_table(page: Page, debug: bool = False) -> List[Dict[str, str]]:
	"""Extract all fuel prices from the table for all districts."""
	try:
		page.wait_for_selector("table.primary-table", state="visible", timeout=15000)
		page.wait_for_timeout(1000)
	except PWTimeoutError:
		return []

	results: List[Dict[str, str]] = []
	try:
		rows = page.locator("table.primary-table tbody tr")
		for i in range(rows.count()):
			row = rows.nth(i)
			district = (row.locator("td").first.inner_text() or "").strip()
			if not district:
				continue
			cells = row.locator("td")
			if cells.count() < 8:
				continue
			results.append({
				"district": district,
				"benzin_95": _extract_price_from_cell(cells.nth(2)),
				"motorin": _extract_price_from_cell(cells.nth(3)),
				"gazyagi": _extract_price_from_cell(cells.nth(4)),
				"fuel_oil": _extract_price_from_cell(cells.nth(5)),
				"yuksek_kukurtlu_fuel_oil": _extract_price_from_cell(cells.nth(6)),
				"kalorifer_yakiti": _extract_price_from_cell(cells.nth(7)),
			})
	except Exception as e:
		if debug:
			print(f"  Debug: Error extracting prices: {e}")
	return results


def _write_sunpet_prices_to_text(city_name: str, prices: List[Dict[str, str]], output_file: Path, append: bool = False) -> None:
	"""Write fuel prices to txt file in format: DISTRICT: PRICE_TYPE: PRICE."""
	if not prices:
		return

	fuel_types = ["benzin_95", "motorin", "gazyagi", "fuel_oil", "yuksek_kukurtlu_fuel_oil", "kalorifer_yakiti"]
	fuel_labels = ["Kurşunsuz Benzin 95", "Motorin", "Gazyağı", "Fuel Oil", "Yuksek Kukurtlu Fuel Oil", "Kalorifer Yakıtı"]
	
	lines = []
	for price_data in prices:
		parts = [f"{fuel_labels[i]}: {price_data[ft]}" for i, ft in enumerate(fuel_types) if price_data.get(ft)]
		if parts:
			lines.append(f"{price_data['district']}: {', '.join(parts)}")

	if lines:
		content = "\n".join(lines)
		if append and output_file.exists():
			existing = output_file.read_text(encoding="utf-8").strip()
			output_file.write_text(f"{existing}\n{content}" if existing else content, encoding="utf-8")
		else:
			output_file.write_text(content, encoding="utf-8")


def _select_city_and_get_prices(page: Page, city_value: str, city_text: str, debug: bool = False) -> List[Dict[str, str]]:
	"""Navigate to city URL and return extracted prices."""
	try:
		if not city_value.startswith("http"):
			return []
		page.goto(city_value, wait_until="domcontentloaded")
		page.wait_for_timeout(2000)
		try:
			page.wait_for_load_state("networkidle", timeout=10000)
		except Exception:
			page.wait_for_timeout(2000)
		try:
			page.wait_for_selector("#cookieModal", state="visible", timeout=2000)
			page.click("#cookieModal button.btn-apply-all", timeout=1000)
			page.wait_for_timeout(500)
		except Exception:
			pass
		return _extract_fuel_prices_from_table(page, debug=debug)
	except Exception as e:
		if debug:
			print(f"  Error navigating to {city_text}: {e}")
		return []


def save_all_cities_prices_txt(
	output_dir: Path,
	url: str = SUNPET_URL,
	debug: bool = False,
	min_delay: float = 0.8,
	max_delay: float = 1.6,
) -> List[Path]:
	"""
	Tüm şehirler için Sunpet akaryakıt fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: sunpet/sunpet_<ŞEHİR>_prices.txt
	İstanbul (Anadolu ve Avrupa) birleştirilir: sunpet_ISTANBUL_prices.txt
	"""
	output_dir.mkdir(parents=True, exist_ok=True)
	saved_files: List[Path] = []

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

		try:
			page.wait_for_selector("#cookieModal", state="visible", timeout=3000)
			page.click("#cookieModal button.btn-apply-all", timeout=2000)
			page.wait_for_timeout(500)
		except Exception:
			pass

		print("Sunpet: Şehirler listeleniyor...")
		cities = _get_city_options(page, debug=debug)
		print(f"Sunpet: {len(cities)} şehir bulundu (duplikatlar filtrelendi).")

		if not cities:
			if debug:
				page.screenshot(path=str(output_dir / "debug_dropdown.png"))
			browser.close()
			return saved_files

		istanbul_output = output_dir / "sunpet_ISTANBUL_prices.txt"
		istanbul_first = True

		for idx, city in enumerate(cities, 1):
			value = city["value"]
			text = city["text"].strip()
			print(f"\n[{idx}/{len(cities)}] Şehir: {text}")

			prices = _select_city_and_get_prices(page, value, text, debug=debug)
			if not prices:
				print(f"  ⚠ Fiyat alınamadı: {text}")
				continue

			print(f"  {len(prices)} ilçe için fiyat bulundu")

			# Check if this is Istanbul (Anadolu or Avrupa) - combine into single file
			# Normalize Turkish characters for comparison
			normalized = text.upper().replace("İ", "I").replace("ı", "I")
			is_istanbul = "ISTANBUL" in normalized
			
			if is_istanbul:
				_write_sunpet_prices_to_text(text, prices, istanbul_output, append=not istanbul_first)
				if istanbul_first:
					saved_files.append(istanbul_output)
					istanbul_first = False
				print(f"  ✓ Kaydedildi: {istanbul_output.name} (Istanbul birleştirildi)")
			else:
				norm = _normalize_city_name_for_filename(text)
				fp = output_dir / f"sunpet_{norm}_prices.txt"
				_write_sunpet_prices_to_text(text, prices, fp)
				saved_files.append(fp)
				print(f"  ✓ Kaydedildi: {fp.name}")

			time.sleep(random.uniform(min_delay, max_delay))

		browser.close()

	print(f"\nToplam {len(saved_files)} dosya yazıldı -> {output_dir}")
	return saved_files
