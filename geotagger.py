import os
import piexif
from PIL import Image
from geopy.geocoders import Nominatim
from concurrent.futures import ThreadPoolExecutor, as_completed


geolocator = Nominatim(user_agent="geo_exif_writer", timeout=10)


def to_utf_16(s):
    return s.encode("utf-16-le") + b"\x00\x00"


def rational_to_deg(value):
    d = value[0][0] / value[0][1]
    m = value[1][0] / value[1][1]
    s = value[2][0] / value[2][1]
    return d + (m / 60.0) + (s / 3600.0)


def safe_save_jpeg(img, file_path, exif_bytes):
    piexif.insert(exif_bytes, file_path)


def process_image(file_path):
    try:
        file_name = os.path.basename(file_path)
        dir_name = os.path.basename(os.path.dirname(file_path))
        img = Image.open(file_path)
        exif_info = img.info.get("exif", None)
        if not exif_info:
            return file_path, "no_exif", None

        exif_dict = piexif.load(exif_info)
        gps_data = exif_dict.get("GPS", None)
        if not gps_data:
            return file_path, "no_gps", None

        try:
            lat_ref = gps_data.get(piexif.GPSIFD.GPSLatitudeRef, b'N').decode()
            lon_ref = gps_data.get(piexif.GPSIFD.GPSLongitudeRef, b'E').decode()
            lat = rational_to_deg(gps_data[piexif.GPSIFD.GPSLatitude])
            lon = rational_to_deg(gps_data[piexif.GPSIFD.GPSLongitude])
        except KeyError:
            return file_path, "invalid_gps", None

        if lat_ref == "S":
            lat = -lat
        if lon_ref == "W":
            lon = -lon

        # Geo-Request
        location = geolocator.reverse((lat, lon))
        if not location:
            return file_path, "no_location", None
        address = location.raw.get("address", None)
        if not address:
            return file_path, "no_address", None

        # Keywords zusammenbauen
        keywords = []
        for key in [
            "country",
            "state",
            "archipelago",
            ("island", "region"),
            "state_district",
            "county",
            "postcode",
            ("town", "city", "village", "hamlet"),
            "city_district",
            "suburb",
            ("neighbourhood", "isolated_dwelling", "commercial", "industrial"),
            "road",
            "house_number",
            ("aeroway", "waterway", "natural", "place", "locality"),
        ]:
            for subkey in [key] if isinstance(key, str) else key:
                if subkey in address:
                    value = address[subkey]
                    if value not in keywords:
                        keywords.append(value)
                        break

        # EXIF schreiben
        print([dir_name, file_name, keywords])
        exif_dict["0th"][piexif.ImageIFD.XPKeywords] = to_utf_16("; ".join(keywords))
        exif_bytes = piexif.dump(exif_dict)
        safe_save_jpeg(img, file_path, exif_bytes)

        return file_path, "ok", keywords

    except Exception as e:
        return file_path, f"error: {e}", None


def get_all_images(path, recursive=True):
    for root, dirs, files in os.walk(path):
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg")):
                yield os.path.join(root, f)
        if not recursive:
            break


def process_all(path, recursive=True, max_workers=5):
    all_images = list(get_all_images(path, recursive))
    print(f"Gefundene Bilder: {len(all_images)}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_image, fp): fp for fp in all_images}

        for i, future in enumerate(as_completed(futures), 1):
            fp = futures[future]
            try:
                _, _, _ = future.result()
            except Exception as e:
                print(f"[{i}] Fehler bei {fp}: {e}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Parallelisiert GPS-Auswertung und Geotagging von Bildern."
    )
    parser.add_argument("path", type=str, help="Pfad zum Verzeichnis")
    parser.add_argument("-r", "--recursive", action="store_true", help="Unterordner durchsuchen")
    parser.add_argument("-t", "--threads", type=int, default=5, help="Anzahl paralleler Threads")

    args = parser.parse_args()
    if not os.path.exists(args.path):
        print(f"Pfad existiert nicht: {args.path}")
        sys.exit(1)

    print(f"Starte parallele Verarbeitung mit {args.threads} Threads ...")
    process_all(args.path, recursive=args.recursive, max_workers=args.threads)
