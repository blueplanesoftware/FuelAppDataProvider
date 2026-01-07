from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page
import random

# TODO: Update this URL with the actual Kadoil fuel prices page URL
KADOIL_URL = "https://kadoil.com/akaryakit-fiyatlari/"


@dataclass
class KadoilPriceRow:
    """Single Kadoil price row for a city/district."""
    city: str
    district: str
    kursunsuz_benzin: str  # K.Benzin 95 Oktan (TL/It)
    motorin: str  # Motorin (TL/It)
    ecomax_motorin: str  # EcoMax Motorin (TL/It)
    gazyagi: str  # Gazyağı (TL/It)
    kalorifer_yakiti: str  # Kalorifer Yakıtı (TL/kg)
    fuel_oil: str  # Fuel Oil (TL/kg)
    yuksek_kukurtlu_fuel_oil: str  # Yüksek Kükürtlü Fuel Oil (TL/kg)
    kadogaz: str  # KADOGAZ (TL/It) - LPG


def _ensure_cookie_accepted(page: Page) -> None:
    """Accept cookie banner if present."""
    try:
        # Kadoil uses a button with id="euCookieAcceptWP"
        btn = page.locator("button#euCookieAcceptWP")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def _get_city_options(select_context) -> List[Dict[str, str]]:
    """Return list of city options from #selectProvince select."""
    try:
        select_context.wait_for_selector("#selectProvince", state="visible", timeout=10000)
        options_locator = select_context.locator("#selectProvince option")
        result: List[Dict[str, str]] = []
        for i in range(options_locator.count()):
            try:
                opt = options_locator.nth(i)
                value = opt.get_attribute("value") or ""
                text = (opt.inner_text() or "").strip()
                if text and value and text != "İl seçiniz":
                    result.append({"value": value, "text": text})
            except Exception:
                continue
        return result
    except Exception as e:
        print(f"Error getting city options: {e}")
        return []


def _select_city_and_submit(select_context, page: Page, city_value: str, city_text: str, debug: bool = False) -> None:
    """Select a city in #selectProvince and wait for the iframe to update."""
    print(f"  Selecting city: {city_text}...")
    try:
        # Set value and trigger events
        select_context.evaluate(f"""
            (val) => {{
                const select = document.querySelector('#selectProvince');
                if (select) {{
                    select.value = val;
                    select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    if (window.jQuery) window.jQuery(select).trigger('change');
                }}
            }}
        """, city_value)
        
        # Wait for iframe to update
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeoutError:
            pass
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  Error selecting city {city_text}: {e}")
        if debug:
            import traceback
            traceback.print_exc()


def _get_iframe_frame(page: Page):
    """Get the iframe frame object for price table."""
    for f in page.frames:
        if "admin.kadoil.com" in f.url or f.name == "frame":
            return f
    return page.frame(url=lambda url: "admin.kadoil.com" in url if url else False)


def _extract_city_prices_from_table(page: Page, logical_city_name: str) -> List[KadoilPriceRow]:
    """Extract all district rows for the current city from the prices table."""
    prices: List[KadoilPriceRow] = []
    try:
        frame = _get_iframe_frame(page)
        if not frame:
            return prices
        
        frame.wait_for_selector("table tbody tr", timeout=15000)
        rows = frame.locator("table tbody tr")
        
        for i in range(rows.count()):
            try:
                tds = rows.nth(i).locator("td")
                if tds.count() < 9:
                    continue
                
                district = tds.nth(0).inner_text().strip()
                if not district or district.lower() in ["ilçe", "district", "bölge"]:
                    continue
                
                prices.append(KadoilPriceRow(
                    city=logical_city_name,
                    district=_normalize_location_name(district),
                    kursunsuz_benzin=tds.nth(1).inner_text().strip(),
                    motorin=tds.nth(2).inner_text().strip(),
                    ecomax_motorin=tds.nth(3).inner_text().strip(),
                    gazyagi=tds.nth(4).inner_text().strip(),
                    kalorifer_yakiti=tds.nth(5).inner_text().strip(),
                    fuel_oil=tds.nth(6).inner_text().strip(),
                    yuksek_kukurtlu_fuel_oil=tds.nth(7).inner_text().strip(),
                    kadogaz=tds.nth(8).inner_text().strip(),
                ))
            except Exception:
                continue
    except Exception as e:
        print(f"  Error extracting prices for {logical_city_name}: {e}")
    return prices


def _normalize_city_name_for_filename(city_name: str) -> str:
    """Normalize city name (Turkish chars → ASCII, uppercased) for filenames."""
    replacements = {
        "İ": "I", "ı": "i", "ş": "s", "Ş": "S",
        "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U",
        "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
    }
    result = city_name
    for tr_char, ascii_char in replacements.items():
        result = result.replace(tr_char, ascii_char)
    return result.upper().strip()


def _normalize_location_name(location: str) -> str:
    """Normalize district or city name for output line (ASCII, upper)."""
    return _normalize_city_name_for_filename(location)


def _write_kadoil_prices_to_text(city_name: str, prices: List[KadoilPriceRow], output_file: Path) -> None:
    """Write Kadoil prices to txt. One line per district (no city header line)."""
    if not prices:
        output_file.write_text("", encoding="utf-8")
        return
    
    lines: List[str] = []
    for p in prices:
        loc = _normalize_location_name(p.district)
        parts = [
            loc,
            f"K.Benzin 95 Oktan: {p.kursunsuz_benzin}",
            f"Motorin: {p.motorin}",
            f"EcoMax Motorin: {p.ecomax_motorin}",
            f"Gazyağı: {p.gazyagi}",
            f"Kalorifer Yakıtı: {p.kalorifer_yakiti}",
            f"Fuel Oil: {p.fuel_oil}",
            f"Yüksek Kükürtlü Fuel Oil: {p.yuksek_kukurtlu_fuel_oil}",
            f"KADOGAZ: {p.kadogaz}",
        ]
        lines.append(" | ".join(parts))
    
    output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, url: str = KADOIL_URL, debug: bool = False) -> List[Path]:
    """Fetch Kadoil prices for all cities and write one txt file per city.

    Behaviour:
    - Iterates over city options one by one.
    - As soon as a city's prices are fetched, its txt file is (over)written immediately.
    - İçel is mapped to Mersin for file naming.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: List[Path] = []

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

        print(f"Navigating to {url}")
        try:
            page.goto(url, wait_until="domcontentloaded")
            # Wait for page to be interactive
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeoutError:
                # Continue even if networkidle times out
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
            print("Please check if the URL is correct. You can update KADOIL_URL in kadoil/scraper.py")
            browser.close()
            return []
        
        # Accept cookies and wait for iframe
        _ensure_cookie_accepted(page)
        page.wait_for_selector("iframe#frame", state="attached", timeout=15000)
        page.wait_for_timeout(2000)
        
        # Find select (usually in iframe)
        frame = _get_iframe_frame(page)
        select_context = frame if frame and frame.locator("#selectProvince").count() > 0 else page
        
        try:
            select_context.wait_for_selector("#selectProvince", state="visible", timeout=10000)
        except PWTimeoutError:
            print("Error: #selectProvince select not found")
            browser.close()
            return []
        
        city_options = _get_city_options(select_context)
        if not city_options:
            print("Error: No city options found on Kadoil page.")
            if debug:
                page.screenshot(path="debug_kadoil_no_options.png")
            browser.close()
            return []
        
        print(f"Found {len(city_options)} city option(s)")

        # Aggregate by logical city name (map İçel to Mersin)
        all_city_prices: Dict[str, List[KadoilPriceRow]] = {}

        for opt in city_options:
            city_text = opt["text"].strip()
            city_value = opt["value"]
            if not city_text:
                continue

            # Logical city name used for filename & grouping
            upper_text = city_text.upper()

            # İçel is actually Mersin (site bug) – map to Mersin
            if upper_text in ("İÇEL", "ICEL"):
                logical_city = "Mersin"
            else:
                logical_city = city_text

            print(f"Fetching prices for: {city_text} -> {logical_city}")
            try:
                _select_city_and_submit(select_context, page, city_value, city_text, debug=debug)
                city_prices = _extract_city_prices_from_table(page, logical_city)
                
                if city_prices:
                    all_city_prices.setdefault(logical_city, []).extend(city_prices)
                    total = len(all_city_prices[logical_city])
                    
                    norm_name = _normalize_city_name_for_filename(logical_city)
                    fp = output_dir / f"kadoil_{norm_name}_prices.txt"
                    _write_kadoil_prices_to_text(logical_city, all_city_prices[logical_city], fp)
                    if fp not in saved_files:
                        saved_files.append(fp)
                    print(f"  ✓ Saved {total} row(s) to {fp.name}")
            except Exception as e:
                print(f"  Error for {city_text}: {e}")
                if debug:
                    import traceback
                    traceback.print_exc()
            
            page.wait_for_timeout(random.uniform(300, 1000))

        browser.close()

    return saved_files

