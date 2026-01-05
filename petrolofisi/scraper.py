from pathlib import Path
from typing import List
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random

@dataclass
class FuelPriceRow:
	city: str
	vmax_kursunsuz_95: str
	vmax_diesel: str
	gazyagi: str
	kalorifer_yakiti: str
	fuel_oil: str
	pogaz_otogaz: str

def extract_prices_from_page(page, prefer_with_tax: bool = True) -> List[FuelPriceRow]:
	"""Extract prices from the desktop table; fallback to empty list if not present."""
	rows = page.locator("table.table-prices tbody tr.price-row")
	row_count = rows.count()
	results: List[FuelPriceRow] = []
	for i in range(row_count):
		row = rows.nth(i)
		cells = row.locator("td")
		# 0: şehir
		city = cells.nth(0).inner_text().strip()
		def get_price(cell_idx: int) -> str:
			cell = cells.nth(cell_idx)
			span = cell.locator("span.with-tax" if prefer_with_tax else "span.without-tax")
			if span.count() > 0:
				return span.first.inner_text().strip()
			# fallback: cell text numeric part
			return cell.inner_text().split()[0].strip()
		results.append(
			FuelPriceRow(
				city=city,
				vmax_kursunsuz_95=get_price(1),
				vmax_diesel=get_price(2),
				gazyagi=get_price(3),
				kalorifer_yakiti=get_price(4),
				fuel_oil=get_price(5),
				pogaz_otogaz=get_price(6),
			)
		)
	return results

def write_prices_to_text(prices: List[FuelPriceRow], output_file: Path) -> None:
	lines: List[str] = []
	for p in prices:
		lines.append(
			f"{p.city} | 95: {p.vmax_kursunsuz_95} | Diesel: {p.vmax_diesel} | "
			f"Gazyağı: {p.gazyagi} | Kalorifer: {p.kalorifer_yakiti} | FuelOil: {p.fuel_oil} | Otogaz: {p.pogaz_otogaz}"
		)
	output_file.write_text("\n".join(lines), encoding="utf-8")

def fetch_all_cities_prices(url: str, plate_codes: List[str], output_dir: Path, prefer_with_tax: bool = True, debug: bool = False, min_delay: float = 0.8, max_delay: float = 1.6, retries: int = 2) -> None:
	"""Open once, iterate all plate codes via dropdown, write only per-city price txt files (no HTML)."""
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		context = browser.new_context(
			user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			locale="tr-TR",
			timezone_id="Europe/Istanbul",
			viewport={"width": 1280, "height": 800},
			ignore_https_errors=True,
		)
		page = context.new_page()
		page.set_default_navigation_timeout(45000)
		page.goto(url, wait_until="domcontentloaded")
		# Cookie banner kapat (varsa)
		try:
			if page.locator("#onetrust-accept-btn-handler").is_visible():
				page.click("#onetrust-accept-btn-handler")
		except Exception:
			pass
		page.wait_for_selector("select.cities-dropdown", state="visible")
		page.locator("select.cities-dropdown").scroll_into_view_if_needed()

		output_dir.mkdir(parents=True, exist_ok=True)

		for code in plate_codes:
			for attempt in range(retries + 1):
				try:
					try:
						page.select_option("select.cities-dropdown", value=code)
					except Exception:
						page.evaluate(
							"(sel, val) => { const el = document.querySelector(sel); if (!el) return; el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
							"select.cities-dropdown",
							code,
						)
					# İçerik yüklensin
					page.wait_for_selector("table.table-prices tbody tr.price-row", timeout=10000)
					page.wait_for_load_state("networkidle")
					page.wait_for_timeout(400)

					prices = extract_prices_from_page(page, prefer_with_tax=prefer_with_tax)
					txt_out = output_dir / f"petrolofisi_{code}_prices.txt"
					write_prices_to_text(prices, txt_out)
					print(f"OK: {code} -> {txt_out.name}")
					break
				except PWTimeoutError:
					if attempt < retries:
						backoff_ms = int(700 * (attempt + 1) * random.uniform(1.0, 1.6))
						page.wait_for_timeout(backoff_ms)
						continue
					else:
						print(f"Atlandı (timeout): {code}")
				except Exception as e:
					if attempt < retries:
						backoff_ms = int(600 * (attempt + 1) * random.uniform(1.0, 1.5))
						page.wait_for_timeout(backoff_ms)
						continue
					else:
						print(f"Hata/atlandı: {code} -> {e}")
			# Nazik hız limiti
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))

		browser.close()

def fetch_city_prices(url: str, city_value: str, output_file: Path, debug: bool = False) -> None:
	"""Open the page, select given city by option value, then save full HTML and extracted district prices."""
	with sync_playwright() as p:
		browser = p.chromium.launch(headless=not debug, slow_mo=400 if debug else 0)
		context = browser.new_context(
			user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			locale="tr-TR",
			timezone_id="Europe/Istanbul",
			viewport={"width": 1280, "height": 800},
			ignore_https_errors=True,
		)
		page = context.new_page()
		page.set_default_navigation_timeout(45000)
		page.goto(url, wait_until="domcontentloaded")
		# Cookie banner kapat (varsa)
		try:
			if page.locator("#onetrust-accept-btn-handler").is_visible():
				page.click("#onetrust-accept-btn-handler")
		except Exception:
			pass
		page.wait_for_selector("select.cities-dropdown", state="visible")
		page.locator("select.cities-dropdown").scroll_into_view_if_needed()
		# İl seçimi
		try:
			page.select_option("select.cities-dropdown", value=city_value)
		except Exception:
			page.evaluate(
				"(sel, val) => { const el = document.querySelector(sel); if (!el) return; el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
				"select.cities-dropdown",
				city_value,
			)
		# Fiyat tablosu/district satırları yüklensin
		page.wait_for_selector("table.table-prices tbody tr.price-row", timeout=10000)
		page.wait_for_load_state("networkidle")
		# Small grace period for any DOM post-processing
		page.wait_for_timeout(1200)
		# Extract prices and write to text file (with tax by default)
		prices = extract_prices_from_page(page, prefer_with_tax=True)
		write_prices_to_text(prices, output_file)
		browser.close()

