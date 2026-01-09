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
from moil.scraper import save_all_cities_prices_txt as moil_save_all_cities_prices_txt
import moil
from parkoil import save_city_prices_txt as parkoil_save_city_prices_txt, save_all_cities_prices_txt as parkoil_save_all_cities_prices_txt
import parkoil
from rpet import save_city_prices_txt as rpet_save_city_prices_txt, save_all_cities_prices_txt as rpet_save_all_cities_prices_txt
import rpet
from hpyco import save_city_prices_txt as hpyco_save_city_prices_txt, save_all_cities_prices_txt as hpyco_save_all_cities_prices_txt
import hpyco
try:
	from total.scraper import save_all_cities_prices_txt as total_save_all_cities_prices_txt
	import total
except Exception:
	total_save_all_cities_prices_txt = None
	total = None
from kadoil.scraper import save_all_cities_prices_txt as kadoil_save_all_cities_prices_txt
import kadoil
from lukoil.scraper import save_all_cities_prices_txt as lukoil_save_all_cities_prices_txt
import lukoil
from milangaz.scraper import save_all_cities_prices_txt as milangaz_save_all_cities_prices_txt
import milangaz
from ipragaz.scraper import save_all_cities_prices_txt as ipragaz_save_all_cities_prices_txt
import ipragaz
from sunpet.scraper import save_all_cities_prices_txt as sunpet_save_all_cities_prices_txt
import sunpet
from petral import save_city_prices_txt as petral_save_city_prices_txt, save_all_cities_prices_txt as petral_save_all_cities_prices_txt
import petral
from qplus import save_city_prices_txt as qplus_save_city_prices_txt, save_all_cities_prices_txt as qplus_save_all_cities_prices_txt
import qplus
from sahoil import save_city_prices_txt as sahoil_save_city_prices_txt, save_all_cities_prices_txt as sahoil_save_all_cities_prices_txt
import sahoil

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

def run_parkoil():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="Adana", help="Tek şehir fiyat txt kaydet (varsayılan: Adana)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(parkoil.__file__).parent / "prices"
	if args.all:
		saved = parkoil_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Seçici veya tablo bulunamamış olabilir.")
	else:
		fp = parkoil_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")

def run_rpet():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="ADANA", help="Tek şehir fiyat txt kaydet (varsayılan: ADANA)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(rpet.__file__).parent / "prices"
	if args.all:
		saved = rpet_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Tablo bulunamamış olabilir.")
	else:
		fp = rpet_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")
		
def run_hpyco():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="Adana", help="Tek şehir fiyat txt kaydet (varsayılan: Adana)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(hpyco.__file__).parent / "prices"
	if args.all:
		saved = hpyco_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Seçici veya sonuç tablosu bulunamamış olabilir.")
	else:
		fp = hpyco_save_city_prices_txt(args.city, output_dir, debug=args.debug)
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


def run_moil():
	"""
	Tüm şehirler için Moil pompa fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: moil/moil_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(moil.__file__).parent / "prices"
	saved = moil_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya tablo / şehir seçimi bulunamamış olabilir.")

def run_total():
	"""
	Tüm şehirler için Total pompa fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: total/total_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	if total is None or total_save_all_cities_prices_txt is None:
		# Lazy import fallback
		from total.scraper import save_all_cities_prices_txt as total_save_all_cities_prices_txt_local
		import total as total_local
		output_dir = Path(total_local.__file__).parent / "prices"
		saved = total_save_all_cities_prices_txt_local(output_dir, debug=args.debug)
	else:
		output_dir = Path(total.__file__).parent / "prices"
		saved = total_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya tablo / şehir seçimi bulunamamış olabilir.")

def run_kadoil():
	"""
	Tüm şehirler için Kadoil pompa fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: kadoil/kadoil_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(kadoil.__file__).parent / "prices"
	saved = kadoil_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya tablo / şehir seçimi bulunamamış olabilir.")

def run_lukoil():
	"""
	Tüm şehirler için Lukoil pompa fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: lukoil/lukoil_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(lukoil.__file__).parent / "prices"
	saved = lukoil_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya tablo / şehir seçimi bulunamamış olabilir.")

def run_aygaz():
	"""
	Bu fonksiyon artık kullanılmıyor (Aygaz scraper silindi).
	Eski çağrılar bozulmasın diye yerinde bırakıldı.
	"""
	parser = argparse.ArgumentParser()
	parser.parse_args()
	print("Aygaz scraper kaldırıldı. Lütfen Milangaz veya diğer markaları kullanın.")


def run_milangaz():
	"""
	Tüm şehirler için Milangaz Otogaz fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: milangaz/milangaz_<ŞEHİR>_prices.txt
	İstanbul (Anadolu) ve İstanbul (Avrupa) birleştirilir: milangaz_ISTANBUL_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(milangaz.__file__).parent / "prices"
	saved = milangaz_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya fiyat bulunamamış olabilir.")

def run_petral():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", help="Tek şehir fiyat txt kaydet")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet (pagination ile)")
	args = parser.parse_args()
	output_dir = Path(petral.__file__).parent / "prices"
	if args.all:
		saved = petral_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. API yanıtı boş olabilir.")
	else:
		if not args.city:
			raise SystemExit("Lütfen --city ile bir şehir adı verin veya --all kullanın.")
		fp = petral_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")

def run_qplus():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", help="Tek şehir fiyat txt kaydet")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(qplus.__file__).parent / "prices"
	if args.all:
		saved = qplus_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Seçici veya tablo bulunamamış olabilir.")
	else:
		if not args.city:
			raise SystemExit("Lütfen --city ile bir şehir adı verin veya --all kullanın.")
		fp = qplus_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")

def run_sahoil():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", default="ADANA", help="Tek şehir fiyat txt kaydet (varsayılan: ADANA)")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	output_dir = Path(sahoil.__file__).parent / "prices"
	if args.all:
		saved = sahoil_save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Seçici veya tablo bulunamamış olabilir.")
	else:
		fp = sahoil_save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")

def run_7kita():
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--city", help="Tek şehir fiyat txt kaydet")
	group.add_argument("--all", action="store_true", help="Tüm şehirlerin fiyat txt dosyalarını kaydet")
	args = parser.parse_args()
	# Dinamik modül yükleyici (paket adı sayıyla başladığı için doğrudan import edilemez)
	import importlib.util, sys
	pkg_dir = Path(__file__).parent / "7kita"
	scraper_path = pkg_dir / "scraper.py"
	spec = importlib.util.spec_from_file_location("sevenkita_scraper", str(scraper_path))
	if spec is None or spec.loader is None:
		raise SystemExit("7kita scraper yüklenemedi.")
	sevenkita = importlib.util.module_from_spec(spec)
	sys.modules["sevenkita_scraper"] = sevenkita
	spec.loader.exec_module(sevenkita)
	output_dir = pkg_dir / "prices"
	if args.all:
		saved = sevenkita.save_all_cities_prices_txt(output_dir, debug=args.debug)
		print(f"{len(saved)} dosya yazıldı -> {output_dir}")
		if not saved:
			print("Uyarı: Dosya yazılamadı. Tablo bulunamamış olabilir.")
	else:
		if not args.city:
			raise SystemExit("Lütfen --city ile bir şehir adı verin veya --all kullanın.")
		fp = sevenkita.save_city_prices_txt(args.city, output_dir, debug=args.debug)
		print(f"Kaydedildi: {fp}")
def run_ipragaz():
	"""
	Tüm şehirler için Ipragaz fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: ipragaz/ipragaz_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(ipragaz.__file__).parent / "prices"
	saved = ipragaz_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya fiyat bulunamamış olabilir.")

def run_sunpet():
	"""
	Tüm şehirler için Sunpet akaryakıt fiyatlarını çekip txt dosyalarına yazar.
	Çıktılar: sunpet/sunpet_<ŞEHİR>_prices.txt
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument("--debug", action="store_true", help="Headful + slow-mo + Inspector (PWDEBUG=1 önerilir)")
	args = parser.parse_args()

	output_dir = Path(sunpet.__file__).parent / "prices"
	saved = sunpet_save_all_cities_prices_txt(output_dir, debug=args.debug)
	print(f"{len(saved)} dosya yazıldı -> {output_dir}")
	if not saved:
		print("Uyarı: Dosya yazılamadı. Seçici veya fiyat bulunamamış olabilir.")

if __name__ == "__main__":
	run_7kita()
