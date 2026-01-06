from pathlib import Path
from typing import List
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random

RPET_URL = "https://rpet.com.tr/yakit-fiyatlari/"


def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _find_prices_table(page):
	# Try specific id first
	t = page.locator("#wpdtSimpleTable-1")
	if t.count() > 0:
		return t.first
	# Fallback: any wpDataTables simple table on page
	t = page.locator("table.wpdtSimpleTable.wpDataTable")
	if t.count() > 0:
		return t.first
	# Last resort: any table under main content
	return page.locator("table").first


@dataclass
class RpetCityRow:
	city: str
	benzin: str
	motorin: str
	date: str


def _extract_rows(table_locator) -> List[RpetCityRow]:
	rows = table_locator.locator("tbody tr")
	rc = rows.count()
	results: List[RpetCityRow] = []
	for i in range(rc):
		tr = rows.nth(i)
		tds = tr.locator("td")
		if tds.count() < 4:
			continue
		def cell_text(idx: int) -> str:
			try:
				return tds.nth(idx).inner_text().replace("\xa0", " ").strip()
			except Exception:
				return ""
		results.append(
			RpetCityRow(
				city=cell_text(0),
				benzin=cell_text(1),
				motorin=cell_text(2),
				date=cell_text(3),
			)
		)
	return results


def _write_city_to_text(row: RpetCityRow, output_file: Path) -> None:
	lines: List[str] = []
	lines.append(f"{row.city}")
	lines.append(f"Benzin: {row.benzin} | Motorin: {row.motorin}")
	output_file.write_text("\n".join(lines), encoding="utf-8")

def _is_istanbul_variant(name: str) -> bool:
	up = (name or "").strip().upper()
	return up.startswith("ISTANBUL") or up.startswith("İSTANBUL")

def _write_istanbul_group_to_text(rows: List[RpetCityRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append("ISTANBUL")
	for r in rows:
		# Örneğin: ISTANBUL (ANADOLU) | Benzin: ... | Motorin: ... | Tarih: ...
		lines.append(f"{r.city} | Benzin: {r.benzin} | Motorin: {r.motorin}")
	output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, url: str = RPET_URL, debug: bool = False, min_delay: float = 0.5, max_delay: float = 1.1) -> List[Path]:
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
		table = _find_prices_table(page)
		page.wait_for_selector("tbody tr", timeout=15000)
		rows = _extract_rows(table)
		output_dir.mkdir(parents=True, exist_ok=True)
		# İstanbul'u tek dosyada birleştir
		istanbul_rows = [r for r in rows if _is_istanbul_variant(r.city)]
		other_rows = [r for r in rows if not _is_istanbul_variant(r.city)]
		if istanbul_rows:
			fp_ist = output_dir / "rpet_ISTANBUL_prices.txt"
			_write_istanbul_group_to_text(istanbul_rows, fp_ist)
			saved.append(fp_ist)
		for r in other_rows:
			fp = output_dir / f"rpet_{r.city}_prices.txt"
			_write_city_to_text(r, fp)
			saved.append(fp)
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		browser.close()
	return saved


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = RPET_URL, debug: bool = False) -> Path:
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
		table = _find_prices_table(page)
		page.wait_for_selector("tbody tr", timeout=15000)
		rows = _extract_rows(table)
		output_dir.mkdir(parents=True, exist_ok=True)
		# İstanbul isteği: iki yakanın tek dosyada birleştirilmesi
		if _is_istanbul_variant(city_name) or city_name.strip().upper() in ["ISTANBUL", "İSTANBUL"]:
			istanbul_rows = [r for r in rows if _is_istanbul_variant(r.city)]
			if not istanbul_rows:
				raise RuntimeError("İstanbul satırları bulunamadı.")
			fp = output_dir / "rpet_ISTANBUL_prices.txt"
			_write_istanbul_group_to_text(istanbul_rows, fp)
		else:
			# Tek şehir dosyası
			target = None
			for r in rows:
				if (r.city or "").strip().upper() == city_name.strip().upper():
					target = r
					break
			if target is None:
				for r in rows:
					if city_name.strip().upper() in (r.city or "").strip().upper():
						target = r
						break
			if target is None:
				raise RuntimeError(f"Şehir bulunamadı: {city_name}")
			fp = output_dir / f"rpet_{target.city}_prices.txt"
			_write_city_to_text(target, fp)
		browser.close()
		return fp


