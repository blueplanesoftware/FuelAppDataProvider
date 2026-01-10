from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from playwright.sync_api import sync_playwright
import re

SEVEN_KITA_URL = "https://7kitadagitim.com/index.php/utts/fiyat/"


def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _safe_city_for_filename(name: str) -> str:
	n = (name or "").strip()
	# Remove illegal characters for Windows filenames
	n = re.sub(r'[\\/:*?"<>|]+', "-", n)
	n = re.sub(r"\s{2,}", " ", n)
	n = re.sub(r"-{2,}", "-", n)
	return n


@dataclass
class CityPriceRow:
	city: str
	values: Dict[str, str]  # label -> value


def _normalize_header_label(text: str) -> str:
	up = (text or "").strip().upper()
	up = up.replace("İ", "I")
	# Common mappings
	if "BENZ" in up or "KURSUNSUZ" in up:
		return "Benzin"
	if "BIYODIZEL" in up or "BIYODIZEL" in up or "B IYODIZEL" in up or "BIYODIZEL" in up or "BIYODIZEL" in up or "BIYODIZEL IHTIVA EDEN MOTORIN" in up or "B IYODIZEL IHTIVA EDEN MOTORIN" in up or "IHTIVA EDEN MOTORIN" in up:
		return "Motorin (Biyodizel)"
	if "MOTOR" in up or "DIESEL" in up or "DIZEL" in up:
		return "Motorin"
	if "LPG" in up or "OTOGAZ" in up:
		return "LPG"
	if "KALORIFER" in up or "KAL-YAK" in up or "KALYAK" in up:
		return "Kalorifer Yakıtı"
	if "FUEL" in up:
		return "Fuel Oil"
	if "TARIH" in up:
		return "Tarih"
	if "ILCE" in up or "ILÇE" in up:
		return "İlçe"
	if "IL" in up:
		return "İl"
	return text.strip()


def _extract_all_rows(page) -> List[CityPriceRow]:
	# Target main price table: prefer #table_1 rendered by wpDataTables
	table = page.locator("#table_1")
	if table.count() == 0:
		table = page.locator("table.wpDataTable")
	if table.count() > 1:
		# pick the first that has at least 10 rows
		best = None
		for i in range(table.count()):
			tb = table.nth(i)
			try:
				rc = tb.locator("tbody tr").count()
			except Exception:
				rc = 0
			if rc >= 5:
				best = tb
				break
		if best is not None:
			table = best
		else:
			table = table.first
	else:
		table = table.first
	# Build header map
	header_cells = table.locator("thead tr").first.locator("th, td")
	hc = header_cells.count()
	header_labels: List[str] = []
	for i in range(hc):
		try:
			header_labels.append(_normalize_header_label(header_cells.nth(i).inner_text()))
		except Exception:
			header_labels.append("")
	# Identify city column index (prefer 'İl' or 'Şehir') then fallback 0
	city_idx = 0
	for idx, lbl in enumerate(header_labels):
		if lbl.strip().upper() in ["IL", "İL", "ŞEHİR", "SEHIR"]:
			city_idx = idx
			break
	# Collect rows
	rows = table.locator("tbody tr")
	rc = rows.count()
	results: List[CityPriceRow] = []
	skip_labels = {"Tarih"}
	for r in range(rc):
		tr = rows.nth(r)
		tds = tr.locator("td")
		if tds.count() == 0:
			continue
		def cell(idx: int) -> str:
			try:
				return tds.nth(idx).inner_text().replace("\xa0", " ").strip()
			except Exception:
				return ""
		city = cell(city_idx)
		if not city or city.upper() in {"IL", "İL"}:
			continue
		values: Dict[str, str] = {}
		for c in range(tds.count()):
			if c == city_idx:
				continue
			lbl = header_labels[c] if c < len(header_labels) else f"C{c}"
			norm_lbl = _normalize_header_label(lbl)
			if norm_lbl in skip_labels:
				continue
			val = cell(c)
			# Keep only meaningful labels
			if norm_lbl and val:
				values[norm_lbl] = val
		results.append(CityPriceRow(city=city, values=values))
	return results


def _write_city_file(row: CityPriceRow, output_file: Path) -> None:
	lines: List[str] = []
	lines.append(row.city)
	# Fixed order for consistency
	order = ["Benzin", "Motorin", "LPG", "Kalorifer Yakıtı", "Fuel Oil"]
	parts: List[str] = []
	for k in order:
		if k in row.values:
			parts.append(f"{k}: {row.values[k]}")
	# Append any remaining columns
	for k, v in row.values.items():
		if k not in order:
			parts.append(f"{k}: {v}")
	if parts:
		lines.append(" | ".join(parts))
	output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, url: str = SEVEN_KITA_URL, debug: bool = False) -> List[Path]:
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
		# Wait table present
		try:
			page.wait_for_function(
				"() => (document.querySelectorAll('#table_1 tbody tr').length || document.querySelectorAll('table.wpDataTable tbody tr').length) > 0",
				timeout=15000
			)
		except Exception:
			pass
		rows = _extract_all_rows(page)
		output_dir.mkdir(parents=True, exist_ok=True)
		for r in rows:
			fp = output_dir / f"7kita_{_safe_city_for_filename(r.city)}_prices.txt"
			_write_city_file(r, fp)
			saved.append(fp)
		browser.close()
	return saved


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = SEVEN_KITA_URL, debug: bool = False) -> Path:
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
		try:
			page.wait_for_selector("table tbody tr", timeout=12000)
		except Exception:
			pass
		rows = _extract_all_rows(page)
		target: Optional[CityPriceRow] = None
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
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"7kita_{_safe_city_for_filename(target.city)}_prices.txt"
		_write_city_file(target, fp)
		browser.close()
		return fp


