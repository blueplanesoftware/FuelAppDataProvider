from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page
import random

LUKOIL_URL = "https://www.lukoil.com.tr/PompaFiyatlari"


@dataclass
class LukoilPriceRow:
    """Single Lukoil price row for a city/district."""
    city: str
    district: str
    kursunsuz_benzin: str  # K.Benzin 95 Oktan (TL/It)
    motorin: str  # Motorin (TL/It)
    ecto_eurodiesel: str  # Ecto Eurodiesel (TL/It)
    yuksek_kukurtlu_fuel_oil: str  # Yüksek Kükürtlü Fuel Oil (TL/kg)
    fuel_oil: str  # Fuel Oil (TL/kg)
    kalorifer_yakiti: str  # Kalorifer Yakıtı (TL/kg)
    gaz_yagi: str  # Gaz Yağı (TL/It)


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


def _get_city_options(page: Page) -> List[Dict[str, str]]:
    """Return list of city options from the city dropdown."""
    try:
        page.wait_for_selector("#ContentPlaceHolder1_ddlCity", state="visible", timeout=15000)
        options_locator = page.locator("#ContentPlaceHolder1_ddlCity option")
        result: List[Dict[str, str]] = []
        for i in range(options_locator.count()):
            try:
                opt = options_locator.nth(i)
                value = opt.get_attribute("value") or ""
                text = (opt.inner_text() or "").strip()
                # Skip empty options or default "select city" options
                if text and value and text.lower() not in ["", "il seçiniz", "şehir seçiniz", "seçiniz"]:
                    result.append({"value": value, "text": text})
            except Exception:
                continue
        return result
    except Exception as e:
        print(f"Error getting city options: {e}")
        return []


def _select_city_and_submit(page: Page, city_value: str, city_text: str, debug: bool = False) -> None:
    """Select a city in the dropdown and click the submit button."""
    print(f"  Selecting city: {city_text}...")
    try:
        # Wait for the dropdown to be visible
        page.wait_for_selector("#ContentPlaceHolder1_ddlCity", state="visible", timeout=10000)
        
        # Select the city option
        page.select_option("#ContentPlaceHolder1_ddlCity", value=city_value)
        page.wait_for_timeout(500)  # Small delay after selection
        
        # Wait for submit button to be visible and click it
        page.wait_for_selector("#ContentPlaceHolder1_btnGetPrices", state="visible", timeout=10000)
        submit_button = page.locator("#ContentPlaceHolder1_btnGetPrices")
        submit_button.click()
        
        # Wait for page to update after form submission
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeoutError:
            pass
        page.wait_for_timeout(2000)  # Additional wait for table to render
        
        print(f"  City {city_text} selected and form submitted")
    except Exception as e:
        print(f"  Error selecting city {city_text}: {e}")
        if debug:
            import traceback
            traceback.print_exc()
            page.screenshot(path=f"debug_lukoil_select_{city_text.replace(' ', '_')}.png")


def _extract_city_prices_from_table(page: Page, logical_city_name: str) -> List[LukoilPriceRow]:
    """Extract all district rows for the current city from the prices table."""
    prices: List[LukoilPriceRow] = []
    seen_districts: set[str] = set()  # Track districts we've already seen to avoid duplicates
    try:
        # Wait for table to appear
        print(f"  Waiting for price table for {logical_city_name}...")
        try:
            # Try to find the table - it might be in various locations
            page.wait_for_selector("table", state="visible", timeout=15000)
        except PWTimeoutError:
            print(f"  Warning: No table found for {logical_city_name}")
            return prices
        
        # Find the table with price data
        # Look for table rows with district and price data
        table_rows = page.locator("table tbody tr, table tr")
        row_count = table_rows.count()
        
        if row_count == 0:
            print(f"  No rows found in table for {logical_city_name}")
            return prices
        
        print(f"  Found {row_count} rows in table")
        
        # Extract data from each row
        for i in range(row_count):
            try:
                row = table_rows.nth(i)
                cells = row.locator("td")
                cell_count = cells.count()
                
                # Skip header rows or rows with insufficient cells
                if cell_count < 3:
                    continue
                
                # Get district name (usually first cell)
                district_text = cells.nth(0).inner_text().strip()
                
                # Skip if it's a header row (contains common header keywords)
                if any(keyword in district_text.upper() for keyword in ["İLÇE", "ILÇE", "DISTRICT", "ŞEHİR", "SEHIR", "CITY"]):
                    continue
                
                if not district_text:
                    continue
                
                # Normalize district name for comparison
                normalized_district = _normalize_location_name(district_text).upper()
                
                # Skip if we've already seen this district (deduplication)
                if normalized_district in seen_districts:
                    print(f"  Skipping duplicate district: {district_text}")
                    continue
                
                seen_districts.add(normalized_district)
                
                # Extract prices from cells
                # The exact column order may vary, so we'll try to extract all numeric values
                def get_cell_text(idx: int) -> str:
                    if idx >= cell_count:
                        return "-"
                    try:
                        text = cells.nth(idx).inner_text().strip()
                        return text if text else "-"
                    except Exception:
                        return "-"
                
                # Based on the fuel types mentioned, we expect at least 7 columns
                # We'll extract them in order: district, then prices
                # Adjust indices based on actual table structure
                prices.append(LukoilPriceRow(
                    city=logical_city_name,
                    district=_normalize_location_name(district_text),
                    kursunsuz_benzin=get_cell_text(1) if cell_count > 1 else "-",
                    motorin=get_cell_text(2) if cell_count > 2 else "-",
                    ecto_eurodiesel=get_cell_text(3) if cell_count > 3 else "-",
                    yuksek_kukurtlu_fuel_oil=get_cell_text(4) if cell_count > 4 else "-",
                    fuel_oil=get_cell_text(5) if cell_count > 5 else "-",
                    kalorifer_yakiti=get_cell_text(6) if cell_count > 6 else "-",
                    gaz_yagi=get_cell_text(7) if cell_count > 7 else "-",
                ))
            except Exception as e:
                print(f"  Error extracting row {i}: {e}")
                continue
        
        print(f"  Extracted {len(prices)} unique price rows for {logical_city_name}")
        return prices
    except Exception as e:
        print(f"  Error extracting prices for {logical_city_name}: {e}")
        import traceback
        traceback.print_exc()
        return prices


def _write_lukoil_prices_to_text(city_name: str, prices: List[LukoilPriceRow], output_file: Path) -> None:
    """Write Lukoil prices to txt. One line per district (no city header line)."""
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
            f"Ecto Eurodiesel: {p.ecto_eurodiesel}",
            f"Yüksek Kükürtlü Fuel Oil: {p.yuksek_kukurtlu_fuel_oil}",
            f"Fuel Oil: {p.fuel_oil}",
            f"Kalorifer Yakıtı: {p.kalorifer_yakiti}",
            f"Gaz Yağı: {p.gaz_yagi}",
        ]
        lines.append(" | ".join(parts))
    
    output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, debug: bool = False) -> List[Path]:
    """Scrape all cities' prices from Lukoil and save to txt files.
    
    Args:
        output_dir: Directory to save price files
        debug: If True, run in headful mode with slow-mo and take screenshots on errors
    
    Returns:
        List of Path objects for saved files
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: List[Path] = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not debug,
            slow_mo=500 if debug else 0,
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to {LUKOIL_URL}...")
            page.goto(LUKOIL_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)  # Additional wait for page to settle
            
            # Get city options
            print("Getting city options...")
            city_options = _get_city_options(page)
            
            if not city_options:
                print("Error: No city options found. Check if the dropdown selector is correct.")
                if debug:
                    page.screenshot(path="debug_lukoil_no_cities.png")
                browser.close()
                return []
            
            print(f"Found {len(city_options)} cities")
            
            # Process each city
            for idx, city_opt in enumerate(city_options, 1):
                city_value = city_opt["value"]
                city_text = city_opt["text"]
                logical_city_name = city_text
                
                # Map "İçel" to "Mersin" if needed (similar to Kadoil)
                if logical_city_name == "İçel":
                    logical_city_name = "Mersin"
                
                print(f"\n[{idx}/{len(city_options)}] Processing {logical_city_name}...")
                
                try:
                    # Select city and submit
                    _select_city_and_submit(page, city_value, city_text, debug=debug)
                    
                    # Extract prices
                    prices = _extract_city_prices_from_table(page, logical_city_name)
                    
                    if prices:
                        # Write file immediately (incremental)
                        normalized_city = _normalize_city_name_for_filename(logical_city_name)
                        output_file = output_dir / f"lukoil_{normalized_city}_prices.txt"
                        _write_lukoil_prices_to_text(logical_city_name, prices, output_file)
                        saved_files.append(output_file)
                        print(f"  ✓ Saved {len(prices)} districts to {output_file.name}")
                    else:
                        print(f"  ⚠ No prices extracted for {logical_city_name}")
                    
                    # Random delay between cities to avoid being blocked
                    if idx < len(city_options):
                        delay = random.uniform(1.0, 2.5)
                        print(f"  Waiting {delay:.1f}s before next city...")
                        page.wait_for_timeout(int(delay * 1000))
                
                except Exception as e:
                    print(f"  ✗ Error processing {logical_city_name}: {e}")
                    if debug:
                        import traceback
                        traceback.print_exc()
                        page.screenshot(path=f"debug_lukoil_error_{logical_city_name.replace(' ', '_')}.png")
                    continue
            
            print(f"\n✓ Completed! Saved {len(saved_files)} files to {output_dir}")
        
        except Exception as e:
            print(f"Error during scraping: {e}")
            if debug:
                import traceback
                traceback.print_exc()
                page.screenshot(path="debug_lukoil_general_error.png")
        
        finally:
            browser.close()
    
    return saved_files

