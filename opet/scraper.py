from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright
import random
import re

OPET_URL = "https://www.opet.com.tr/akaryakit-fiyatlari"

def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass

def _find_city_select(page):
	# Prefer known class selector first
	sel = page.locator("select.FuelPrice-module_obvSelect--3bb")
	if sel.count() > 0:
		return sel.first
	# Heuristic: find a <select> whose options contain common city names and count is large
	selects = page.locator("select")
	sel_count = selects.count()
	candidate = None
	for i in range(sel_count):
		handle = selects.nth(i)
		try:
			options: List[Dict[str, str]] = page.eval_on_selector_all(
				f"select:nth-of-type({i+1}) option",
				"opts => opts.map(o => ({ value: o.value, text: (o.textContent||'').trim() }))"
			)
			if not options or len(options) < 20:
				continue
			texts = [o.get("text","").upper() for o in options]
			if any(name in texts for name in ["ADANA","ANKARA","ISTANBUL","İSTANBUL"]):
				candidate = handle
				break
		except Exception:
			continue
	return candidate

def _get_city_options_from_select(select_handle) -> List[Dict[str, str]]:
	# Evaluate on the specific <select> element
	return select_handle.evaluate(
		"s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() })).filter(o => o.value)"
	)

def _select_option_with_fallback(page, select_handle, value: str) -> None:
	"""Try native select_option, then JS set on element, finally generic first select on page."""
	try:
		select_handle.select_option(value)
		return
	except Exception:
		pass
	try:
		select_handle.evaluate(
			"(el, val)=>{ el.value = val; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }",
			value
		)
		return
	except Exception:
		pass
	page.evaluate(
		"(val)=>{ const s=document.querySelector('select'); if(s){ s.value=val; s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('change',{bubbles:true})); }}",
		value
	)

def _wait_prices_table(page, timeout: int = 10000):
	# OPET table class contains FuelPrice-module_tableFuelPrice.. plus other classes
	loc = page.locator('table[class*="FuelPrice-module_tableFuelPrice"].table.table-nowrap.table-keyvalue.table-small-head')
	try:
		loc.wait_for(timeout=timeout)
		return loc
	except Exception:
		pass
	# Fallback: try to find any table under #root that looks like the fuel price table
	try:
		page.wait_for_selector("#root table", timeout=timeout)
	except Exception:
		# last resort: any table
		try:
			page.wait_for_selector("table", timeout=int(timeout / 2))
		except Exception:
			raise

	def _pick_best_table():
		tables = page.locator("#root table") if page.locator("#root table").count() > 0 else page.locator("table")
		count = tables.count()
		keywords = ["BENZIN", "BENZİN", "MOTORIN", "MOTORİN", "OTOGAZ", "LPG", "İLÇE", "ILÇE", "İL", "IL"]
		for i in range(count):
			t = tables.nth(i)
			try:
				ths = t.locator("thead th")
				hc = ths.count()
				if hc == 0:
					continue
				header_text = " ".join([ths.nth(j).inner_text().upper() for j in range(hc)])
				if any(k in header_text for k in keywords):
					return t
			except Exception:
				continue
		# fallback: return the first visible table
		for i in range(count):
			t = tables.nth(i)
			try:
				if t.is_visible():
					return t
			except Exception:
				continue
		return tables.first

	return _pick_best_table()

def _slugify_city(name: str) -> str:
	text = name.strip().lower()
	# Turkish character normalization
	replacements = {
		"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u",
		"â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
		" ": "-", "â€™": "", "’": "", "'": "", "“": "", "”": "", ".": "-", ",": "-",
	}
	for k, v in replacements.items():
		text = text.replace(k, v)
	# remove any non-url-friendly chars
	text = re.sub(r"[^a-z0-9\-]+", "", text)
	text = re.sub(r"-{2,}", "-", text).strip("-")
	return text

@dataclass
class OpetPriceRow:
	label: str
	value: str

@dataclass
class OpetDistrictRow:
	name: str  # İlçe adı
	values: List[OpetPriceRow]

def _extract_table_headers(table_locator) -> List[str]:
	header_cells = table_locator.locator("thead tr th")
	hc = header_cells.count()
	headers: List[str] = []
	for i in range(hc):
		text = header_cells.nth(i).inner_text().replace("\n", " ").replace("\r", " ").strip()
		# Normalize multiple spaces
		text = " ".join(text.split())
		headers.append(text)
	return headers

def _extract_district_rows(table_locator, headers: List[str]) -> List[OpetDistrictRow]:
	"""Extract district rows when the first header is İlçe. Returns list per district with labeled values."""
	rows = table_locator.locator("tbody tr")
	rc = rows.count()
	results: List[OpetDistrictRow] = []
	for i in range(rc):
		row = rows.nth(i)
		tds = row.locator("td")
		if tds.count() < 2:
			continue
		# İlçe adı
		try:
			first_td = tds.nth(0)
			span_auto = first_td.locator("span.ml-auto")
			if span_auto.count() > 0:
				district_name = span_auto.last.inner_text().strip()
			else:
				district_name = first_td.inner_text().strip()
		except Exception:
			district_name = ""
		values: List[OpetPriceRow] = []
		num_cols = min(len(headers), tds.count())
		for col_idx in range(1, num_cols):
			label = headers[col_idx]
			try:
				cell = tds.nth(col_idx)
				span_val = cell.locator("span.ml-auto")
				if span_val.count() > 0:
					value = span_val.last.inner_text().strip()
				else:
					value = cell.inner_text().strip()
			except Exception:
				value = ""
			values.append(OpetPriceRow(label=label, value=value))
		results.append(OpetDistrictRow(name=district_name, values=values))
	return results

def _extract_city_values(table_locator, city_name: str, headers: List[str]) -> List[OpetPriceRow]:
	rows = table_locator.locator("tbody tr")
	rc = rows.count()
	for i in range(rc):
		row = rows.nth(i)
		tds = row.locator("td")
		if tds.count() < 2:
			continue
		try:
			spans = tds.nth(0).locator("span.ml-auto")
			if spans.count() > 0:
				city_text = spans.last.inner_text().strip()
			else:
				city_text = tds.nth(0).inner_text().strip()
		except Exception:
			city_text = ""
		if city_text.upper() != city_name.upper():
			continue
		# Found the row: build label->value pairs using headers
		result: List[OpetPriceRow] = []
		num_cols = min(len(headers), tds.count())
		for col_idx in range(1, num_cols):  # include KDV and onwards, skip first "İl" header
			label = headers[col_idx]
			try:
				val_spans = tds.nth(col_idx).locator("span.ml-auto")
				if val_spans.count() > 0:
					value = val_spans.last.inner_text().strip()
				else:
					value = tds.nth(col_idx).inner_text().strip()
			except Exception:
				value = ""
			result.append(OpetPriceRow(label=label, value=value))
		return result
	# If not found, return empty; caller may fallback
	return []

def _write_opet_prices_to_text(city_name: str, prices: List[OpetPriceRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append(f"{city_name}")
	for p in prices:
		lines.append(f"{p.label}: {p.value}")
	output_file.write_text("\n".join(lines), encoding="utf-8")

def _write_opet_districts_to_text(city_name: str, headers: List[str], districts: List[OpetDistrictRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append(f"{city_name}")
	labels = headers[1:] if len(headers) > 1 else []
	for d in districts:
		parts = [d.name]
		for idx, label in enumerate(labels):
			val = d.values[idx].value if idx < len(d.values) else ""
			parts.append(f"{label}: {val}")
		lines.append(" | ".join(parts))
	output_file.write_text("\n".join(lines), encoding="utf-8")

def save_city_prices_txt(city_name: str, output_dir: Path, url: str = OPET_URL, debug: bool = False, verbose: bool = False) -> Path:
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
		# Find city select and choose
		page.wait_for_timeout(500)
		select_handle = _find_city_select(page)
		if select_handle is None:
			# try clicking any select-like container to reveal selects dynamically
			try:
				page.locator("select").first.scroll_into_view_if_needed()
			except Exception:
				pass
			select_handle = _find_city_select(page)
		if select_handle is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		# Get options and find matching by text
		options = _get_city_options_from_select(select_handle)
		if verbose:
			print(f"Opet: {len(options)} seçenek bulundu.")
		target = None
		for o in options:
			if (o["text"] or "").strip().upper() == city_name.upper():
				target = o
				break
		if target is None:
			# fallback: partial contains
			for o in options:
				if city_name.upper() in (o["text"] or "").strip().upper():
					target = o
					break
		if target is None:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		_select_option_with_fallback(page, select_handle, target["value"])
		# Wait for navigation or header update
		slug = _slugify_city(city_name)
		try:
			page.wait_for_url(f"**/akaryakit-fiyatlari/{slug}*", timeout=12000)
			page.wait_for_load_state("networkidle")
		except Exception:
			try:
				page.wait_for_function(
					"""(expected)=>{
						var el=document.querySelector('.FuelPrice-module_fuelPriceHeader--daa p.big');
						return !!el && el.textContent && el.textContent.trim().toUpperCase()===String(expected).toUpperCase();
					}""",
					city_name,
					timeout=12000
				)
			except Exception:
				pass
		page.wait_for_timeout(800)
		# Wait table populate
		table = _wait_prices_table(page, timeout=12000)
		page.wait_for_timeout(500)
		headers = _extract_table_headers(table)
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"opet_{city_name}_prices.txt"
		if headers and ("İlçe" in headers[0] or "Ilçe" in headers[0] or "ILÇE" in headers[0].upper()):
			districts = _extract_district_rows(table, headers)
			_write_opet_districts_to_text(city_name, headers, districts, fp)
		else:
			prices = _extract_city_values(table, city_name, headers)
			_write_opet_prices_to_text(city_name, prices, fp)
		browser.close()
		return fp

def save_all_cities_prices_txt(output_dir: Path, url: str = OPET_URL, debug: bool = False, min_delay: float = 0.6, max_delay: float = 1.2, verbose: bool = False) -> List[Path]:
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
		page.wait_for_timeout(500)
		# Iterate cities from select and fetch district table per city
		select_handle = _find_city_select(page)
		if select_handle is None:
			try:
				page.locator("select").first.scroll_into_view_if_needed()
			except Exception:
				pass
			select_handle = _find_city_select(page)
		if select_handle is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = _get_city_options_from_select(select_handle)
		if verbose:
			print(f"Opet: {len(options)} seçenek bulundu.")
		for o in options:
			try:
				# select city
				_select_option_with_fallback(page, select_handle, o["value"])
				# Wait for route or header change
				city_name = (o["text"] or "").strip()
				slug = _slugify_city(city_name)
				try:
					page.wait_for_url(f"**/akaryakit-fiyatlari/{slug}*", timeout=12000)
					page.wait_for_load_state("networkidle")
				except Exception:
					try:
						page.wait_for_function(
							"""(expected)=>{
								var el=document.querySelector('.FuelPrice-module_fuelPriceHeader--daa p.big');
								return !!el && el.textContent && el.textContent.trim().toUpperCase()===String(expected).toUpperCase();
							}""",
							city_name,
							timeout=12000
						)
					except Exception:
						pass
				page.wait_for_timeout(800)
				table = _wait_prices_table(page, timeout=12000)
				page.wait_for_timeout(500)
				headers = _extract_table_headers(table)
				if verbose:
					print(f"Opet: {city_name} headers -> {headers}")
				fp = output_dir / f"opet_{city_name}_prices.txt"
				if headers and ("İlçe" in headers[0] or "Ilçe" in headers[0] or "ILÇE" in headers[0].upper()):
					districts = _extract_district_rows(table, headers)
					_write_opet_districts_to_text(city_name, headers, districts, fp)
				else:
					prices = _extract_city_values(table, city_name, headers)
					_write_opet_prices_to_text(city_name, prices, fp)
				if verbose:
					print(f"OK: {city_name} -> {fp.name}")
				saved.append(fp)
			except Exception as e:
				if verbose:
					print(f"Hata/atlandı: {o.get('text')} -> {e}")
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		browser.close()
	return saved


