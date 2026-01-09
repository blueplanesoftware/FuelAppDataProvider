from pathlib import Path

__file__ = str(Path(__file__).resolve())

from .scraper import save_all_cities_prices_txt

__all__ = ["save_all_cities_prices_txt"]

