from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import random

HYPCO_URL = "https://www.hypco.com.tr/tr/pompa-fiyatlari"


def _ensure_cookie_accepted(page) -> None:
	try:
		if page.locator("#onetrust-accept-btn-handler").is_visible():
			page.click("#onetrust-accept-btn-handler")
	except Exception:
		pass


def _el(page, sel: str):
	loc = page.locator(sel)
	return loc if loc.count() > 0 else None


def _get_select_options(select_handle) -> List[Dict[str, str]]:
	if select_handle is None:
		return []
	return select_handle.evaluate(
		"s => Array.from(s.options).map(o => ({ value: o.value, text: (o.textContent||'').trim() }))"
	)


def _select_option_with_events(select_handle, value: str) -> None:
	# Try native first
	try:
		select_handle.select_option(value)
		return
	except Exception:
		pass
	# Fallback to manual change
	select_handle.evaluate(
		"(el, val)=>{ el.value = val; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }",
		value
	)


def _click_show_button(page) -> None:
	# Button near selects: class "btn" with data-call-archive="1"
	btn = page.locator('button.btn[data-call-archive="1"]')
	if btn.count() == 0:
		btn = page.locator("button.btn")
	handle = btn.first
	try:
		handle.scroll_into_view_if_needed()
	except Exception:
		pass
	try:
		handle.click()
	except Exception:
		handle.click(force=True)


def _wait_results_loaded(page, timeout_ms: int = 15000) -> None:
	# Prefer waiting for #resultPrice DOM to change/populate
	try:
		page.wait_for_function(
			"""() => {
				const c = document.querySelector('#resultPrice');
				return !!c && c.innerHTML && c.innerHTML.trim().length > 20;
			}""",
			timeout=timeout_ms
		)
	except Exception:
		try:
			page.wait_for_selector("#resultPrice table tbody tr", timeout=int(timeout_ms / 2))
		except Exception:
			# Fallback: any visible table rows
			try:
				page.wait_for_selector("table tbody tr", timeout=int(timeout_ms / 2))
			except Exception:
				page.wait_for_timeout(800)
	page.wait_for_load_state("networkidle")
	page.wait_for_timeout(300)


@dataclass
class HypcoDistrictRow:
	name: str
	benzin: str
	motorin: str


def _is_istanbul_variant(name: str) -> bool:
	up = (name or "").strip().upper()
	return up.startswith("ISTANBUL") or up.startswith("İSTANBUL")


def _extract_prices_for_selected_district(page) -> Dict[str, str]:
	"""
	#resultPrice altında gösterilen tek ilçe fiyatını yakalamaya çalışır.
	Önce tablo benzeri satırlardan 'Benzin' ve 'Motorin' değerlerini arar,
	sonra genel metin üzerinden regex ile yakalamayı dener.
	"""
	import re
	scope = page.locator("#resultPrice")
	if scope.count() == 0:
		scope = page
	# 1) Tablo satırlarında etiket-değer eşlemesi
	try:
		rows = scope.locator("table tbody tr")
		rc = rows.count()
		labels: Dict[str, str] = {}
		for i in range(rc):
			tr = rows.nth(i)
			tds = tr.locator("td, th")
			tc = tds.count()
			if tc == 0:
				continue
			try:
				label = tds.nth(0).inner_text().strip()
				value = ""
				if tc > 1:
					value = tds.nth(1).inner_text().strip()
				else:
					# tek hücre ise satır içinden sayı çek
					text = tr.inner_text().strip()
					m = re.search(r"([0-9]+[.,][0-9]{2})", text)
					value = m.group(1) if m else ""
				up = label.upper()
				if "BENZ" in up and "BENZIN" not in labels:
					labels["Benzin"] = value
				if "MOTOR" in up and "Motorin" not in labels:
					labels["Motorin"] = value
			except Exception:
				continue
		if labels.get("Benzin") or labels.get("Motorin"):
			return {"benzin": labels.get("Benzin", ""), "motorin": labels.get("Motorin", "")}
	except Exception:
		pass
	# 2) Genel metinden regex ile yakalama (Türkçe ondalık için , veya .)
	try:
		text = scope.inner_text()
		benzin = ""
		motorin = ""
		# Turkish-insensitive patterns for BENZIN/BENZİN and MOTORIN/MOTORİN
		p_b = re.compile(r"B\s*E\s*N\s*Z\s*[İIıi]\s*N[^0-9]*([0-9]+[.,][0-9]{2})", re.IGNORECASE)
		p_m = re.compile(r"M\s*O\s*T\s*O\s*R\s*[İIıi]\s*N[^0-9]*([0-9]+[.,][0-9]{2})", re.IGNORECASE)
		m_b = p_b.search(text)
		if m_b:
			benzin = m_b.group(1).strip()
		m_m = p_m.search(text)
		if m_m:
			motorin = m_m.group(1).strip()
		if benzin or motorin:
			return {"benzin": benzin, "motorin": motorin}
	except Exception:
		pass
	# 3) Fallback: boş
	return {"benzin": "", "motorin": ""}


def _write_hypco_districts_to_text(city_name: str, districts: List[HypcoDistrictRow], output_file: Path) -> None:
	lines: List[str] = []
	lines.append(f"{city_name}")
	for d in districts:
		lines.append(f"{d.name} | Benzin: {d.benzin} | Motorin: {d.motorin}")
	output_file.write_text("\n".join(lines), encoding="utf-8")


def save_city_prices_txt(city_name: str, output_dir: Path, url: str = HYPCO_URL, debug: bool = False) -> Path:
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
		# Wait selects
		page.wait_for_selector("#City", state="visible", timeout=15000)
		page.wait_for_selector("#District", state="visible", timeout=15000)
		city_sel = _el(page, "#City")
		dist_sel = _el(page, "#District")
		if city_sel is None or dist_sel is None:
			raise RuntimeError("Şehir veya ilçe select'i bulunamadı.")
		# Select target city (with İstanbul özel durumu)
		options = _get_select_options(city_sel)
		def _match_value_for(text: str) -> str:
			for o in options:
				if (o.get("text") or "").strip().upper() == text.strip().upper():
					return o.get("value") or ""
			for o in options:
				if text.strip().upper() in (o.get("text") or "").strip().upper():
					return o.get("value") or ""
			return ""

		def _get_district_rows_for_selected_city() -> List[HypcoDistrictRow]:
			try:
				page.wait_for_function(
					"""() => {
						const s = document.querySelector('#District');
						return !!s && s.options && s.options.length > 1;
					}""",
					timeout=8000
				)
			except Exception:
				page.wait_for_timeout(800)
			local_dist_sel = _el(page, "#District")
			local_opts = _get_select_options(local_dist_sel)
			local_opts = [d for d in local_opts if (d.get("value") or "").strip() and "İlçe seçiniz" not in (d.get("text") or "")]
			rows: List[HypcoDistrictRow] = []
			for d in local_opts:
				name = (d.get("text") or "").strip()
				try:
					_select_option_with_events(local_dist_sel, d.get("value") or "")
					_click_show_button(page)
					_wait_results_loaded(page, timeout_ms=18000)
					prices = _extract_prices_for_selected_district(page)
					rows.append(HypcoDistrictRow(name=name, benzin=prices.get("benzin",""), motorin=prices.get("motorin","")))
				except Exception:
					rows.append(HypcoDistrictRow(name=name, benzin="", motorin=""))
				page.wait_for_timeout(int(300 * random.uniform(1.0, 1.3)))
			return rows

		all_rows: List[HypcoDistrictRow] = []
		if _is_istanbul_variant(city_name) or city_name.strip().upper() in ["ISTANBUL", "İSTANBUL"]:
			# Gather both İstanbul (Anadolu) and (Avrupa)
			istanbul_options = [o for o in options if _is_istanbul_variant((o.get("text") or ""))]
			if not istanbul_options:
				raise RuntimeError("İstanbul seçenekleri bulunamadı.")
			for opt in istanbul_options:
				_select_option_with_events(city_sel, opt.get("value") or "")
				page.wait_for_timeout(500)
				all_rows.extend(_get_district_rows_for_selected_city())
			# Deduplicate by district name
			seen = set()
			unique_rows: List[HypcoDistrictRow] = []
			for r in all_rows:
				key = r.name.strip().upper()
				if key in seen:
					continue
				seen.add(key)
				unique_rows.append(r)
			output_dir.mkdir(parents=True, exist_ok=True)
			fp = output_dir / f"hpyco_İstanbul_prices.txt"
			_write_hypco_districts_to_text("İstanbul", unique_rows, fp)
			browser.close()
			return fp
		else:
			# Single non-İstanbul city
			target_val = _match_value_for(city_name)
			if not target_val:
				raise RuntimeError(f"Şehir bulunamadı: {city_name}")
			_select_option_with_events(city_sel, target_val)
			page.wait_for_timeout(500)
			district_rows = _get_district_rows_for_selected_city()
			# Deduplicate by district name (keep first occurrence)
			seen = set()
			unique_rows: List[HypcoDistrictRow] = []
			for r in district_rows:
				key = r.name.strip().upper()
				if key in seen:
					continue
				seen.add(key)
				unique_rows.append(r)
			# Write output
			output_dir.mkdir(parents=True, exist_ok=True)
			fp = output_dir / f"hpyco_{city_name}_prices.txt"
			_write_hypco_districts_to_text(city_name, unique_rows, fp)
			browser.close()
			return fp


def save_all_cities_prices_txt(
	output_dir: Path,
	url: str = HYPCO_URL,
	debug: bool = False,
	min_delay: float = 0.6,
	max_delay: float = 1.2,
) -> List[Path]:
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
		page.wait_for_selector("#City", state="visible", timeout=15000)
		page.wait_for_selector("#District", state="visible", timeout=15000)
		city_sel = _el(page, "#City")
		dist_sel = _el(page, "#District")
		options = _get_select_options(city_sel)
		# Remove default option like "Şehir seçiniz"
		city_options = [o for o in options if (o.get("value") or "").strip() and "Şehir seçiniz" not in (o.get("text") or "")]
		output_dir.mkdir(parents=True, exist_ok=True)
		istanbul_rows: List[HypcoDistrictRow] = []
		for o in city_options:
			city_name = (o.get("text") or "").strip()
			try:
				_select_option_with_events(city_sel, o.get("value") or "")
				page.wait_for_timeout(500)
				# Refresh district options after city change
				dist_opts = _get_select_options(dist_sel)
				dist_opts = [d for d in dist_opts if (d.get("value") or "").strip() and "İlçe seçiniz" not in (d.get("text") or "")]
				district_rows: List[HypcoDistrictRow] = []
				for d in dist_opts:
					name = (d.get("text") or "").strip()
					try:
						_select_option_with_events(dist_sel, d.get("value") or "")
						_click_show_button(page)
						_wait_results_loaded(page, timeout_ms=18000)
						prices = _extract_prices_for_selected_district(page)
						district_rows.append(HypcoDistrictRow(name=name, benzin=prices.get("benzin",""), motorin=prices.get("motorin","")))
					except Exception:
						district_rows.append(HypcoDistrictRow(name=name, benzin="", motorin=""))
						continue
					page.wait_for_timeout(int(320 * random.uniform(1.0, 1.3)))
				# Deduplicate
				seen = set()
				unique_rows: List[HypcoDistrictRow] = []
				for r in district_rows:
					key = r.name.strip().upper()
					if key in seen:
						continue
					seen.add(key)
					unique_rows.append(r)
				# İstanbul özel: biriktir, hemen yazma
				if _is_istanbul_variant(city_name):
					istanbul_rows.extend(unique_rows)
				else:
					fp = output_dir / f"hpyco_{city_name}_prices.txt"
					_write_hypco_districts_to_text(city_name, unique_rows, fp)
					saved.append(fp)
					print(f"OK: {city_name} -> {fp.name}")
			except Exception as e:
				print(f"Hata/atlandı: {city_name} -> {e}")
			page.wait_for_timeout(int(1000 * random.uniform(min_delay, max_delay)))
		# İstanbul birleşik yaz
		if istanbul_rows:
			seen = set()
			unique_rows: List[HypcoDistrictRow] = []
			for r in istanbul_rows:
				key = r.name.strip().upper()
				if key in seen:
					continue
				seen.add(key)
				unique_rows.append(r)
			fp_ist = output_dir / f"hpyco_İstanbul_prices.txt"
			_write_hypco_districts_to_text("İstanbul", unique_rows, fp_ist)
			saved.append(fp_ist)
			print(f"OK: İstanbul -> {fp_ist.name}")
		browser.close()
	return saved


