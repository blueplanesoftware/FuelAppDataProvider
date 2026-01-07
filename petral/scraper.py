from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
from playwright.sync_api import sync_playwright
import math
import re

PETRALL_FUEL_URL = "https://petrall.com.tr/fuelBring"


@dataclass
class PetrallRow:
	city: str
	district: str
	diesel: str
	gasoline: str
	heatingoil: str
	fueloil: str


def _fetch_page(request_ctx, page: int, page_size: int = 10) -> Tuple[List[PetrallRow], Dict]:
	resp = request_ctx.get(PETRALL_FUEL_URL, params={"page": page, "page_size": page_size})
	# Playwright APIResponse doesn't have raise_for_status; check ok()/status
	if not resp.ok:
		try:
			body = resp.text()
		except Exception:
			body = ""
		raise RuntimeError(f"HTTP {resp.status}: {body[:200]}")
	try:
		js = resp.json()
	except Exception:
		js = {}
	data = js.get("data", []) or []
	rows: List[PetrallRow] = []
	for item in data:
		rows.append(
			PetrallRow(
				city=(item.get("city") or "").strip(),
				district=(item.get("district") or " - ").strip(),
				diesel=(item.get("diesel") or "").strip(),
				gasoline=(item.get("gasoline") or "").strip(),
				heatingoil=(item.get("heatingoil") or "").strip(),
				fueloil=(item.get("fueloil") or "").strip(),
			)
		)
	return rows, js.get("pagination") or {}


def _write_city_file(city_name: str, rows: List[PetrallRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append(city_name)
	for r in rows:
		# İlçe adı sadece "-" ise yazma
		dname = (r.district or "").strip()
		if dname == "-":
			continue
		lines.append(
			f"{r.district} | Motorin: {r.diesel} | Kurşunsuz 95: {r.gasoline} | Kalorifer Yakıtı: {r.heatingoil} | Fuel Oil: {r.fueloil}"
		)
	output_file.write_text("\n".join(lines), encoding="utf-8")

def _is_istanbul_variant(name: str) -> bool:
	up = (name or "").strip().upper()
	return up.startswith("ISTANBUL") or up.startswith("İSTANBUL")

def _normalize_city_key(name: str) -> str:
	n = (name or "").strip()
	if _is_istanbul_variant(n):
		return "İstanbul"
	return n

def _safe_filename_city(name: str) -> str:
	# Windows illegal chars: \ / : * ? " < > |
	n = re.sub(r'[\\/:*?"<>|]+', "-", name).strip()
	# collapse spaces and dashes
	n = re.sub(r"\s{2,}", " ", n)
	n = re.sub(r"-{2,}", "-", n)
	return n


def save_all_cities_prices_txt(output_dir: Path, debug: bool = False, page_size: int = 10) -> List[Path]:
	"""
	Petrall fuelBring endpoint'ini sayfa sayfa çağırıp tüm satırları topla,
	şehir adına göre gruplandır ve her şehir için bir txt yaz.
	"""
	saved: List[Path] = []
	with sync_playwright() as p:
		request_ctx = p.request.new_context(
			extra_http_headers={
				"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
				"Referer": "https://petrall.com.tr/fuel",
				"Accept": "application/json, text/plain, */*",
			}
		)
		# İlk sayfayı çek, toplam sayfa bilgisi al
		all_rows: List[PetrallRow] = []
		rows, pagination = _fetch_page(request_ctx, 1, page_size=page_size)
		all_rows.extend(rows)
		last_page = int(pagination.get("last_page") or 1)
		# Güvenlik: eğer pagination bilgisi yoksa, örneğe göre 102 sayfa varsay
		if not pagination:
			last_page = 102
		# Kalan sayfaları çek
		for pg in range(2, last_page + 1):
			rows, _ = _fetch_page(request_ctx, pg, page_size=page_size)
			all_rows.extend(rows)
		# Şehirlere göre grupla (İstanbul varyantlarını tek anahtar altında topla)
		city_map: Dict[str, List[PetrallRow]] = {}
		for r in all_rows:
			if not r.city:
				continue
			key = _normalize_city_key(r.city)
			city_map.setdefault(key, []).append(r)
		# Yaz
		output_dir.mkdir(parents=True, exist_ok=True)
		for city, rows in city_map.items():
			city_filename = _safe_filename_city(city)
			fp = output_dir / f"petral_{city_filename}_prices.txt"
			_write_city_file(city, rows, fp)
			saved.append(fp)
	return saved


def save_city_prices_txt(city_name: str, output_dir: Path, debug: bool = False, page_size: int = 10) -> Path:
	"""
	Belirli bir şehir için tüm sayfaları tarayıp sadece o şehrin satırlarını topla ve tek txt yaz.
	"""
	with sync_playwright() as p:
		request_ctx = p.request.new_context(
			extra_http_headers={
				"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
				"Referer": "https://petrall.com.tr/fuel",
				"Accept": "application/json, text/plain, */*",
			}
		)
		# İlk sayfayı çek
		target_rows: List[PetrallRow] = []
		rows, pagination = _fetch_page(request_ctx, 1, page_size=page_size)
		last_page = int(pagination.get("last_page") or 1) if pagination else 102
		def _match_city(rcity: str, target: str) -> bool:
			if _is_istanbul_variant(target) or target.strip().upper() in ["ISTANBUL", "İSTANBUL"]:
				return _is_istanbul_variant(rcity)
			ru = (rcity or "").strip().upper()
			tu = (target or "").strip().upper()
			return ru == tu or (ru in tu) or (tu in ru)
		for r in rows:
			if _match_city(r.city, city_name):
				target_rows.append(r)
		# Kalan sayfalar
		for pg in range(2, last_page + 1):
			rows, _ = _fetch_page(request_ctx, pg, page_size=page_size)
			for r in rows:
				if _match_city(r.city, city_name):
					target_rows.append(r)
		if not target_rows:
			raise RuntimeError(f"Şehir bulunamadı veya veri yok: {city_name}")
		output_dir.mkdir(parents=True, exist_ok=True)
		final_city = _normalize_city_key(city_name)
		fp = output_dir / f"petral_{_safe_filename_city(final_city)}_prices.txt"
		_write_city_file(final_city, target_rows, fp)
		return fp


