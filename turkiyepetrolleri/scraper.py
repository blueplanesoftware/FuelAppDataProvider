from pathlib import Path
from typing import List
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random
import re

TPPD_URL = "https://www.tppd.com.tr/akaryakit-fiyatlari"

def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass

def _normalize_city_name(name: str) -> str:
	"""Normalize city name to match common naming conventions."""
	name = name.strip().upper()
	# Handle special cases
	if "KAHRAMANMARAŞ" in name or "K.MARAS" in name:
		return "K.MARAS"
	# Remove common suffixes
	name = re.sub(r'\s*GÜNCEL\s*AKARYAKIT\s*FİYATLARI\s*$', '', name, flags=re.IGNORECASE)
	name = re.sub(r'\s+', ' ', name).strip()
	return name

def _extract_city_links_from_main_page(page) -> List[dict]:
	"""Extract city links from the main page's otherStations section."""
	# Wait for the links to be available
	try:
		page.wait_for_selector(".otherStations a[href*='-akaryakit-fiyatlari']", timeout=10000)
	except Exception:
		pass
	
	links = page.locator(".otherStations a[href*='-akaryakit-fiyatlari']")
	count = links.count()
	city_links: List[dict] = []
	
	for i in range(count):
		link = links.nth(i)
		try:
			href = link.get_attribute("href")
			text = link.inner_text().strip()
			
			# Extract city name from text
			city_name = _normalize_city_name(text)
			
			# Fallback: Extract from URL if text parsing fails
			if not city_name and href:
				url_match = re.search(r'/([^/]+)-akaryakit-fiyatlari', href)
				if url_match:
					url_city = url_match.group(1).upper().replace('-', ' ')
					city_name = _normalize_city_name(url_city)
			
			if href and city_name:
				city_links.append({"name": city_name, "url": href})
		except Exception:
			continue
	return city_links

@dataclass
class TPPDPriceRow:
	district: str  # İlçe
	kursunsuz_benzin: str  # KURŞUNSUZ BENZİN (TL/LT)
	gaz_yagi: str  # GAZ YAĞI (TL/LT)
	motorin_1: str  # MOTORİN (TL/LT) - first column
	motorin_2: str  # MOTORİN (TL/LT) - second column
	kalorifer_yakiti: str  # KALORİFER YAKITI (TL/KG)
	fuel_oil: str  # FUEL OIL (TL/KG)
	yk_fuel_oil: str  # Y.K. FUEL OIL (TL/KG)
	gaz: str  # GAZ

def _extract_prices_from_city_page(page) -> List[TPPDPriceRow]:
	"""Extract price table from city page."""
	# Wait for results section
	try:
		page.wait_for_selector("#results", timeout=10000)
	except Exception:
		pass
	
	# Wait a bit for table to render
	page.wait_for_timeout(500)
	
	table = page.locator("#results table.table.table-bordered.cf")
	if table.count() == 0:
		# Fallback: try any table in results
		table = page.locator("#results table")
	
	if table.count() == 0:
		return []
	
	rows = table.locator("tbody tr")
	row_count = rows.count()
	results: List[TPPDPriceRow] = []
	
	for i in range(row_count):
		row = rows.nth(i)
		tds = row.locator("td")
		td_count = tds.count()
		if td_count < 9:
			continue
		
		def get_cell_text(idx: int) -> str:
			try:
				cell = tds.nth(idx)
				# Try to get text from the cell, handling nested elements
				text = cell.inner_text().strip()
				# Clean up whitespace and newlines
				text = re.sub(r'\s+', ' ', text)
				# Remove any leading/trailing whitespace
				text = text.strip()
				return text if text else "-"
			except Exception:
				return "-"
		
		results.append(
			TPPDPriceRow(
				district=get_cell_text(0),
				kursunsuz_benzin=get_cell_text(1),
				gaz_yagi=get_cell_text(2),
				motorin_1=get_cell_text(3),
				motorin_2=get_cell_text(4),
				kalorifer_yakiti=get_cell_text(5),
				fuel_oil=get_cell_text(6),
				yk_fuel_oil=get_cell_text(7),
				gaz=get_cell_text(8),
			)
		)
	
	return results

def _write_tppd_prices_to_text(city_name: str, prices: List[TPPDPriceRow], output_file: Path) -> None:
	lines: List[str] = []
	for p in prices:
		lines.append(
			f"{p.district} | K.Benzin 95: {p.kursunsuz_benzin} | Gaz Yağı: {p.gaz_yagi} | "
			f"Motorin: {p.motorin_1} | Motorin 2: {p.motorin_2} | Kalorifer Yakıtı: {p.kalorifer_yakiti} | "
			f"Fuel Oil: {p.fuel_oil} | Y.K. Fuel Oil: {p.yk_fuel_oil} | Gaz: {p.gaz}"
		)
	output_file.write_text("\n".join(lines), encoding="utf-8")

def save_city_prices_txt(city_name: str, output_dir: Path, url: str = TPPD_URL, debug: bool = False) -> Path:
	"""Open TPPD prices page, navigate to city page, extract price table, and write txt."""
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
		
		# First, get the main page to find city links
		page.goto(url, wait_until="domcontentloaded")
		_ensure_cookie_accepted(page)
		page.wait_for_timeout(1000)
		
		# Extract city links
		city_links = _extract_city_links_from_main_page(page)
		
		# Find matching city
		target_link = None
		for link in city_links:
			if link["name"].upper() == city_name.upper():
				target_link = link
				break
		
		# Fallback: try partial match
		if not target_link:
			for link in city_links:
				if city_name.upper() in link["name"].upper() or link["name"].upper() in city_name.upper():
					target_link = link
					break
		
		if not target_link:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		
		# Navigate to city page
		city_url = target_link["url"]
		if not city_url.startswith("http"):
			city_url = f"https://www.tppd.com.tr{city_url}"
		
		page.goto(city_url, wait_until="domcontentloaded")
		page.wait_for_timeout(1500)
		
		# Extract prices
		prices = _extract_prices_from_city_page(page)
		
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"tppd_{city_name}_prices.txt"
		_write_tppd_prices_to_text(city_name, prices, fp)
		
		browser.close()
		return fp

def save_all_cities_prices_txt(output_dir: Path, url: str = TPPD_URL, debug: bool = False, min_delay: float = 0.8, max_delay: float = 1.6, retries: int = 1) -> List[Path]:
	"""Open TPPD prices page, iterate all cities, write per-city txt files to output_dir."""
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
		
		# Get main page and extract city links
		page.goto(url, wait_until="domcontentloaded")
		_ensure_cookie_accepted(page)
		page.wait_for_timeout(1000)
		
		city_links = _extract_city_links_from_main_page(page)
		output_dir.mkdir(parents=True, exist_ok=True)
		
		for link in city_links:
			city_name = link["name"]
			for attempt in range(retries + 1):
				try:
					# Navigate to city page
					city_url = link["url"]
					if not city_url.startswith("http"):
						city_url = f"https://www.tppd.com.tr{city_url}"
					
					page.goto(city_url, wait_until="domcontentloaded")
					page.wait_for_timeout(1500)
					
					# Extract prices
					prices = _extract_prices_from_city_page(page)
					
					if prices:
						fp = output_dir / f"tppd_{city_name}_prices.txt"
						_write_tppd_prices_to_text(city_name, prices, fp)
						saved.append(fp)
						print(f"OK: {city_name} -> {fp.name}")
					else:
						print(f"Uyarı: {city_name} için fiyat bulunamadı")
					
					break
				except PWTimeoutError:
					if attempt < retries:
						page.wait_for_timeout(int(1000 * (attempt + 1) * random.uniform(1.0, 1.4)))
						continue
					else:
						print(f"Atlandı (timeout): {city_name}")
				except Exception as e:
					if attempt < retries:
						page.wait_for_timeout(int(800 * (attempt + 1) * random.uniform(1.0, 1.3)))
						continue
					else:
						print(f"Hata/atlandı: {city_name} -> {e}")
			
			# Delay between cities
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		
		browser.close()
		return saved

def fetch_all_cities_prices(output_dir: Path, url: str = TPPD_URL, debug: bool = False, min_delay: float = 0.8, max_delay: float = 1.6, retries: int = 1) -> None:
	"""Automatically fetch all cities' prices (like Petrolofisi). Opens TPPD prices page, iterates all cities, writes per-city txt files."""
	saved = save_all_cities_prices_txt(output_dir, url, debug, min_delay, max_delay, retries)
	if saved:
		print(f"Tüm şehirlerin fiyat txt dosyaları 'turkiyepetrolleri/prices' klasörüne yazıldı (tppd_<ŞEHİR>_prices.txt).")
	else:
		print("Uyarı: Hiçbir dosya yazılamadı.")

