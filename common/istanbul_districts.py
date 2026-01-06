from typing import Dict, List, Optional

"""
Istanbul district → region mapping for Aytemiz (and other brands if needed).

We use this to decide whether a district belongs to:
- Avrupa (European side)
- Anadolu (Asian side)

Scrapers can then:
- Take two Istanbul LPG prices (Avrupa / Anadolu)
- Fan them out to all Istanbul districts by region
"""

# Keys are plain district names (no "İstanbul /" prefix), e.g. "Kadıköy".
ISTANBUL_DISTRICT_REGIONS: Dict[str, str] = {
    # Avrupa Yakası (25)
    "Arnavutköy": "Avrupa",
    "Avcılar": "Avrupa",
    "Bağcılar": "Avrupa",
    "Bahçelievler": "Avrupa",
    "Bakırköy": "Avrupa",
    "Başakşehir": "Avrupa",
    "Bayrampaşa": "Avrupa",
    "Beşiktaş": "Avrupa",
    "Beylikdüzü": "Avrupa",
    "Beyoğlu": "Avrupa",
    "Büyükçekmece": "Avrupa",
    "Çatalca": "Avrupa",
    "Esenler": "Avrupa",
    "Esenyurt": "Avrupa",
    "Eyüp": "Avrupa",  # Alias for Eyüpsultan (used in some data sources)
    "Eyüpsultan": "Avrupa",
    "Eminönü": "Avrupa",  # Merged into Fatih in 2009, but still appears in some data
    "Fatih": "Avrupa",
    "Gaziosmanpaşa": "Avrupa",
    "Güngören": "Avrupa",
    "Kağıthane": "Avrupa",
    "Küçükçekmece": "Avrupa",
    "Sarıyer": "Avrupa",
    "Silivri": "Avrupa",
    "Şişli": "Avrupa",
    "Sultangazi": "Avrupa",
    "Zeytinburnu": "Avrupa",

    # Anadolu Yakası (14)
    "Adalar": "Anadolu",
    "Ataşehir": "Anadolu",
    "Beykoz": "Anadolu",
    "Çekmeköy": "Anadolu",
    "Kadıköy": "Anadolu",
    "Kartal": "Anadolu",
    "Maltepe": "Anadolu",
    "Pendik": "Anadolu",
    "Sancaktepe": "Anadolu",
    "Sultanbeyli": "Anadolu",
    "Şile": "Anadolu",
    "Tuzla": "Anadolu",
    "Ümraniye": "Anadolu",
    "Üsküdar": "Anadolu",
}


def _normalize_turkish_chars(text: str) -> str:
    """Normalize Turkish characters to ASCII equivalents for matching."""
    replacements = {
        'ı': 'i', 'İ': 'I', 'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G', 'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C'
    }
    result = text
    for turkish, ascii_char in replacements.items():
        result = result.replace(turkish, ascii_char)
    return result

def get_istanbul_district_region(district_name: str) -> Optional[str]:
    """
    Return 'Avrupa' or 'Anadolu' for a given Istanbul district name, or None if not found.

    Matching is whitespace-normalized, case-insensitive, and Turkish-character-normalized.
    """
    # Normalize: lowercase, remove extra whitespace, normalize Turkish chars
    normalized_input = _normalize_turkish_chars(" ".join(district_name.strip().split()).lower())
    
    for key, region in ISTANBUL_DISTRICT_REGIONS.items():
        normalized_key = _normalize_turkish_chars(" ".join(key.strip().split()).lower())
        if normalized_key == normalized_input:
            return region
    return None


def get_avrupa_districts() -> List[str]:
    """Return list of all Avrupa (European side) district names."""
    return [dist for dist, region in ISTANBUL_DISTRICT_REGIONS.items() if region == "Avrupa"]


def get_anadolu_districts() -> List[str]:
    """Return list of all Anadolu (Asian side) district names."""
    return [dist for dist, region in ISTANBUL_DISTRICT_REGIONS.items() if region == "Anadolu"]


