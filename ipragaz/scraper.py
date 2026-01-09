from pathlib import Path
from typing import List, Dict
import random
import time
import re

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError

IPRAGAZ_URL = "https://www.ipragaz.com.tr/yolda/pompa-fiyatlari"


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


def _map_city_name_for_display(city_name: str) -> str:
	"""Map city names for display (e.g., İçel -> Mersin)."""
	return "Mersin" if city_name.upper() in ("İÇEL", "ICEL") else city_name


def _write_ipragaz_price_to_text(city_label: str, price: str, output_file: Path, append: bool = False) -> None:
	"""Write one line 'CITY: PRICE' to txt, optionally appending."""
	if not price:
		return
	line = f"{city_label}: {price}"
	if append and output_file.exists():
		existing = output_file.read_text(encoding="utf-8").strip()
		output_file.write_text(f"{existing}\n{line}" if existing else line, encoding="utf-8")
	else:
		output_file.write_text(line, encoding="utf-8")


def _click_manual_button(page: Page) -> None:
	"""Click the 'İlinizi yazın' button to reveal city selection."""
	page.wait_for_selector("#type-manually", state="visible", timeout=15000)
	page.click("#type-manually")
	page.wait_for_timeout(500)


def _open_city_dropdown(page: Page) -> None:
	"""Click the dropdown button to show city list."""
	try:
		page.locator("#province").click(timeout=2000)
	except Exception:
		pass
	page.wait_for_timeout(200)
	page.wait_for_selector("#pricefinder button[data-search]", state="visible", timeout=10000)
	page.click("#pricefinder button[data-search]")
	page.wait_for_selector("#provinceautocomplete-list", state="visible", timeout=5000)
	page.wait_for_timeout(500)


def _get_city_options(page: Page, debug: bool = False) -> List[Dict[str, str]]:
	"""Return list of city options from the Ipragaz dropdown."""
	try:
		page.wait_for_selector("#provinceautocomplete-list", state="visible", timeout=10000)
	except PWTimeoutError:
		_open_city_dropdown(page)
		page.wait_for_selector("#provinceautocomplete-list", state="visible", timeout=5000)

	options_locator = page.locator("#provinceautocomplete-list > div")
	if options_locator.count() == 0:
		options_locator = page.locator("#provinceautocomplete-list div")

	result: List[Dict[str, str]] = []
	for i in range(options_locator.count()):
		opt = options_locator.nth(i)
		hidden_input = opt.locator("input[type='hidden']")
		if hidden_input.count() == 0:
			continue
		value = (hidden_input.get_attribute("value") or "").strip()
		text = (opt.inner_text() or "").strip()
		if value and text:
			result.append({"value": value, "text": text})
	return result


def _click_back_button(page: Page, debug: bool = False) -> None:
	"""Click the 'Geri' (Back) button to return to city selection."""
	clicked = page.evaluate("""
		() => {
			const selectors = ['button.price-finder__back', '.price-finder__back', 
				'button[class*="back"]', 'a[class*="back"]'];
			for (const sel of selectors) {
				const el = document.querySelector(sel);
				if (el) { el.click(); return true; }
			}
			const buttons = Array.from(document.querySelectorAll('button, a'));
			for (const btn of buttons) {
				const text = (btn.innerText || '').trim().toUpperCase();
				if (text.includes('GERI') || text.includes('BACK') || text.includes('←')) {
					btn.click(); return true;
				}
			}
			return false;
		}
	""")
	if not clicked:
		raise Exception("Could not find or click the back button")
	# Wait for page to transition back to city selection
	page.wait_for_timeout(1000)
	# Check if dropdown is available (more reliable than waiting for hidden button)
	try:
		page.wait_for_selector("#province", timeout=5000)
	except PWTimeoutError:
		# If province input not found, that's okay - page might still be transitioning
		pass


def _extract_price_from_page(page: Page) -> str:
	"""Extract numeric price from the price element."""
	try:
		page.wait_for_selector("#lblAutogasPriceResult", state="visible", timeout=10000)
		raw = page.locator("#lblAutogasPriceResult").first.inner_text().strip()
	except PWTimeoutError:
		page.wait_for_selector(".price-finder__result__autogas__text", state="visible", timeout=5000)
		raw = page.locator(".price-finder__result__autogas__text").first.inner_text().strip()
	
	raw_clean = raw.replace("₺", "").replace("/litre", "").strip()
	raw_normalized = raw_clean.replace(".", "").replace(",", ".") if "," in raw_clean and raw_clean.count(",") == 1 else raw_clean
	m = re.search(r"(\d+[.,]?\d*)", raw_normalized)
	return m.group(1).replace(",", ".") if m else raw_clean.strip()


def _select_city_and_get_price(page: Page, city_value: str, city_text: str, debug: bool = False) -> str:
	"""Select city by clicking the dropdown option and return extracted price string."""
	try:
		try:
			page.wait_for_selector("#provinceautocomplete-list", state="visible", timeout=2000)
		except PWTimeoutError:
			_open_city_dropdown(page)

		options = page.query_selector_all("#provinceautocomplete-list > div")
		for opt in options:
			hidden_input = opt.query_selector("input[type='hidden']")
			if hidden_input and (hidden_input.get_attribute("value") or "").strip() == city_value:
				opt.click()
				break
		else:
			return ""

		page.wait_for_timeout(2000)
		try:
			page.wait_for_load_state("networkidle", timeout=8000)
		except Exception:
			page.wait_for_timeout(1000)
		page.wait_for_timeout(1000)

		return _extract_price_from_page(page)
	except Exception as e:
		if debug:
			print(f"  Error selecting {city_text}: {e}")
		return ""


def save_all_cities_prices_txt(
	output_dir: Path,
	url: str = IPRAGAZ_URL,
	debug: bool = False,
	min_delay: float = 0.8,
	max_delay: float = 1.6,
) -> List[Path]:
	"""
	Tüm şehirler için Ipragaz Otogaz fiyatlarını çekip txt dosyalarına yazar.

	Çıktılar: ipragaz/ipragaz_<ŞEHİR>_prices.txt
	İstanbul (Adalar, Marmara, Trakya) birleştirilir: ipragaz_ISTANBUL_prices.txt
	Çanakkale (Çanakkale, Çanakkale-B.G. Ada) birleştirilir: ipragaz_CANAKKALE_prices.txt
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

		print("Ipragaz: 'İlinizi yazın' butonuna tıklanıyor...")
		_click_manual_button(page)
		print("✓ Buton tıklandı, dropdown açılıyor...")
		_open_city_dropdown(page)
		print("✓ Dropdown açıldı, şehirler listeleniyor...")

		cities = _get_city_options(page, debug=debug)
		print(f"Ipragaz: {len(cities)} şehir bulundu.")
		
		if not cities:
			if debug:
				page.screenshot(path=str(output_dir / "debug_dropdown.png"))
			browser.close()
			return saved_files

		istanbul_output = output_dir / "ipragaz_ISTANBUL_prices.txt"
		canakkale_output = output_dir / "ipragaz_CANAKKALE_prices.txt"
		istanbul_first = True
		canakkale_first = True

		for idx, city in enumerate(cities, 1):
			value = city["value"]
			text = city["text"].strip()
			print(f"\n[{idx}/{len(cities)}] Şehir: {text} (value={value})")

			try:
				page.wait_for_selector("#provinceautocomplete-list", state="visible", timeout=1000)
			except PWTimeoutError:
				_open_city_dropdown(page)

			price = _select_city_and_get_price(page, value, text, debug=debug)
			if not price:
				print(f"  ⚠ Fiyat alınamadı: {text}")
				if idx < len(cities):
					try:
						_click_back_button(page, debug=debug)
					except Exception:
						pass
				continue

			print(f"  Fiyat: {price} TL/lt")

			upper_text = text.upper()
			is_istanbul = "ISTANBUL" in upper_text
			is_canakkale = "CANAKKALE" in upper_text

			if is_istanbul:
				_write_ipragaz_price_to_text(text, price, istanbul_output, append=not istanbul_first)
				if istanbul_first:
					saved_files.append(istanbul_output)
					istanbul_first = False
				print(f"  ✓ Kaydedildi: {istanbul_output.name}")
			elif is_canakkale:
				_write_ipragaz_price_to_text(text, price, canakkale_output, append=not canakkale_first)
				if canakkale_first:
					saved_files.append(canakkale_output)
					canakkale_first = False
				print(f"  ✓ Kaydedildi: {canakkale_output.name}")
			else:
				display_name = _map_city_name_for_display(text)
				norm = _normalize_city_name_for_filename(display_name)
				fp = output_dir / f"ipragaz_{norm}_prices.txt"
				_write_ipragaz_price_to_text(display_name, price, fp, append=False)
				saved_files.append(fp)
				print(f"  ✓ Kaydedildi: {fp.name}")

			if idx < len(cities):
				back_success = False
				try:
					_click_back_button(page, debug=debug)
					print("  ✓ Geri butonuna tıklandı, şehir seçimine dönüldü")
					back_success = True
				except Exception as e:
					print(f"  ⚠ Geri butonu tıklanamadı: {e}")
					try:
						print("  ⚠ Sayfa yenileniyor (fallback)...")
						page.reload(wait_until="domcontentloaded")
						try:
							page.wait_for_load_state("networkidle", timeout=8000)
						except Exception:
							pass
						_click_manual_button(page)
						_open_city_dropdown(page)
						print("  ✓ Sayfa yenilendi ve form sıfırlandı")
						back_success = True
					except Exception:
						pass
				
				time.sleep(random.uniform(min_delay, max_delay))

		browser.close()

	print(f"\nToplam {len(saved_files)} dosya yazıldı -> {output_dir}")
	return saved_files
