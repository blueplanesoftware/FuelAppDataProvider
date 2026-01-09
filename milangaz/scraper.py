from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
import random
import time
import re

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError

MILANGAZ_URL = "https://milangaz.com.tr/otogaz/lpg-ve-otogaz-il-tavan-fiyatlari/"


@dataclass
class MilangazPriceRow:
	"""Single Milangaz Otogaz price row for a city."""

	city: str
	price: str  # TL/lt


def _normalize_city_name_for_filename(city_name: str) -> str:
	"""Normalize city name for filenames (uppercase ASCII-ish)."""
	replacements = {
		"İ": "I",
		"ı": "i",
		"Ş": "S",
		"ş": "s",
		"Ğ": "G",
		"ğ": "g",
		"Ü": "U",
		"ü": "u",
		"Ö": "O",
		"ö": "o",
		"Ç": "C",
		"ç": "c",
		"-": "_",
		" ": "_",
	}
	n = city_name
	for src, dst in replacements.items():
		n = n.replace(src, dst)
	# Remove any remaining non-alnum/underscore
	n = re.sub(r"[^A-Z0-9_]", "", n.upper())
	return n


def _write_milangaz_price_to_text(city_label: str, price: str, output_file: Path, append: bool = False) -> None:
	"""Write one line 'CITY: PRICE' to txt, optionally appending."""
	if not price:
		return

	line = f"{city_label}: {price}"

	if append and output_file.exists():
		existing = output_file.read_text(encoding="utf-8").strip()
		if existing:
			output_file.write_text(f"{existing}\n{line}", encoding="utf-8")
		else:
			output_file.write_text(line, encoding="utf-8")
	else:
		output_file.write_text(line, encoding="utf-8")


def _get_city_options(page: Page) -> List[Dict[str, str]]:
	"""Return list of city options from the Milangaz select."""
	page.wait_for_selector("select#iller", state="visible", timeout=15000)
	options = page.query_selector_all("select#iller option")

	result: List[Dict[str, str]] = []
	for opt in options:
		value = (opt.get_attribute("value") or "").strip()
		text = (opt.inner_text() or "").strip()
		if not value or not text or value == "":
			# Skip the "Seçiniz" placeholder
			continue
		result.append({"value": value, "text": text})
	return result


def _extract_price_from_page(page: Page) -> str:
	"""Extract numeric price from the productprice strong element."""
	try:
		page.wait_for_selector(".productprice strong", state="visible", timeout=10000)
	except PWTimeoutError:
		return ""

	raw = page.locator(".productprice strong").first.inner_text().strip()
	# Handle Turkish decimal comma
	raw_normalized = raw.replace(".", "").replace(",", ".") if "," in raw and raw.count(",") == 1 else raw
	m = re.search(r"(\d+[.,]?\d*)", raw_normalized)
	if not m:
		return raw.strip()
	price_str = m.group(1).replace(",", ".")
	return price_str


def _select_city_and_get_price(page: Page, city_value: str, city_text: str, debug: bool = False) -> str:
	"""Select city by option value and return extracted price string."""
	try:
		page.wait_for_selector("select#iller", state="visible", timeout=15000)
		select = page.locator("select#iller")

		# Select the city
		select.select_option(value=city_value)

		# Allow JS/Ajax to run and update price
		page.wait_for_timeout(1500)

		# Sometimes the form shows a loading spinner; give a bit more time
		try:
			page.wait_for_selector(".product-detail.show .productprice strong", state="visible", timeout=8000)
		except PWTimeoutError:
			if debug:
				print(f"  Warning: price element did not become visible for {city_text}")

		price = _extract_price_from_page(page)
		if not price or price in ("0", "0.0", "0.00"):
			if debug:
				print(f"  Warning: suspicious price '{price}' for {city_text}")
		return price
	except Exception as e:
		print(f"  Error selecting {city_text} ({city_value}): {e}")
		if debug:
			import traceback

			traceback.print_exc()
		return ""


def save_all_cities_prices_txt(
	output_dir: Path,
	url: str = MILANGAZ_URL,
	debug: bool = False,
	min_delay: float = 0.8,
	max_delay: float = 1.6,
) -> List[Path]:
	"""
	Tüm şehirler için Milangaz Otogaz fiyatlarını çekip txt dosyalarına yazar.

	Çıktılar: milangaz/milangaz_<ŞEHİR>_prices.txt
	İstanbul (Anadolu) ve İstanbul (Avrupa) birleştirilir: milangaz_ISTANBUL_prices.txt
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

		# Get city options from select
		cities = _get_city_options(page)
		print(f"Milangaz: {len(cities)} şehir bulundu.")

		istanbul_output = output_dir / "milangaz_ISTANBUL_prices.txt"
		istanbul_prices: List[Dict[str, str]] = []  # Store Istanbul prices to write together

		for idx, city in enumerate(cities, 1):
			value = city["value"]
			text = city["text"].strip()

			print(f"\n[{idx}/{len(cities)}] Şehir: {text} (value={value})")

			price = _select_city_and_get_price(page, value, text, debug=debug)
			if not price:
				print(f"  ⚠ Fiyat alınamadı: {text}")
				continue

			print(f"  Fiyat: {price} TL/lt")

			upper_text = text.upper()
			is_istanbul_anadolu = "İSTANBUL-ANADOLU" in upper_text or "ISTANBUL-ANADOLU" in upper_text or "İSTANBUL ANADOLU" in upper_text
			is_istanbul_avrupa = "İSTANBUL-AVRUPA" in upper_text or "ISTANBUL-AVRUPA" in upper_text or "İSTANBUL AVRUPA" in upper_text

			if is_istanbul_anadolu or is_istanbul_avrupa:
				# Store Istanbul prices to write together at the end
				label = "İstanbul (Anadolu)" if is_istanbul_anadolu else "İstanbul (Avrupa)"
				istanbul_prices.append({"label": label, "price": price})
				print(f"  ✓ İstanbul fiyatı toplandı: {label}")
			else:
				# Write other cities immediately
				norm = _normalize_city_name_for_filename(text)
				fp = output_dir / f"milangaz_{norm}_prices.txt"
				_write_milangaz_price_to_text(text.title(), price, fp, append=False)
				saved_files.append(fp)
				print(f"  ✓ Kaydedildi: {fp.name}")

			# Küçük rastgele bekleme
			if idx < len(cities):
				time.sleep(random.uniform(min_delay, max_delay))

		# Write Istanbul file with both entries
		if istanbul_prices:
			# Write first entry
			_write_milangaz_price_to_text(istanbul_prices[0]["label"], istanbul_prices[0]["price"], istanbul_output, append=False)
			# Append remaining entries
			for price_data in istanbul_prices[1:]:
				_write_milangaz_price_to_text(price_data["label"], price_data["price"], istanbul_output, append=True)
			saved_files.append(istanbul_output)
			print(f"\n✓ İstanbul dosyası yazıldı ({len(istanbul_prices)} fiyat): {istanbul_output.name}")

			# Küçük rastgele bekleme
			if idx < len(cities):
				time.sleep(random.uniform(min_delay, max_delay))

		browser.close()

	print(f"\nToplam {len(saved_files)} dosya yazıldı -> {output_dir}")
	return saved_files


