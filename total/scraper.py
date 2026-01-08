from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
import json
import ssl
import http.client
from urllib.parse import urlparse

# Total Energies API endpoint
TOTAL_API_BASE = "https://apimobile.guzelenerji.com.tr/exapi/fuel_prices"

# Import city code map from common
from common.city_code_map import CITY_CODE_TO_NAME


@dataclass
class TotalPriceRow:
    """Single Total price row for a city/district."""
    city: str
    district: str
    kursunsuz_benzin: str  # K.Benzin 95 Oktan (TL/It)
    motorin: str  # Motorin (TL/It)
    motorin_excellium: str  # Motorin Excellium (TL/It)
    gazyagi: str  # Gazyağı (TL/It)
    kalorifer_yakiti: str  # Kalorifer Yakıtı (TL/kg)
    fuel_oil: str  # Fuel Oil (TL/kg)
    yuksek_kukurtlu_fuel_oil: str  # Yüksek Kükürtlü Fuel Oil (TL/kg)
    otogaz: str  # Otogaz (TL/It) - LPG


def _normalize_city_name_for_filename(city_name: str) -> str:
    """Normalize city name for use in filename (uppercase, no special chars)."""
    # Replace Turkish characters
    replacements = {
        "İ": "I", "ı": "I",
        "Ş": "S", "ş": "s",
        "Ğ": "G", "ğ": "g",
        "Ü": "U", "ü": "u",
        "Ö": "O", "ö": "o",
        "Ç": "C", "ç": "c",
    }
    normalized = city_name
    for tr_char, ascii_char in replacements.items():
        normalized = normalized.replace(tr_char, ascii_char)
    return normalized.upper().strip()


def _normalize_location_name(name: str) -> str:
    """Normalize location/district name for output."""
    return " ".join(name.strip().split())


def _fetch_api_data(url: str) -> Dict:
    """Fetch data from Total Energies API using http.client."""
    try:
        parsed = urlparse(url)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        conn = http.client.HTTPSConnection(parsed.netloc, context=ssl_context, timeout=30)
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query
        
        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        conn.close()
        
        return json.loads(data)
    except Exception as e:
        print(f"Error fetching API data: {e}")
        return {}


def _parse_api_response(api_data: Dict, city_name: str) -> List[TotalPriceRow]:
    """Parse API response into TotalPriceRow objects."""
    prices: List[TotalPriceRow] = []
    
    if not api_data or not isinstance(api_data, list):
        return prices
    
    for item in api_data:
        if not isinstance(item, dict):
            continue
        
        district = item.get("county_name", "").strip()
        if not district:
            continue
        
        def get_price_value(key, default=""):
            val = item.get(key)
            return str(val).strip() if val is not None else default
        
        prices.append(TotalPriceRow(
            city=city_name,
            district=_normalize_location_name(district),
            kursunsuz_benzin=get_price_value("kursunsuz_95_excellium_95"),
            motorin=get_price_value("motorin"),
            motorin_excellium=get_price_value("motorin_excellium"),
            gazyagi=get_price_value("gazyagi"),
            kalorifer_yakiti=get_price_value("kalorifer_yakiti"),
            fuel_oil=get_price_value("fuel_oil"),
            yuksek_kukurtlu_fuel_oil=get_price_value("yuksek_kukurtlu_fuel_oil"),
            otogaz=get_price_value("otogaz"),
        ))
    
    return prices


def _wait_for_flutter_app(page: Page, timeout: int = 30000) -> None:
    """Wait for Flutter app to load and be ready."""
    print("  Waiting for Flutter app to initialize...")
    # Wait for Flutter to initialize - look for common Flutter app indicators
    try:
        # Wait for the app to be interactive
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    
    # Additional wait for Flutter widgets to render
    page.wait_for_timeout(2000)
    
    # Try to find any Flutter-rendered content (dropdowns, buttons, etc.)
    # Flutter web apps typically have elements with specific classes or data attributes
    try:
        # Wait for any select element or button to appear (indicating app is loaded)
        page.wait_for_selector("select, button, [role='button'], [role='combobox']", timeout=15000, state="visible")
    except PWTimeoutError:
        print("  Warning: Could not find Flutter app elements. Continuing anyway...")


def _get_city_options(page: Page) -> List[Dict[str, str]]:
    """Extract city options from the dropdown.
    
    For Flutter apps, the dropdown might be a custom widget. We'll try multiple selectors.
    """
    options: List[Dict[str, str]] = []
    
    # Try standard HTML select first
    try:
        select_elements = page.locator("select").all()
        if select_elements:
            for select in select_elements:
                opts = select.locator("option").all()
                for opt in opts:
                    value = opt.get_attribute("value") or ""
                    text = (opt.inner_text() or "").strip()
                    if text and value and text.lower() not in ["şehir seçin", "select city", "seçiniz"]:
                        options.append({"value": value, "text": text})
            if options:
                return options
    except Exception:
        pass
    
    # Try Flutter dropdown (might be a custom widget with divs/spans)
    # Common patterns: dropdown with options as clickable elements
    try:
        # Look for dropdown trigger
        dropdown_trigger = page.locator("[role='combobox'], [aria-haspopup='listbox'], button:has-text('Şehir'), button:has-text('City')").first
        if dropdown_trigger.count() > 0:
            dropdown_trigger.click()
            page.wait_for_timeout(500)
            
            # Look for options in a listbox or menu
            option_elements = page.locator("[role='option'], [role='menuitem'], li, .option, .dropdown-item").all()
            for opt in option_elements:
                text = (opt.inner_text() or "").strip()
                if text and text.lower() not in ["şehir seçin", "select city", "seçiniz"]:
                    # Try to get value from data attribute or use text as value
                    value = opt.get_attribute("value") or opt.get_attribute("data-value") or text
                    options.append({"value": value, "text": text})
            
            # Close dropdown if still open
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            
            if options:
                return options
    except Exception as e:
        print(f"  Warning: Could not extract options from Flutter dropdown: {e}")
    
    # Fallback: try to find any select-like structure
    try:
        # Look for elements that might contain city names
        all_text = page.locator("body").inner_text()
        # This is a last resort - we'd need the actual HTML structure
        print("  Warning: Could not find city dropdown. Please check the page structure.")
    except Exception:
        pass
    
    return options


def _select_city_and_search(page: Page, city_value: str, city_text: str, debug: bool = False) -> None:
    """Select a city in the dropdown and click the 'Ara' (Search) button."""
    print(f"  Selecting city: {city_text} (value={city_value})...")
    
    # Try standard HTML select first
    try:
        page.select_option("select", value=city_value)
        page.wait_for_timeout(500)
    except Exception:
        # Try Flutter dropdown
        try:
            # Click dropdown trigger
            dropdown = page.locator("[role='combobox'], [aria-haspopup='listbox'], select").first
            if dropdown.count() > 0:
                dropdown.click()
                page.wait_for_timeout(500)
                
                # Find and click the option
                option = page.locator(f"[role='option']:has-text('{city_text}'), [role='menuitem']:has-text('{city_text}'), option:has-text('{city_text}')").first
                if option.count() > 0:
                    option.click()
                    page.wait_for_timeout(500)
                else:
                    # Fallback: use JavaScript to set value
                    page.evaluate(f"""
                        (val) => {{
                            const select = document.querySelector('select');
                            if (select) {{
                                select.value = val;
                                select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}
                        }}
                    """, city_value)
        except Exception as e:
            print(f"  Warning: Error selecting city: {e}")
            if debug:
                import traceback
                traceback.print_exc()
    
    # Click the "Ara" (Search) button
    try:
        # Try multiple selectors for the search button
        search_button = page.locator("button:has-text('Ara'), button:has-text('Search'), [type='submit']:has-text('Ara')").first
        if search_button.count() == 0:
            # Try by aria-label or title
            search_button = page.locator("button[aria-label*='Ara'], button[title*='Ara'], button[aria-label*='Search']").first
        
        if search_button.count() > 0:
            search_button.click()
            print("  Clicked 'Ara' button")
        else:
            print("  Warning: Could not find 'Ara' button")
    except Exception as e:
        print(f"  Warning: Error clicking search button: {e}")
        if debug:
            import traceback
            traceback.print_exc()
    
    # Wait for results to load
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    
    # Wait for price table/results to appear
    try:
        # Common table selectors
        page.wait_for_selector("table tbody tr, .price-row, [class*='price'], [class*='table'] tbody tr", timeout=15000, state="visible")
    except PWTimeoutError:
        print("  Warning: Price table did not appear after search")
    
    page.wait_for_timeout(random.uniform(500, 1500))


def _extract_city_prices_from_page(page: Page, logical_city_name: str) -> List[TotalPriceRow]:
    """Extract all price rows for the current city from the results table."""
    prices: List[TotalPriceRow] = []
    
    # Try multiple table selectors
    table_selectors = [
        "table tbody tr",
        "table tr",
        ".price-row",
        "[class*='price'] tbody tr",
        "[class*='table'] tbody tr",
        "tbody tr",
    ]
    
    rows = None
    for selector in table_selectors:
        try:
            rows = page.locator(selector)
            if rows.count() > 0:
                break
        except Exception:
            continue
    
    if rows is None or rows.count() == 0:
        print(f"  Warning: No price rows found for {logical_city_name}")
        return prices
    
    row_count = rows.count()
    print(f"  Found {row_count} row(s) in price table")
    
    for i in range(row_count):
        try:
            tr = rows.nth(i)
            cells = tr.locator("td, th").all()
            
            if len(cells) < 3:
                # Skip header rows or rows with insufficient data
                continue
            
            # Extract district name (usually first column)
            district_text = ""
            if len(cells) > 0:
                district_text = _normalize_location_name(cells[0].inner_text())
            
            # Extract prices (columns vary by site, but typically: Kurşunsuz Benzin, Motorin, LPG)
            kursunsuz_benzin = ""
            motorin = ""
            lpg = ""
            
            # Try to identify price columns by header or position
            # Common pattern: District | Kurşunsuz Benzin | Motorin | LPG
            if len(cells) >= 2:
                # Second column might be Kurşunsuz Benzin
                kursunsuz_benzin = cells[1].inner_text().strip()
            if len(cells) >= 3:
                # Third column might be Motorin
                motorin = cells[2].inner_text().strip()
            if len(cells) >= 4:
                # Fourth column might be LPG
                lpg = cells[3].inner_text().strip()
            
            # Skip if no prices found
            if not any([kursunsuz_benzin, motorin, lpg]):
                continue
            
            # If district is empty, use city name
            if not district_text:
                district_text = logical_city_name
            
            prices.append(TotalPriceRow(
                city=logical_city_name,
                district=district_text,
                kursunsuz_benzin=kursunsuz_benzin,
                motorin=motorin,
                lpg=lpg,
            ))
        except Exception as e:
            print(f"  Warning: Error extracting row {i}: {e}")
            continue
    
    return prices


def _write_total_prices_to_text(city_name: str, prices: List[TotalPriceRow], output_file: Path) -> None:
    """Write Total prices to txt. One line per district (no city header line)."""
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
            f"Motorin Excellium: {p.motorin_excellium}",
            f"Gazyağı: {p.gazyagi}",
            f"Kalorifer Yakıtı: {p.kalorifer_yakiti}",
            f"Fuel Oil: {p.fuel_oil}",
            f"Yüksek Kükürtlü Fuel Oil: {p.yuksek_kukurtlu_fuel_oil}",
            f"Otogaz: {p.otogaz}",
        ]
        lines.append(" | ".join(parts))
    
    output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, url: str = TOTAL_API_BASE, debug: bool = False) -> List[Path]:
    """Fetch Total prices from API and write one txt file per city.
    
    Uses city code map to make API requests. Each city code maps to a city name
    which is used for file naming.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: List[Path] = []
    
    if not CITY_CODE_TO_NAME:
        print("Error: CITY_CODE_TO_NAME map is empty. Please fill in the mappings in common/city_code_map.py")
        return []
    
    print(f"Fetching prices for {len(CITY_CODE_TO_NAME)} cities from API...")
    
    for city_code, city_name in CITY_CODE_TO_NAME.items():
        # Map İçel to Mersin
        logical_city = "Mersin" if city_name.upper() in ("İÇEL", "ICEL") else city_name
        
        print(f"Fetching prices for: {city_name} (City code: {city_code})...")
        
        try:
            # Fetch districts using city code
            prices_url = f"{TOTAL_API_BASE}/{city_code}"
            districts_data = _fetch_api_data(prices_url)
            
            if not districts_data:
                print(f"  Warning: No data for {city_name} (code: {city_code})")
                continue
            
            # Parse districts
            city_districts = _parse_api_response(districts_data, logical_city)
            
            if city_districts:
                # Write file immediately using city name from map
                norm_name = _normalize_city_name_for_filename(logical_city)
                fp = output_dir / f"total_{norm_name}_prices.txt"
                _write_total_prices_to_text(logical_city, city_districts, fp)
                saved_files.append(fp)
                print(f"  ✓ Saved {len(city_districts)} row(s) to {fp.name}")
            else:
                print(f"  Warning: No districts found for {city_name}")
        except Exception as e:
            print(f"  Error fetching prices for {city_name} (code: {city_code}): {e}")
            if debug:
                import traceback
                traceback.print_exc()
            continue
    
    return saved_files

