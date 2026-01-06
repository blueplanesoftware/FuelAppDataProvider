from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page
import random
import re
from common.istanbul_districts import get_istanbul_district_region, ISTANBUL_DISTRICT_REGIONS

AYTEMIZ_URL = "https://www.aytemiz.com.tr/akaryakit-fiyatlari/benzin-fiyatlari"

@dataclass
class AytemizBenzinPriceRow:
	"""Benzin price row for a city/district."""
	city: str
	district: Optional[str]  # None if city-level only
	benzin_95: Optional[str] = None
	motorin: Optional[str] = None
	motorin_optimum: Optional[str] = None
	kalorifer_yakiti: Optional[str] = None
	fuel_oil: Optional[str] = None
	lpg: Optional[str] = None  # Merged later

@dataclass
class AytemizLPGPriceRow:
	"""LPG price row for a city/district."""
	city: str
	district: Optional[str]  # None if city-level only
	lpg: str

def _ensure_cookie_accepted(page: Page) -> None:
	"""Accept cookies if banner is visible."""
	try:
		accept_button = page.locator("#onetrust-accept-btn-handler")
		if accept_button.is_visible(timeout=5000):
			print("Cookie banner detected, clicking accept.")
			accept_button.click()
			page.wait_for_timeout(500)
	except PWTimeoutError:
		print("No cookie banner or already accepted.")
	except Exception as e:
		print(f"Error handling cookie banner: {e}")

def _extract_benzin_prices_from_page(page: Page, selected_city_name: Optional[str] = None) -> List[AytemizBenzinPriceRow]:
	"""Extracts benzin prices from the current page's table.
	
	Args:
		page: Playwright page object
		selected_city_name: The city name selected from dropdown (used to determine if text without '/' is a district)
	"""
	prices: List[AytemizBenzinPriceRow] = []
	try:
		# Wait for the table to be visible
		page.wait_for_selector("#fuel-price-table tbody tr", timeout=15000)
		rows = page.locator("#fuel-price-table tbody tr")
		row_count = rows.count()
		
		if row_count == 0:
			print("    Warning: Table found but no rows detected")
			return prices

		for i in range(row_count):
			try:
				row = rows.nth(i)
				cells = row.locator("td")
				cell_count = cells.count()
				
				if cell_count >= 6:  # Expecting at least 6 columns for benzin prices
					city_district_text = cells.nth(0).inner_text().strip()
					
					# Parse city and district
					if '/' in city_district_text:
						# Format: "City / District" or "İstanbul / Avrupa"
						city_name = city_district_text.split('/')[0].strip()
						district_name = city_district_text.split('/')[-1].strip()
					else:
						# No '/' - could be just city name or just district name
						# If we have a selected_city_name and it matches, treat the text as district
						if selected_city_name and city_district_text.lower() != selected_city_name.lower():
							# Text doesn't match selected city, so it's likely a district
							city_name = selected_city_name
							district_name = city_district_text
						else:
							# No city selected or text matches city name, treat as city-level
							city_name = city_district_text
							district_name = None

					prices.append(AytemizBenzinPriceRow(
						city=city_name,
						district=district_name,
						benzin_95=cells.nth(1).inner_text().strip(),
						motorin=cells.nth(2).inner_text().strip(),
						motorin_optimum=cells.nth(3).inner_text().strip(),
						kalorifer_yakiti=cells.nth(4).inner_text().strip(),
						fuel_oil=cells.nth(5).inner_text().strip(),
					))
				else:
					print(f"    Warning: Row {i} has only {cell_count} cells (expected at least 6)")
			except Exception as e:
				print(f"    Error extracting row {i}: {e}")
				continue
	except PWTimeoutError:
		print("    Timeout waiting for benzin price table. No benzin prices found or page did not load correctly.")
	except Exception as e:
		print(f"    Error extracting benzin prices: {e}")
		import traceback
		traceback.print_exc()
	return prices

def _extract_lpg_prices_from_page(page: Page) -> List[AytemizLPGPriceRow]:
	"""Extracts LPG prices from the current page's table."""
	prices: List[AytemizLPGPriceRow] = []
	try:
		# LPG table uses #fuelPricesHeader in the header, not #fuel-price-table
		# Try to find the table by the header first
		try:
			page.wait_for_selector("#fuelPricesHeader", timeout=15000)
			# Find the table that contains this header
			table = page.locator("#fuelPricesHeader").locator("xpath=ancestor::table")
			rows = table.locator("tbody tr")
		except PWTimeoutError:
			# Fallback: try to find any table with tbody rows
			page.wait_for_selector("table tbody tr", timeout=10000)
			rows = page.locator("table tbody tr")
		
		row_count = rows.count()
		print(f"    Found {row_count} row(s) in LPG table")

		for i in range(row_count):
			try:
				row = rows.nth(i)
				cells = row.locator("td")
				cell_count = cells.count()
				if cell_count >= 2:  # Expecting at least 2 columns for LPG prices
					city_district_text = cells.nth(0).inner_text().strip()
					lpg_price = cells.nth(1).inner_text().strip()
					
					if not city_district_text or not lpg_price:
						continue  # Skip empty rows
					
					# Parse city and district (e.g., "İstanbul / Avrupa" or just "Adana")
					if '/' in city_district_text:
						city_name = city_district_text.split('/')[0].strip()
						district_name = city_district_text.split('/')[-1].strip()
					else:
						city_name = city_district_text
						district_name = None
					
					prices.append(AytemizLPGPriceRow(
						city=city_name,
						district=district_name,
						lpg=lpg_price,
					))
				else:
					print(f"    Warning: LPG row {i} has only {cell_count} cells (expected at least 2)")
			except Exception as e:
				print(f"    Error extracting LPG row {i}: {e}")
				continue
	except PWTimeoutError:
		print("    Timeout waiting for LPG price table. No LPG prices found or page did not load correctly.")
	except Exception as e:
		print(f"    Error extracting LPG prices: {e}")
		import traceback
		traceback.print_exc()
	return prices

def _click_lpg_button(page: Page, debug: bool) -> bool:
	"""
	Clicks the 'LPG Pompa Fiyatları' button to switch to LPG prices.
	Handles potential ASP.NET postbacks.
	"""
	print("Attempting to click 'LPG Pompa Fiyatları' button...")
	lpg_button_selector = "a[href=\"javascript:filterPrice(2)\"]"
	radio_button_selector = "#ContentPlaceHolder1_C001_rdbPriceType_1"

	try:
		# Try clicking the <a> tag directly
		lpg_button = page.locator(lpg_button_selector)
		if lpg_button.is_visible(timeout=10000):
			lpg_button.click()
			print("Clicked LPG button (<a> tag).")
			page.wait_for_load_state("networkidle", timeout=20000)
			page.wait_for_timeout(random.uniform(1000, 2000))  # Wait for UI to settle
			return True
	except PWTimeoutError:
		print("LPG button (<a> tag) not found or not clickable within timeout.")
	except Exception as e:
		print(f"Error clicking LPG button (<a> tag): {e}")

	# Fallback: Try clicking the hidden radio button and triggering postback
	try:
		lpg_radio_button = page.locator(radio_button_selector)
		if lpg_radio_button.is_visible(timeout=5000):  # It might be hidden but still interactable via JS
			lpg_radio_button.click()
			print("Clicked LPG radio button.")
			page.wait_for_load_state("networkidle", timeout=20000)
			page.wait_for_timeout(random.uniform(1000, 2000))
			return True
		else:
			# If not visible, try to force click or evaluate JavaScript
			page.evaluate(f"document.querySelector('{radio_button_selector}').click()")
			print("Forced click on LPG radio button via JavaScript.")
			page.wait_for_load_state("networkidle", timeout=20000)
			page.wait_for_timeout(random.uniform(1000, 2000))
			return True
	except PWTimeoutError:
		print("LPG radio button not found or not interactable.")
	except Exception as e:
		print(f"Error interacting with LPG radio button: {e}")

	print("Failed to click LPG button using all known methods.")
	return False

def _get_city_options(page: Page) -> List[Dict[str, str]]:
	"""Extracts city options from the dropdown."""
	options = page.locator("#ContentPlaceHolder1_C001_ddlCity option").all()
	city_options = []
	for option in options:
		value = option.get_attribute("value")
		text = option.inner_text().strip()
		if value and value != "-1" and text:
			city_options.append({"value": value, "text": text})
	return city_options

def _select_city_and_wait_for_load(page: Page, city_value: str, debug: bool) -> None:
	"""Selects a city from the dropdown and waits for the page to load."""
	print(f"Selecting city with value: {city_value}")
	try:
		page.select_option("#ContentPlaceHolder1_C001_ddlCity", value=city_value)
		# The onchange event triggers __doPostBack, so we wait for networkidle
		page.wait_for_load_state("networkidle", timeout=20000)
		page.wait_for_timeout(random.uniform(1000, 2000))  # Give UI time to update
	except PWTimeoutError:
		print(f"Timeout while selecting city {city_value} or waiting for load.")
		# Attempt to force postback if select_option didn't trigger it
		page.evaluate(f"__doPostBack('ctl00$ContentPlaceHolder1$C001$ddlCity','');")
		page.wait_for_load_state("networkidle", timeout=20000)
		page.wait_for_timeout(random.uniform(1000, 2000))
	except Exception as e:
		print(f"Error selecting city {city_value}: {e}")

def _fetch_all_lpg_prices_dict(debug: bool = False) -> Dict[str, List[AytemizLPGPriceRow]]:
	"""
	Fetches all LPG prices from the main page without selecting any city.
	After clicking the LPG button, extracts all LPG prices that are shown on the main page.
	"""
	all_lpg_prices: Dict[str, List[AytemizLPGPriceRow]] = {}
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
		page.set_default_navigation_timeout(60000)

		print(f"Navigating to {AYTEMIZ_URL}")
		page.goto(AYTEMIZ_URL, wait_until="domcontentloaded")
		_ensure_cookie_accepted(page)

		# Wait for page to be ready
		page.wait_for_timeout(2000)

		# Click the LPG button
		print("Clicking LPG button to switch to LPG prices...")
		if not _click_lpg_button(page, debug):
			print("Could not switch to LPG prices. Exiting LPG fetch.")
			browser.close()
			return {}

		# Wait for LPG prices table to load after clicking the button
		print("Waiting for LPG price table to load...")
		page.wait_for_timeout(3000)  # Give it time for the table to populate

		# Extract LPG prices from the main page (without selecting any city)
		print("Extracting LPG prices from main page...")
		prices = _extract_lpg_prices_from_page(page)
		
		if prices:
			print(f"Found {len(prices)} LPG price row(s) on main page")
			# Organize by city/district
			for price_row in prices:
				# For Istanbul, the main table already has "İstanbul / Avrupa" and "İstanbul / Anadolu"
				# For other cities, it's just the city name
				key = f"{price_row.city} / {price_row.district}" if price_row.district else price_row.city
				all_lpg_prices.setdefault(key, []).append(price_row)
		else:
			print("Warning: No LPG prices found on main page.")

		# Check if Istanbul LPG prices are missing
		istanbul_found = False
		for key in all_lpg_prices.keys():
			if "İstanbul" in key:
				istanbul_found = True
				break

		if not istanbul_found:
			print("Istanbul LPG prices not found in main table. Selecting Istanbul to fetch LPG prices...")
			try:
				# Select Istanbul (value="34") from the dropdown
				_select_city_and_wait_for_load(page, "34", debug)
				
				# Wait for the table to update
				page.wait_for_timeout(2000)
				
				# Extract LPG prices for Istanbul
				istanbul_prices = _extract_lpg_prices_from_page(page)
				if istanbul_prices:
					print(f"Found {len(istanbul_prices)} LPG price row(s) for Istanbul")
					for price_row in istanbul_prices:
						# Istanbul LPG prices might have Avrupa/Anadolu districts
						key = f"{price_row.city} / {price_row.district}" if price_row.district else price_row.city
						all_lpg_prices.setdefault(key, []).append(price_row)
				else:
					print("Warning: No LPG prices found for Istanbul after selection.")
			except Exception as e:
				print(f"Error fetching Istanbul LPG prices: {e}")
				if debug:
					import traceback
					traceback.print_exc()

		browser.close()
	return all_lpg_prices

def _merge_lpg_for_single_city(
	city_name: str,
	benzin_prices: List[AytemizBenzinPriceRow],
	lpg_data: Dict[str, List[AytemizLPGPriceRow]]
) -> List[AytemizBenzinPriceRow]:
	"""
	Merges LPG prices into benzin prices for a single city.
	Handles Istanbul districts by mapping them to Avrupa/Anadolu regions.
	"""
	merged_prices = [AytemizBenzinPriceRow(
		city=p.city,
		district=p.district,
		benzin_95=p.benzin_95,
		motorin=p.motorin,
		motorin_optimum=p.motorin_optimum,
		kalorifer_yakiti=p.kalorifer_yakiti,
		fuel_oil=p.fuel_oil,
		lpg=p.lpg,
	) for p in benzin_prices]
	
	if city_name == "İstanbul":
		# For Istanbul, match districts to Avrupa/Anadolu LPG prices
		# First, find available Istanbul LPG prices
		istanbul_lpg_avrupa = None
		istanbul_lpg_anadolu = None
		
		# Look for "İstanbul / Avrupa" and "İstanbul / Anadolu"
		# Handle variations in key format (with/without spaces around "/")
		print(f"    Looking for Istanbul LPG prices in {len(lpg_data)} LPG entries...")
		for key, lpg_rows in lpg_data.items():
			# Normalize key for comparison (remove extra spaces)
			normalized_key = " ".join(key.split())
			if "İstanbul" in normalized_key or "Istanbul" in normalized_key:
				print(f"    Found Istanbul LPG key: '{key}' (normalized: '{normalized_key}') with {len(lpg_rows)} row(s)")
				if "Avrupa" in normalized_key:
					istanbul_lpg_avrupa = lpg_rows[0].lpg if lpg_rows else None
					print(f"    Istanbul Avrupa LPG price: {istanbul_lpg_avrupa}")
				elif "Anadolu" in normalized_key:
					istanbul_lpg_anadolu = lpg_rows[0].lpg if lpg_rows else None
					print(f"    Istanbul Anadolu LPG price: {istanbul_lpg_anadolu}")
				elif normalized_key == "İstanbul" or normalized_key == "Istanbul":
					# Fallback: if only "İstanbul" (no district) is found, we can't split it
					print(f"    Found Istanbul LPG without district: {lpg_rows[0].lpg if lpg_rows else None}")
		
		if not istanbul_lpg_avrupa and not istanbul_lpg_anadolu:
			print(f"    Warning: No Istanbul LPG prices found (Avrupa or Anadolu)")
		
		# Apply LPG prices to districts based on their region
		# Skip rows where district is "Avrupa" or "Anadolu" (these are region labels, not actual districts)
		matched_count = 0
		unmatched_districts = []
		district_count = 0
		all_districts = []  # Debug: collect all district names
		
		for price_row in merged_prices:
			if price_row.district:
				district_count += 1
				all_districts.append(price_row.district)
				# Skip region labels
				if price_row.district.lower() in ["avrupa", "anadolu"]:
					continue
				
				# Look up which region this district belongs to
				district_region = get_istanbul_district_region(price_row.district)
				if district_region == "Avrupa" and istanbul_lpg_avrupa:
					price_row.lpg = istanbul_lpg_avrupa
					matched_count += 1
				elif district_region == "Anadolu" and istanbul_lpg_anadolu:
					price_row.lpg = istanbul_lpg_anadolu
					matched_count += 1
				elif not district_region:
					unmatched_districts.append(price_row.district)
					# Debug: show first few unmatched districts
					if len(unmatched_districts) <= 5:
						print(f"    Debug: District '{price_row.district}' (repr: {repr(price_row.district)}) not found in mapping")
		
		# Debug: show all districts found
		print(f"    Debug: Found {district_count} districts with district field: {all_districts[:10]}")
		if unmatched_districts:
			print(f"    Warning: {len(unmatched_districts)} districts not found in mapping. Sample: {unmatched_districts[:5]}")
		print(f"    Applied LPG prices to {matched_count} out of {district_count} Istanbul districts (skipped {district_count - len(unmatched_districts) - matched_count} region labels)")
	else:
		# For non-Istanbul cities, direct match
		if city_name in lpg_data and lpg_data[city_name]:
			lpg_price = lpg_data[city_name][0].lpg
			for price_row in merged_prices:
				price_row.lpg = lpg_price
	
	return merged_prices

def _normalize_location_name(location: str) -> str:
	"""Normalize location name (city or district) for output - uppercase, remove special chars."""
	# Replace Turkish characters
	location = location.replace("İ", "I").replace("ı", "i").replace("ş", "s").replace("Ş", "S")
	location = location.replace("ğ", "g").replace("Ğ", "G").replace("ü", "u").replace("Ü", "U")
	location = location.replace("ö", "o").replace("Ö", "O").replace("ç", "c").replace("Ç", "C")
	return location.upper().strip()

def _write_aytemiz_prices_to_text(prices: List[AytemizBenzinPriceRow], output_file: Path) -> None:
	"""Write Aytemiz prices to a text file. Format matches Petrolofisi (district per line, no city header)."""
	lines: List[str] = []
	for p in prices:
		# Format: District | Benzin 95: ... | Motorin: ... | ... | LPG: ...
		# Use district name if available, otherwise city name
		location = p.district if p.district else p.city
		location = _normalize_location_name(location)
		parts = [location]
		
		# Always include all fields, use "-" if not available (like Shell/Petrolofisi format)
		parts.append(f"Benzin 95: {p.benzin_95 if p.benzin_95 else '-'}")
		parts.append(f"Motorin: {p.motorin if p.motorin else '-'}")
		parts.append(f"Motorin Optimum: {p.motorin_optimum if p.motorin_optimum else '-'}")
		parts.append(f"Kalorifer Yakıtı: {p.kalorifer_yakiti if p.kalorifer_yakiti else '-'}")
		parts.append(f"Fuel Oil: {p.fuel_oil if p.fuel_oil else '-'}")
		parts.append(f"LPG: {p.lpg if p.lpg else '-'}")
		
		lines.append(" | ".join(parts))
	
	output_file.write_text("\n".join(lines), encoding="utf-8")

def _normalize_city_name_for_filename(city_name: str) -> str:
	"""Normalize city name for use in filename (remove special chars, handle Istanbul districts)."""
	# Remove "İstanbul / " prefix if present, we'll use just the city name for filename
	if " / " in city_name:
		city_name = city_name.split(" / ")[0]
	# Replace special characters
	city_name = city_name.replace("İ", "I").replace("ı", "i").replace("ş", "s").replace("Ş", "S")
	city_name = city_name.replace("ğ", "g").replace("Ğ", "G").replace("ü", "u").replace("Ü", "U")
	city_name = city_name.replace("ö", "o").replace("Ö", "O").replace("ç", "c").replace("Ç", "C")
	return city_name.upper()

def save_all_cities_prices_txt(output_dir: Path, debug: bool = False) -> List[Path]:
	"""
	Fetches LPG prices first, then fetches benzin prices city by city,
	merges them, and writes a text file immediately for each city.
	Returns list of created file paths.
	"""
	output_dir.mkdir(parents=True, exist_ok=True)
	
	saved_files: List[Path] = []
	
	try:
		# Step 1: Fetch all LPG prices first (one browser session)
		print("Fetching all LPG prices...")
		lpg_data = _fetch_all_lpg_prices_dict(debug)
		print(f"Fetched LPG data for {len(lpg_data)} entries.")
		
		# Step 2: Fetch benzin prices city by city and write files immediately
		print("Fetching benzin prices and writing files...")
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
			page.set_default_navigation_timeout(60000)

			print(f"Navigating to {AYTEMIZ_URL} for benzin prices.")
			page.goto(AYTEMIZ_URL, wait_until="domcontentloaded")
			_ensure_cookie_accepted(page)

			page.wait_for_selector("#ContentPlaceHolder1_C001_ddlCity", state="visible", timeout=15000)
			city_options = _get_city_options(page)

			for city_option in city_options:
				city_name = city_option["text"].strip()
				city_value = city_option["value"]
				print(f"Fetching Benzin prices for city: {city_name} (value: {city_value})")

				try:
					_select_city_and_wait_for_load(page, city_value, debug)

					benzin_prices = _extract_benzin_prices_from_page(page, selected_city_name=city_name)
					if benzin_prices:
						print(f"  Found {len(benzin_prices)} price row(s) for {city_name}")
						
						# Merge with LPG prices for this city
						merged_prices = _merge_lpg_for_single_city(city_name, benzin_prices, lpg_data)
						
						# Write file immediately using the city_name from the dropdown (not from data)
						try:
							normalized_name = _normalize_city_name_for_filename(city_name)
							fp = output_dir / f"aytemiz_{normalized_name}_prices.txt"
							_write_aytemiz_prices_to_text(merged_prices, fp)
							saved_files.append(fp)
							print(f"  Saved: {fp.name} ({len(merged_prices)} row(s))")
						except Exception as e:
							print(f"  Error writing file for {city_name}: {e}")
							if debug:
								import traceback
								traceback.print_exc()
					else:
						print(f"  Warning: No Benzin prices found for {city_name}.")
				except Exception as e:
					print(f"  Error fetching prices for {city_name}: {e}")
					if debug:
						import traceback
						traceback.print_exc()

				page.wait_for_timeout(random.uniform(500, 1500))

			browser.close()
		
	except Exception as e:
		print(f"Error in save_all_cities_prices_txt: {e}")
		if debug:
			import traceback
			traceback.print_exc()
	
	return saved_files

def fetch_all_cities_with_lpg(debug: bool = False) -> Dict[str, List[AytemizBenzinPriceRow]]:
	"""
	Fetches all benzin prices, then all LPG prices, and merges them.
	Returns the merged data dictionary.
	"""
	print("Fetching all benzin prices...")
	benzin_data = _fetch_all_benzin_prices_dict(debug)
	print(f"Fetched benzin data for {len(benzin_data)} entries.")

	print("Fetching all LPG prices...")
	lpg_data = _fetch_all_lpg_prices_dict(debug)
	print(f"Fetched LPG data for {len(lpg_data)} entries.")

	print("Merging LPG prices into benzin data...")
	merged_data = _merge_lpg_into_benzin(benzin_data, lpg_data)
	print("Merge complete.")

	return merged_data

def _merge_lpg_into_benzin(
	benzin_data: Dict[str, List[AytemizBenzinPriceRow]],
	lpg_data: Dict[str, List[AytemizLPGPriceRow]]
) -> Dict[str, List[AytemizBenzinPriceRow]]:
	"""
	Merges LPG prices into benzin price data.
	Handles Istanbul districts by mapping them to Avrupa/Anadolu regions.
	"""
	merged_data = benzin_data.copy()

	for lpg_key, lpg_rows in lpg_data.items():
		if "İstanbul" in lpg_key:
			# For Istanbul LPG, the key is "İstanbul / Avrupa" or "İstanbul / Anadolu"
			# We need to apply this LPG price to all districts in that region
			istanbul_city_part = lpg_key.split('/')[0].strip()
			istanbul_region = lpg_key.split('/')[-1].strip() if '/' in lpg_key else None

			if not istanbul_region:
				print(f"Warning: Istanbul LPG key '{lpg_key}' does not specify a region. Skipping merge for this entry.")
				continue

			# Get the single LPG price for this region (assuming one price per region)
			lpg_price_for_region = lpg_rows[0].lpg if lpg_rows else None

			if not lpg_price_for_region:
				print(f"Warning: No LPG price found for Istanbul region '{istanbul_region}'. Skipping.")
				continue

			# Iterate through all benzin entries to find matching Istanbul districts
			for benzin_key, benzin_price_list in merged_data.items():
				if "İstanbul" in benzin_key:
					# Benzin key might be "İstanbul / Kadıköy" or "İstanbul"
					benzin_city_part = benzin_key.split('/')[0].strip()
					benzin_district_part = benzin_key.split('/')[-1].strip() if '/' in benzin_key else None

					if benzin_district_part:
						district_region = get_istanbul_district_region(benzin_district_part)
						if district_region == istanbul_region:
							for row in benzin_price_list:
								row.lpg = lpg_price_for_region
					elif not benzin_district_part and istanbul_region == "Avrupa":  # Fallback for generic Istanbul if no district
						for row in benzin_price_list:
							row.lpg = lpg_price_for_region
		else:
			# For non-Istanbul cities, direct match
			if lpg_key in merged_data:
				lpg_price = lpg_rows[0].lpg if lpg_rows else None
				if lpg_price:
					for row in merged_data[lpg_key]:
						row.lpg = lpg_price
			else:
				print(f"Warning: No matching benzin data found for LPG city: {lpg_key}")

	return merged_data
