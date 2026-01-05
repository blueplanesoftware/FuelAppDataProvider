from pathlib import Path
from typing import List
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random
import re
from dataclasses import dataclass

SHELL_URL = "https://www.shell.com.tr/suruculer/shell-yakitlari/akaryakit-pompa-satis-fiyatlari.html"

def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass

def _find_prices_frame(page):
	"""Try to find the iframe that contains the DevExpress province dropdown/list."""
	# Quick pass: if elements exist on main page, use page itself
	if page.locator('td.dxeListBoxItem, .dxeButtonEdit, td.dxeButtonEdit, #cb_all_cb_province_I, #cb_all_cb_province_B-1').count() > 0:
		return page
	# Prefer frame by URL
	target = page.wait_for_event("frameattached", timeout=5000)
	for _ in range(8):
		frame_by_url = page.frame(url=re.compile(r"turkiyeshell\.com/.+pompa", re.I))
		if frame_by_url:
			return frame_by_url
		page.wait_for_timeout(300)
	# Otherwise probe frames
	for _ in range(6):
		for frame in page.frames:
			try:
				if frame.locator('td.dxeListBoxItem, .dxeButtonEdit, td.dxeButtonEdit, #cb_all_cb_province_I, #cb_all_cb_province_B-1').count() > 0:
					return frame
			except Exception:
				continue
		page.wait_for_timeout(300)
	# Fallback: main page
	return page

def _open_dropdown_via_devexpress(scope) -> None:
	# Try DevExpress client-side API to open the dropdown
	try:
		scope.evaluate("""(name) => {
			try {
				if (window.ASPxClientControl && ASPxClientControl.GetControlCollection) {
					var c = ASPxClientControl.GetControlCollection().GetByName(name);
					if (c && c.ShowDropDown) c.ShowDropDown();
				}
			} catch (e) {}
		}""", "cb_all_cb_province")
	except Exception:
		pass

def _open_province_dropdown(scope) -> None:
	# Try a few likely selectors to open the DevExpress combo dropdown
	candidates = [
		'#cb_all_cb_province_B-1',  # dropdown button id pattern
		'#cb_all_cb_province_I',    # input area
		'td.dxeButtonEdit',         # devexpress button-edit cell
		'.dxeButtonEdit',           # generic class
	]
	for sel in candidates:
		loc = scope.locator(sel)
		if loc.count() > 0 and loc.first.is_visible():
			try:
				loc.first.scroll_into_view_if_needed()
			except Exception:
				pass
			loc.first.click()
			return
	# Fallback: click anywhere on the button edit if present
	scope.locator('.dxeButtonEdit, td.dxeButtonEdit').first.click()
	# As a last resort, use DevExpress API
	_open_dropdown_via_devexpress(scope)
	# Give time for dropdown to render
	try:
		scope.locator('td.dxeListBoxItem').first.wait_for(state="visible", timeout=3000)
	except Exception:
		pass

def _click_city_in_list(scope, city_name: str) -> None:
	# Ensure dropdown is open, then click the list item by text
	try:
		if not scope.locator('td.dxeListBoxItem').first.is_visible():
			_open_province_dropdown(scope)
	except Exception:
		_open_province_dropdown(scope)
	# Prefer filter(has_text=...) for robustness
	item = scope.locator('td.dxeListBoxItem').filter(has_text=city_name).first
	try:
		item.wait_for(state="visible", timeout=4000)
	except Exception:
		# Try to open via DevExpress and wait again
		_open_dropdown_via_devexpress(scope)
		try:
			item.wait_for(state="visible", timeout=4000)
		except Exception:
			pass
	try:
		item.click()
	except Exception:
		# Fallback: select via DevExpress client-side API
		try:
			scope.evaluate("""(name, text) => {
				try {
					if (window.ASPxClientControl && ASPxClientControl.GetControlCollection) {
						var c = ASPxClientControl.GetControlCollection().GetByName(name);
						if (c) {
							var it = c.FindItemByText && c.FindItemByText(text);
							if (it) {
								if (c.SelectItem) c.SelectItem(it.index);
								if (c.HideDropDown) c.HideDropDown();
								if (c.RaiseValueChanged) c.RaiseValueChanged();
							}
						}
					}
				} catch (e) {}
			}""", "cb_all_cb_province", city_name)
		except Exception:
			# Last attempt: type into input then press Enter
			try:
				inp = scope.locator('#cb_all_cb_province_I')
				if inp.count() > 0:
					inp.first.fill(city_name)
					inp.first.press("Enter")
			except Exception:
				pass

@dataclass
class ShellPriceRow:
	name: str  # İl/İlçe
	benzin_95: str
	motorin: str
	gazyagi: str
	kalyak: str
	fuel_oil_high: str
	fuel_oil: str
	autogas: str

def _extract_prices_from_scope(scope) -> List[ShellPriceRow]:
	rows = scope.locator("#cb_all_grdPrices_DXMainTable tr.dxgvDataRow")
	count = rows.count()
	results: List[ShellPriceRow] = []
	for i in range(count):
		tds = rows.nth(i).locator("td")
		# Expecting 8 columns as per headers
		def cell(idx: int) -> str:
			try:
				return tds.nth(idx).inner_text().strip()
			except Exception:
				return "-"
		results.append(
			ShellPriceRow(
				name=cell(0),
				benzin_95=cell(1),
				motorin=cell(2),
				gazyagi=cell(3),
				kalyak=cell(4),
				fuel_oil_high=cell(5),
				fuel_oil=cell(6),
				autogas=cell(7),
			)
		)
	return results

def _write_shell_prices_to_text(prices: List[ShellPriceRow], output_file: Path) -> None:
	lines: List[str] = []
	for p in prices:
		lines.append(
			f"{p.name} | K.Benzin 95 Oktan: {p.benzin_95} | Motorin: {p.motorin} | Gaz Yağı: {p.gazyagi} | "
			f"Kalyak: {p.kalyak} | Yüksek Kükürtlü Fuel Oil: {p.fuel_oil_high} | Fuel Oil: {p.fuel_oil} | Otogaz: {p.autogas}"
		)
	output_file.write_text("\n".join(lines), encoding="utf-8")

def save_city_prices_txt(city_name: str, output_dir: Path, url: str = SHELL_URL, debug: bool = False) -> Path:
	"""Open Shell prices page, select given city, extract price table, and write txt (no HTML)."""
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
		_ensure_cookie_accepted(page)
		scope = _find_prices_frame(page)
		_open_province_dropdown(scope)
		try:
			scope.wait_for_selector('td.dxeListBoxItem', timeout=8000)
		except Exception:
			pass
		_click_city_in_list(scope, city_name)
		# Wait first cell in grid to reflect selected city (best-effort)
		try:
			for _ in range(20):
				first_cell = scope.locator("#cb_all_grdPrices_DXMainTable tr.dxgvDataRow td").first
				if first_cell.count() > 0 and city_name.upper() in first_cell.inner_text().upper():
					break
				scope.wait_for_timeout(300)
		except Exception:
			pass
		scope.wait_for_timeout(600)
		prices = _extract_prices_from_scope(scope)
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"shell_{city_name}_prices.txt"
		_write_shell_prices_to_text(prices, fp)
		browser.close()
		return fp

def save_all_cities_prices_txt(output_dir: Path, url: str = SHELL_URL, debug: bool = False, min_delay: float = 0.6, max_delay: float = 1.4, retries: int = 1) -> List[Path]:
	"""Open Shell prices page, iterate all cities, write per-city txt files to output_dir."""
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
		_ensure_cookie_accepted(page)
		output_dir.mkdir(parents=True, exist_ok=True)
		scope = _find_prices_frame(page)
		_open_province_dropdown(scope)
		city_names: List[str] = scope.eval_on_selector_all(
			'td.dxeListBoxItem',
			'els => els.map(e => (e.textContent || "").trim()).filter(Boolean)'
		)
		for name in city_names:
			for attempt in range(retries + 1):
				try:
					_open_province_dropdown(scope)
					_click_city_in_list(scope, name)
					# Wait grid reflects selected city
					try:
						for _ in range(20):
							first_cell = scope.locator("#cb_all_grdPrices_DXMainTable tr.dxgvDataRow td").first
							if first_cell.count() > 0 and name.upper() in first_cell.inner_text().upper():
								break
							scope.wait_for_timeout(300)
					except Exception:
						pass
					scope.wait_for_timeout(600)
					prices = _extract_prices_from_scope(scope)
					fp = output_dir / f"shell_{name}_prices.txt"
					_write_shell_prices_to_text(prices, fp)
					saved.append(fp)
					print(f"OK: {name} -> {fp.name}")
					break
				except PWTimeoutError:
					if attempt < retries:
						scope.wait_for_timeout(int(600 * (attempt + 1) * random.uniform(1.0, 1.4)))
						continue
					else:
						print(f"Atlandı (timeout): {name}")
				except Exception as e:
					if attempt < retries:
						scope.wait_for_timeout(int(500 * (attempt + 1) * random.uniform(1.0, 1.3)))
						continue
					else:
						print(f"Hata/atlandı: {name} -> {e}")
			scope.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		browser.close()
	return saved

