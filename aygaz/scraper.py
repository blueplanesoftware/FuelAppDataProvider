from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page
import random
import re

AYGAZ_URL = "https://www.aygaz.com.tr/fiyatlar/otogaz"


@dataclass
class AygazPriceRow:
    """Single Aygaz price row for a city."""
    city: str
    price: str  # Single Otogaz price in TL/lt


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
    # Remove parentheses and their contents for filename
    normalized = re.sub(r'\s*\([^)]*\)\s*', '', normalized)
    return normalized.upper().strip()


def _get_city_links(page: Page) -> List[Dict[str, str]]:
    """Extract city links from the city list at the bottom of the page."""
    try:
        # Wait for the city list to be visible
        page.wait_for_selector("div.list a.item", state="visible", timeout=15000)
        
        city_links = page.locator("div.list a.item")
        result: List[Dict[str, str]] = []
        
        link_count = city_links.count()
        print(f"  Found {link_count} city links")
        
        for i in range(link_count):
            try:
                link = city_links.nth(i)
                href = link.get_attribute("href") or ""
                text = (link.inner_text() or "").strip()
                
                # Remove "Otogaz Fiyatları" suffix
                city_name = re.sub(r'\s+Otogaz Fiyatları\s*$', '', text, flags=re.IGNORECASE)
                
                if city_name and href:
                    result.append({"name": city_name, "href": href})
            except Exception as e:
                print(f"  Error extracting link {i}: {e}")
                continue
        
        return result
    except Exception as e:
        print(f"Error getting city links: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_price_from_page(page: Page) -> str:
    """Extract the price from the current page."""
    try:
        # Wait for price element to be visible
        page.wait_for_selector("p.price", state="visible", timeout=10000)
        
        price_element = page.locator("p.price").first
        price_text = price_element.inner_text().strip()
        
        # Extract just the numeric price (remove "TL/lt" and other text)
        # Format is typically "30.69 TL/lt" or "30.69<!-- --> TL/lt"
        price_match = re.search(r'(\d+\.?\d*)', price_text)
        if price_match:
            price = price_match.group(1)
            return price
        else:
            return price_text
    except PWTimeoutError:
        print("  Warning: Price element not found")
        return ""
    except Exception as e:
        print(f"  Error extracting price: {e}")
        return ""


def _write_aygaz_price_to_text(city_name: str, price: str, output_file: Path, append: bool = False) -> None:
    """Write Aygaz price to txt file. Format: CITY_NAME: PRICE
    
    Args:
        city_name: Name of the city
        price: Price value
        output_file: Path to output file
        append: If True, append to existing file; if False, overwrite
    """
    if not price:
        if not append:
            output_file.write_text("", encoding="utf-8")
        return
    
    # Format: CITY_NAME: PRICE
    line = f"{city_name}: {price}"
    
    if append and output_file.exists():
        # Append to existing file
        existing_content = output_file.read_text(encoding="utf-8").strip()
        if existing_content:
            output_file.write_text(f"{existing_content}\n{line}", encoding="utf-8")
        else:
            output_file.write_text(line, encoding="utf-8")
    else:
        # Write new file
        output_file.write_text(line, encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, debug: bool = False) -> List[Path]:
    """Scrape all cities' prices from Aygaz and save to txt files.
    
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
            print(f"Navigating to {AYGAZ_URL}...")
            # Use domcontentloaded instead of networkidle
            try:
                page.goto(AYGAZ_URL, wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                page.goto(AYGAZ_URL, wait_until="load", timeout=60000)
            
            page.wait_for_timeout(3000)  # Wait for React to render
            
            # Get city links
            print("Getting city links...")
            city_links = _get_city_links(page)
            
            if not city_links:
                print("Error: No city links found.")
                if debug:
                    page.screenshot(path="debug_aygaz_no_links.png")
                browser.close()
                return []
            
            print(f"Found {len(city_links)} cities")
            
            # Track Istanbul file
            istanbul_output_file = output_dir / "aygaz_ISTANBUL_prices.txt"
            istanbul_count = 0
            
            # Process each city
            for idx, city_data in enumerate(city_links, 1):
                city_name = city_data["name"]
                city_href = city_data["href"]
                
                # Check if this is an Istanbul city
                is_istanbul = "istanbul" in city_name.lower() or "İstanbul" in city_name
                
                print(f"\n[{idx}/{len(city_links)}] Processing {city_name}...")
                
                try:
                    # Navigate to the city's page
                    full_url = f"https://www.aygaz.com.tr{city_href}" if city_href.startswith("/") else city_href
                    print(f"  Navigating to {full_url}...")
                    
                    try:
                        page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
                    except PWTimeoutError:
                        page.goto(full_url, wait_until="load", timeout=30000)
                    
                    page.wait_for_timeout(2000)  # Wait for page to load
                    
                    # Extract price
                    price = _extract_price_from_page(page)
                    
                    if price:
                        if is_istanbul:
                            # Use the actual city name from the link (e.g., "İstanbul (Anadolu)" or "İstanbul (Avrupa)")
                            istanbul_label = city_name  # This will be "İstanbul (Anadolu)" or "İstanbul (Avrupa)"
                            
                            # Write/append to Istanbul file
                            if istanbul_count == 0:
                                # First Istanbul city - write new file
                                _write_aygaz_price_to_text(istanbul_label, price, istanbul_output_file, append=False)
                                saved_files.append(istanbul_output_file)
                                istanbul_count += 1
                                print(f"  ✓ Saved price to {istanbul_output_file.name}")
                            else:
                                # Second Istanbul city - append to existing file
                                _write_aygaz_price_to_text(istanbul_label, price, istanbul_output_file, append=True)
                                istanbul_count += 1
                                print(f"  ✓ Appended price to {istanbul_output_file.name}")
                        else:
                            # Write file immediately for non-Istanbul cities
                            normalized_city = _normalize_city_name_for_filename(city_name)
                            output_file = output_dir / f"aygaz_{normalized_city}_prices.txt"
                            _write_aygaz_price_to_text(city_name, price, output_file)
                            saved_files.append(output_file)
                            print(f"  ✓ Saved price to {output_file.name}")
                    else:
                        print(f"  ⚠ No price extracted for {city_name}")
                    
                    # Random delay between cities to avoid being blocked
                    if idx < len(city_links):
                        delay = random.uniform(1.0, 2.5)
                        print(f"  Waiting {delay:.1f}s before next city...")
                        page.wait_for_timeout(int(delay * 1000))
                
                except Exception as e:
                    print(f"  ✗ Error processing {city_name}: {e}")
                    if debug:
                        import traceback
                        traceback.print_exc()
                        page.screenshot(path=f"debug_aygaz_error_{city_name.replace(' ', '_').replace('(', '').replace(')', '')}.png")
                    continue
            
            print(f"\n✓ Completed! Saved {len(saved_files)} files to {output_dir}")
        
        except Exception as e:
            print(f"Error during scraping: {e}")
            if debug:
                import traceback
                traceback.print_exc()
                page.screenshot(path="debug_aygaz_general_error.png")
        
        finally:
            browser.close()
    
    return saved_files

