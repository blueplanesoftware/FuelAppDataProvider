from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page
import random

MOIL_URL = "https://www.moil.com.tr/akaryakit-fiyatlari"


@dataclass
class MoilPriceRow:
    """Single Moil price row for a city/district."""
    city: str
    district: str
    kursunsuz_benzin: str
    gaz_yagi: str
    motorin: str
    motorin_powerm: str
    kalorifer_yakiti: str
    fuel_oil: str
    yk_fuel_oil: str


def _ensure_cookie_accepted(page: Page) -> None:
    """Accept cookie banner if present."""
    try:
        # Button with onclick="cerezKabul(2);" is the "Kabul Et" / "Hepsine İzin Ver" button
        btn = page.locator("button[onclick*='cerezKabul(2)']")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def _get_city_options(page: Page) -> List[Dict[str, str]]:
    """Return list of city options from #cityId select."""
    options = page.locator("#cityId option").all()
    result: List[Dict[str, str]] = []
    for opt in options:
        value = opt.get_attribute("value") or ""
        text = (opt.inner_text() or "").strip()
        if not text or not value:
            continue
        result.append({"value": value, "text": text})
    return result


def _select_city_and_submit(page: Page, city_value: str, debug: bool = False) -> None:
    """Select a city in #cityId and click the 'Sonuçları Göster' button."""
    print(f"Selecting city value={city_value}...")
    try:
        page.select_option("#cityId", value=city_value)
    except TimeoutError:
        print(f"  Timeout while selecting city value={city_value}")
    except Exception as e:
        print(f"  Error selecting city {city_value}: {e}")

    # Click the button that triggers price list update
    try:
        page.click("button[onclick='pompaFiyatList();']")
    except Exception:
        # Fallback: click by text
        try:
            page.get_by_text("Sonuçları Göster").click()
        except Exception as e:
            print(f"  Error clicking 'Sonuçları Göster' button: {e}")

    # Wait for table to update
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    try:
        page.wait_for_selector(".distributor_list table.table-hover tbody tr", timeout=15000)
    except Exception as e:
        print(f"  Warning: price table rows did not appear after city change: {e}")
    page.wait_for_timeout(random.uniform(500, 1500))


def _extract_city_prices_from_table(page: Page, logical_city_name: str) -> List[MoilPriceRow]:
    """Extract all district rows for the current city from the prices table."""
    rows = page.locator(".distributor_list table.table-hover tbody tr")
    row_count = rows.count()
    prices: List[MoilPriceRow] = []
    if row_count == 0:
        print("  Warning: price table has 0 rows for city", logical_city_name)
        return prices

    for i in range(row_count):
        try:
            tr = rows.nth(i)
            tds = tr.locator("td")
            if tds.count() < 8:
                print(f"  Warning: row {i} has only {tds.count()} cells (expected 8)")
                continue
            # Columns: İlçe, Kurşunsuz Benzin, Gaz Yağı, Motorin, Motorin PowerM,
            #          Kalorifer Yakıtı, Fuel Oil, YK Fuel Oil
            district = tds.nth(0).inner_text().strip()
            if not district:
                continue
            prices.append(
                MoilPriceRow(
                    city=logical_city_name,
                    district=district,
                    kursunsuz_benzin=tds.nth(1).inner_text().strip(),
                    gaz_yagi=tds.nth(2).inner_text().strip(),
                    motorin=tds.nth(3).inner_text().strip(),
                    motorin_powerm=tds.nth(4).inner_text().strip(),
                    kalorifer_yakiti=tds.nth(5).inner_text().strip(),
                    fuel_oil=tds.nth(6).inner_text().strip(),
                    yk_fuel_oil=tds.nth(7).inner_text().strip(),
                )
            )
        except Exception as e:
            print(f"  Error extracting row {i} for city {logical_city_name}: {e}")
            continue
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


def _write_moil_prices_to_text(city_name: str, prices: List[MoilPriceRow], output_file: Path) -> None:
    """Write Moil prices to txt. One line per district (no city header line)."""
    lines: List[str] = []
    for p in prices:
        loc = _normalize_location_name(p.district)
        parts = [
            loc,
            f"Kurşunsuz Benzin: {p.kursunsuz_benzin}",
            f"Gaz Yağı: {p.gaz_yagi}",
            f"Motorin: {p.motorin}",
            f"Motorin PowerM: {p.motorin_powerm}",
            f"Kalorifer Yakıtı: {p.kalorifer_yakiti}",
            f"Fuel Oil: {p.fuel_oil}",
            f"YK Fuel Oil: {p.yk_fuel_oil}",
        ]
        lines.append(" | ".join(parts))
    output_file.write_text("\n".join(lines), encoding="utf-8")


def save_all_cities_prices_txt(output_dir: Path, debug: bool = False) -> List[Path]:
    """Fetch Moil prices for all cities and write one txt file per city.

    Behaviour:
    - Iterates over city options one by one.
    - As soon as a city's prices are fetched, its txt file is (over)written immediately.
    - Istanbul has two options (İSTANBUL / İSTANBUL Anadolu); both are merged
      into the same logical city 'İSTANBUL' and the txt file is updated after
      each Istanbul option is processed.
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

        print(f"Navigating to {MOIL_URL}")
        page.goto(MOIL_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        _ensure_cookie_accepted(page)

        # Ensure city select is present
        try:
            page.wait_for_selector("#cityId", state="visible", timeout=15000)
        except PWTimeoutError:
            print("Error: #cityId select not found on Moil page.")
            browser.close()
            return []

        city_options = _get_city_options(page)
        print(f"Found {len(city_options)} city option(s) on Moil page.")

        # Aggregate by logical city name (merge İstanbul & İstanbul Anadolu).
        # We also write txt files incrementally so you don't have to wait for
        # all cities to finish.
        all_city_prices: Dict[str, List[MoilPriceRow]] = {}

        for opt in city_options:
            city_text = opt["text"].strip()
            city_value = opt["value"]
            if not city_text:
                continue

            # Logical city name used for filename & grouping
            upper_text = city_text.upper()

            # İstanbul / İstanbul Anadolu are merged
            if (
                upper_text.startswith("İSTANBUL")
                or upper_text.startswith("ISTANBUL")
                or "İSTANBUL" in upper_text
                or "ISTANBUL" in upper_text
            ):
                logical_city = "İSTANBUL"
            # İçel is actually Mersin (site bug) – map to Mersin
            elif upper_text in ("İÇEL", "ICEL"):
                logical_city = "Mersin"
            else:
                logical_city = city_text

            print(f"Fetching prices for city option: '{city_text}' (value={city_value}), logical city='{logical_city}'")
            try:
                _select_city_and_submit(page, city_value, debug=debug)
                city_prices = _extract_city_prices_from_table(page, logical_city)
                if city_prices:
                    # Merge into in-memory collection for this logical city
                    all_city_prices.setdefault(logical_city, []).extend(city_prices)
                    total_for_city = len(all_city_prices[logical_city])
                    print(
                        f"  Collected {len(city_prices)} row(s) for logical city "
                        f"'{logical_city}' (total now {total_for_city})"
                    )

                    # Write / update this city's txt file immediately
                    try:
                        norm_name = _normalize_city_name_for_filename(logical_city)
                        fp = output_dir / f"moil_{norm_name}_prices.txt"
                        _write_moil_prices_to_text(logical_city, all_city_prices[logical_city], fp)
                        if fp not in saved_files:
                            saved_files.append(fp)
                        print(f"  Saved {total_for_city} row(s) to {fp.name}")
                    except Exception as write_err:
                        print(f"  Error writing file for city '{logical_city}': {write_err}")
                        if debug:
                            import traceback

                            traceback.print_exc()
                else:
                    print(f"  Warning: no rows found for city option '{city_text}'")
            except Exception as e:
                print(f"  Error while fetching prices for city option '{city_text}': {e}")
                if debug:
                    import traceback

                    traceback.print_exc()
                continue

            page.wait_for_timeout(random.uniform(300, 1000))

        browser.close()

    return saved_files



