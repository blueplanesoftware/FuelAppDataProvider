from pathlib import Path
import argparse
from common.plates import get_plate_codes
from petrolofisi.scraper import fetch_all_cities_prices
import petrolofisi
from shell import save_city_prices_txt, save_all_cities_prices_txt
import shell
from opet import save_city_prices_txt as opet_save_city_prices_txt, save_all_cities_prices_txt as opet_save_all_cities_prices_txt
import opet
from turkiyepetrolleri.scraper import fetch_all_cities_prices as tppd_fetch_all_cities_prices
from turkiyepetrolleri import save_city_prices_txt as tppd_save_city_prices_txt, save_all_cities_prices_txt as tppd_save_all_cities_prices_txt
import turkiyepetrolleri
from aytemiz.scraper import save_all_cities_prices_txt
import aytemiz

def run_opet():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="ADANA", help="Tek şehir fiyat txt kaydet (varsayılan: ADANA)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(opet.__file__).parent / "prices"
	if args.all:
		saved = opet_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Seçici veya tablo bulunamamış olabilir.")
	else:
		fp = opet_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")

def run_petrolofisi():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()
	target_url = "https://www.petrolofisi.com.tr/akaryakit-fiyatlari"
	# 81 il plaka kodlarını ortak fonksiyondan al
	plate_codes = get_plate_codes()
	# Tüm iller için yalnızca fiyat txt'leri üret (HTML yazılmaz)
	output_dir = Path(petrolofisi.__file__).parent / "prices"
	fetch_all_cities_prices(target_url, plate_codes, output_dir, prefer_with_tax=True, debug=args.debug)
	print("Tüm iller için txt dosyaları 'petrolofisi/prices' klasörüne yazıldı (petrolofisi_<plaka>_prices.txt).")

def run_shell():
	# .\test.py --all => hepsi   ,   .\test.py --city ADANA => sadece ADANA
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="ADANA", help="Tek şehir fiyat txt kaydet (varsayılan: ADANA)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(shell.__file__).parent / "prices"
	if args.all:
		save_all_cities_prices_txt(output_dir, debug=args.debug)
		print("Tüm şehirlerin fiyat txt dosyaları 'shell/prices' klasörüne yazıldı (shell_<ŞEHİR>_prices.txt).")
	else:
		fp = save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")


def run_turkiyepetrolleri():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()
	# Tüm şehirler için otomatik olarak fiyat txt'leri üret (Petrolofisi gibi)
	output_dir = Path(turkiyepetrolleri.__file__).parent / "prices"
	tppd_fetch_all_cities_prices(output_dir, debug=args.debug)

def run_aytemiz():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()
	# Fetch all cities with benzin and LPG prices (merged) and save to text files
	output_dir = Path(aytemiz.__file__).parent / "prices"
	saved = save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya tablo bulunamamış olabilir.")

if __name__ == "__main__":
	run_aytemiz()