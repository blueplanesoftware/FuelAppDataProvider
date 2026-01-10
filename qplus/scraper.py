from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re

QPLUS_URL = "https://www.qplus.com.tr/tr/akaryakit-fiyatlari"


def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _find_city_select(page):
	# QPlus uses select#il inside form.fuel
	sel = page.locator("select#il")
	if sel.count() > 0:
		return sel.first
	# Fallback to heuristic
	return page.locator("select").first


def _get_options(select_handle) -> List[Dict[str, str]]:
	if select_handle is None:
		return []
	return select_handle.evaluate(
		"s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() }))"
	)


def _select_option(select_handle, value: str) -> None:
	try:
		select_handle.select_option(value)
		return
	except Exception:
		pass
	select_handle.evaluate(
		"(el, val)=>{ el.value=val; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }",
		value
	)


def _click_query(page) -> None:
	# QPlus button is button[name=sorgula]
	btn = page.locator('button[name="sorgula"]')
	if btn.count() == 0:
		# Fallback: any button containing SORGULA
		btn = page.get_by_role("button", name=re.compile(r"sorgula", re.I))
		if btn.count() == 0:
			btn = page.locator("button, input[type=submit]").filter(has_text=re.compile(r"sorgula", re.I))
	if btn.count() == 0:
		btn = page.locator("button, input[type=submit]")
	handle = btn.first
	try:
		handle.scroll_into_view_if_needed()
	except Exception:
		pass
	try:
		handle.click()
	except Exception:
		handle.click(force=True)


@dataclass
class QPlusPrice:
	city: str
	benzin: str
	motorin: str
	lpg: str


def _wait_results(page, timeout_ms: int = 12000) -> None:
	# QPlus injects response HTML into div.html as a list (<ul><li>...</li>...)
	try:
		# Wait for at least 3 li elements under .html (Il, Tarih, Benzin)
		page.wait_for_function(
			"""() => {
				const c = document.querySelector('div.html');
				if (!c) return false;
				const li = c.querySelectorAll('ul li');
				return li && li.length >= 3;
			}""",
			timeout=timeout_ms
		)
	except Exception:
		page.wait_for_timeout(800)
	page.wait_for_load_state("networkidle")
	page.wait_for_timeout(200)


def _extract_city_prices(page, fallback_city: str) -> Optional[QPlusPrice]:
	# Read values from div.html -> <ul><li>Il</li><li>Tarih</li><li>Benzin</li><li>Motorin</li><li>LPG</li><li>QPLUS Max</li><li>Para Birimi</li>
	container = page.locator("div.html")
	if container.count() == 0:
		return None
	try:
		lis = container.locator("ul li")
		if lis.count() < 3:
			return None
		vals: List[str] = []
		for i in range(min(7, lis.count())):
			try:
				vals.append(lis.nth(i).inner_text().strip())
			except Exception:
				vals.append("")
		city = (vals[0] if len(vals) > 0 and vals[0] else fallback_city).strip()
		benzin = vals[2] if len(vals) > 2 else ""
		motorin = vals[3] if len(vals) > 3 else ""
		lpg = vals[4] if len(vals) > 4 else ""
		return QPlusPrice(city=city, benzin=benzin, motorin=motorin, lpg=lpg)
	except Exception:
		return None


def _is_istanbul_variant(name: str) -> bool:
	up = (name or "").strip().upper()
	return up.startswith("ISTANBUL") or up.startswith("İSTANBUL")

def _is_default_city_text(text: str) -> bool:
	up = (text or "").strip().upper()
	# Common variants
	return up in {"IL SECINIZ", "İL SEÇİNİZ", "İL SECİNİZ", "IL SEÇİNİZ"}


def _normalize_city(name: str) -> str:
	n = (name or "").strip()
	if _is_istanbul_variant(n):
		return "İstanbul"
	return n


def _safe_city_for_filename(name: str) -> str:
	n = re.sub(r'[\\/:*?"<>|]+', "-", name).strip()
	n = re.sub(r"\s{2,}", " ", n)
	n = re.sub(r"-{2,}", "-", n)
	return n


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = QPLUS_URL, debug: bool = False) -> Path:
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
		page.wait_for_timeout(400)
		city_sel = _find_city_select(page)
		if city_sel is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = _get_options(city_sel)
		# Find target option (exact, then contains)
		target = None
		for o in options:
			if (o.get("text") or "").strip().upper() == city_name.strip().upper():
				target = o
				break
		if target is None:
			for o in options:
				if city_name.strip().upper() in (o.get("text") or "").strip().upper():
					target = o
					break
		if target is None:
			raise RuntimeError(f"Şehir bulunamadı: {city_name}")
		_select_option(city_sel, target.get("value") or "")
		_click_query(page)
		_wait_results(page, timeout_ms=12000)
		price = _extract_city_prices(page, fallback_city=(target.get("text") or city_name).strip())
		if price is None:
			price = QPlusPrice(city=(target.get("text") or city_name).strip(), benzin="", motorin="", lpg="")
		# Skip default option if somehow captured
		if _is_default_city_text(price.city):
			raise RuntimeError("Geçersiz şehir seçimi (İl Seçiniz) yakalandı.")
		# Write file
		final_city = _normalize_city(price.city)
		output_dir.mkdir(parents=True, exist_ok=True)
		fp = output_dir / f"qplus_{_safe_city_for_filename(final_city)}_prices.txt"
		lines: List[str] = []
		lines.append(final_city)
		lines.append(f"Benzin: {price.benzin} | Motorin: {price.motorin} | LPG: {price.lpg}")
		fp.write_text("\n".join(lines), encoding="utf-8")
		browser.close()
		return fp


def save_all_cities_prices_txt(output_dir: Path, url: str = QPLUS_URL, debug: bool = False, min_delay: float = 0.5, max_delay: float = 1.1) -> List[Path]:
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
		page.wait_for_timeout(300)
		city_sel = _find_city_select(page)
		if city_sel is None:
			raise RuntimeError("Şehir seçimi için select bulunamadı.")
		options = _get_options(city_sel)
		# Filter out default/empty
		opts = [o for o in options if (o.get("value") or "").strip() and not _is_default_city_text(o.get("text") or "")]
		istanbul_prices: List[QPlusPrice] = []
		output_dir.mkdir(parents=True, exist_ok=True)
		for o in opts:
			try:
				_select_option(city_sel, o.get("value") or "")
				_click_query(page)
				_wait_results(page, timeout_ms=12000)
				price = _extract_city_prices(page, fallback_city=(o.get("text") or "").strip())
				if price is None:
					price = QPlusPrice(city=(o.get("text") or "").strip(), benzin="", motorin="", lpg="")
				# Skip default option if somehow captured
				if _is_default_city_text(price.city):
					continue
				if _is_istanbul_variant(price.city):
					istanbul_prices.append(price)
					continue
				final_city = _normalize_city(price.city)
				fp = output_dir / f"qplus_{_safe_city_for_filename(final_city)}_prices.txt"
				lines = [final_city, f"Benzin: {price.benzin} | Motorin: {price.motorin} | LPG: {price.lpg}"]
				fp.write_text("\n".join(lines), encoding="utf-8")
				saved.append(fp)
			except Exception:
				continue
			page.wait_for_timeout(int(1000 * min_delay))
		# Merge İstanbul variants
		if istanbul_prices:
			final_city = "İstanbul"
			fp = output_dir / f"qplus_{_safe_city_for_filename(final_city)}_prices.txt"
			lines: List[str] = [final_city]
			for pr in istanbul_prices:
				lines.append(f"{pr.city} | Benzin: {pr.benzin} | Motorin: {pr.motorin} | LPG: {pr.lpg}")
			fp.write_text("\n".join(lines), encoding="utf-8")
			saved.append(fp)
		browser.close()
	return saved


