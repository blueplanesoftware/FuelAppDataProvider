from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re

SAHOIL_URL = "https://sahhoil.com.tr/tr/akaryakit-fiyatlari"


def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _find_city_select(page):
	# On sample HTML the city select is: select[name="il"]
	sel = page.locator('select[name="il"]')
	if sel.count() > 0:
		return sel.first
	# fallback: any select with many uppercase city options
	selects = page.locator("select")
	cnt = selects.count()
	for i in range(cnt):
		s = selects.nth(i)
		try:
			opts = s.evaluate("el => Array.from(el.options).map(o => (o.textContent||'').trim())")
			if opts and len(opts) >= 20 and any(x.upper() == "ADANA" for x in opts):
				return s
		except Exception:
			continue
	return None


def _select_city_and_submit(page, select_handle, value: str) -> None:
	# The form uses onchange=this.form.submit(). select then wait for navigation
	select_handle.select_option(value)
	try:
		page.wait_for_load_state("networkidle", timeout=15000)
	except Exception:
		page.wait_for_timeout(800)


@dataclass
class SahoilDistrictRow:
	name: str
	benzin: str
	motorin: str

def _is_istanbul_variant(text: str) -> bool:
	up = (text or "").strip().upper()
	return up.startswith("ISTANBUL")

def _dedupe_districts(rows: List[SahoilDistrictRow]) -> List[SahoilDistrictRow]:
	seen = set()
	out: List[SahoilDistrictRow] = []
	for r in rows:
		key = (r.name or "").strip().upper()
		if not key or key in seen:
			continue
		seen.add(key)
		out.append(r)
	return out

def _extract_district_table(page) -> List[SahoilDistrictRow]:
	# Prefer the specific table classes present in the site
	tables = page.locator("table.table.table-striped.table-hover")
	if tables.count() == 0:
		tables = page.locator("table.table-striped.table-hover, table")
	tc = tables.count()
	for i in range(tc):
		tb = tables.nth(i)
		# Basic header check (thead may use td instead of th)
		head_text = ""
		try:
			head_text = tb.locator("thead").inner_text().upper()
		except Exception:
			try:
				# Sometimes headers are first row in tbody
				head_text = tb.locator("tbody tr").first.inner_text().upper()
			except Exception:
				pass
		if ("BENZ" in head_text or "KURŞUNSUZ" in head_text or "KURSUNSUZ" in head_text) and ("MOTOR" in head_text or "MOTORİN" in head_text or "MOTORIN" in head_text):
			try:
				rows = tb.locator("tbody tr")
			except Exception:
				continue
			rc = rows.count()
			results: List[SahoilDistrictRow] = []
			for r in range(rc):
				tr = rows.nth(r)
				tds = tr.locator("td")
				if tds.count() < 3:
					continue
				def cell(idx: int) -> str:
					try:
						txt = tds.nth(idx).inner_text().replace("\xa0", " ").strip()
						return re.sub(r"\s{2,}", " ", txt)
					except Exception:
						return ""
				name = cell(0)
				benzin = cell(1)
				motorin = cell(2)
				# Skip header-like or empty rows
				if not name or any(k in name.upper() for k in ["KURŞUNSUZ", "MOTOR", "KURSUNSUZ"]):
					continue
				results.append(SahoilDistrictRow(name=name, benzin=benzin, motorin=motorin))
			if results:
				return results
	return []


def _write_city_file(city_name: str, districts: List[SahoilDistrictRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append(city_name)
	for d in districts:
		lines.append(f"{d.name} | Benzin: {d.benzin} | Motorin: {d.motorin}")
	output_file.write_text("\n".join(lines), encoding="utf-8")


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = SAHOIL_URL, debug: bool = False) -> Path:
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
		city_sel = _find_city_select(page)
		if city_sel is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		# Find option by text (exact/contains)
		options: List[Dict[str, str]] = city_sel.evaluate(
			"s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() }))"
		)
		targets: List[Dict[str, str]] = []
		# İstanbul tek dosya: iki varyant varsa ikisini de ekle
		if _is_istanbul_variant(city_name):
			targets = [o for o in options if _is_istanbul_variant(o.get("text") or "")]
		if not targets:
			# exact
			for o in options:
				if (o.get("text") or "").strip().upper() == city_name.strip().upper():
					targets = [o]
					break
		if not targets:
			# contains
			for o in options:
				if city_name.strip().upper() in (o.get("text") or "").strip().upper():
					targets = [o]
					break
		if not targets:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		# Collect districts across one or more targets (İstanbul)
		merged: List[SahoilDistrictRow] = []
		for t in targets:
			_select_city_and_submit(page, city_sel, t.get("value") or "")
			try:
				page.wait_for_selector("table.table.table-striped.table-hover tbody tr", timeout=12000)
			except Exception:
				pass
			merged.extend(_extract_district_table(page))
		districts = _dedupe_districts(merged)
		output_dir.mkdir(parents=True, exist_ok=True)
		final_city = "ISTANBUL" if _is_istanbul_variant(city_name) else city_name
		fp = output_dir / f"sahoil_{final_city}_prices.txt"
		_write_city_file(final_city, districts, fp)
		browser.close()
		return fp


def save_all_cities_prices_txt(output_dir: Path, url: str = SAHOIL_URL, debug: bool = False, min_delay: float = 0.6, max_delay: float = 1.2) -> List[Path]:
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
		city_sel = _find_city_select(page)
		if city_sel is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options: List[Dict[str, str]] = city_sel.evaluate("s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() }))")
		options = [o for o in options if (o.get('value') or '').strip()]
		output_dir.mkdir(parents=True, exist_ok=True)
		istanbul_rows: List[SahoilDistrictRow] = []
		for o in options:
			try:
				# Reload base page each iteration to avoid stale handles after submit refresh
				page.goto(url, wait_until="domcontentloaded")
				try:
					page.wait_for_load_state("networkidle", timeout=8000)
				except Exception:
					pass
				_ensure_cookie_accepted(page)
				city_sel = _find_city_select(page)
				if city_sel is None:
					raise RuntimeError("Şehir seçimi için select bulunamadı.")
				_select_city_and_submit(page, city_sel, o.get("value") or "")
				# Wait table rows appear
				try:
					page.wait_for_selector("table.table.table-striped.table-hover tbody tr", timeout=12000)
				except Exception:
					pass
				districts = _extract_district_table(page)
				city_text = (o.get("text") or "").strip()
				if _is_istanbul_variant(city_text):
					istanbul_rows.extend(districts)
				else:
					fp = output_dir / f"sahoil_{city_text}_prices.txt"
					_write_city_file(city_text, districts, fp)
					saved.append(fp)
			except Exception as e:
				print(f"Hata/atlandı: {o.get('text')} -> {e}")
			page.wait_for_timeout(800)
		# Write merged İstanbul if any
		if istanbul_rows:
			merged = _dedupe_districts(istanbul_rows)
			fp_ist = output_dir / "sahoil_ISTANBUL_prices.txt"
			_write_city_file("ISTANBUL", merged, fp_ist)
			saved.append(fp_ist)
		browser.close()
	return saved


