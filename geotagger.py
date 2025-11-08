import os
import piexif
from PIL import Image
from geopy.geocoders import Nominatim
import tempfile
import shutil


geolocator = Nominatim(user_agent="geo_exif_writer")

def to_utf_16(s):
    return s.encode("utf-16-le") + b"\x00\x00"


def rational_to_deg(value):
    d = value[0][0] / value[0][1]
    m = value[1][0] / value[1][1]
    s = value[2][0] / value[2][1]
    return d + (m / 60.0) + (s / 3600.0)


def safe_save_jpeg(img, file_path, exif_bytes):
    # Temporäre Datei im selben Ordner anlegen
    dir_name = os.path.dirname(file_path)
    with tempfile.NamedTemporaryFile(delete=False, dir=dir_name, suffix=".jpg") as tmp:
        temp_path = tmp.name

    try:
        # Versuch: neues Bild mit EXIF schreiben
        img.save(temp_path, exif=exif_bytes)
        # Wenn erfolgreich, altes ersetzen
        shutil.move(temp_path, file_path)
    except Exception as e:
        # Bei Fehler: temporäre Datei löschen, Original bleibt erhalten
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e


def _parse_directory(path: str, parse_subdirs: bool):
    for file_name in os.listdir(path):
        file_path = os.path.join(path, file_name)

        # Datei bearbeiten
        if os.path.isfile(file_path) and file_path.lower().endswith((".jpg", ".jpeg")):

            # Bild laden
            dir_name = os.path.basename(path)
            img = Image.open(file_path)
            exif_info = img.info.get("exif", None)
            if not exif_info: continue
            exif_dict = piexif.load(exif_info)

            # Koordinaten auslesen
            gps_data = exif_dict.get("GPS", None)
            if not gps_data: continue
            try:
                lat_ref = gps_data.get(piexif.GPSIFD.GPSLatitudeRef, b'N').decode()
                lon_ref = gps_data.get(piexif.GPSIFD.GPSLongitudeRef, b'E').decode()
                lat = rational_to_deg(gps_data[piexif.GPSIFD.GPSLatitude])
                lon = rational_to_deg(gps_data[piexif.GPSIFD.GPSLongitude])
            except KeyError:
                continue

            # Werte umkehren, je nach Quadrant
            if lat_ref == "S": lat = -lat
            if lon_ref == "W": lon = -lon

            # Geo-Daten auslesen
            location = geolocator.reverse((lat, lon))
            if not location: continue
            address = location.raw.get("address", None)
            if not address: continue

            # Eigenschaften zusammenbauen
            keywords = []
            for key in ["country",
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
                        ("aeroway", "waterway", "natural", "place", "locality")]:
                for subkey in [key] if type(key) == str else key:
                    if subkey in address:
                        value = address[subkey]
                        if len(keywords) == 0 or value != keywords[-1]:
                            keywords.append(address[subkey])

            print([dir_name, file_name, keywords])

            # Schreiben in die Datei
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = to_utf_16("; ".join(keywords))
            exif_bytes = piexif.dump(exif_dict)
            safe_save_jpeg(img, file_path, exif_bytes)

        # Ordner rekursiv durchgehen
        elif os.path.isdir(file_path) and parse_subdirs:
            _parse_directory(file_path, True)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Liest GPS-Daten aus Fotos und schreibt Ortsinformationen in die Metadaten."
    )
    parser.add_argument(
        "path",
        type=str,
        help="Pfad zum Verzeichnis, das durchsucht werden soll."
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Unterordner rekursiv durchsuchen."
    )

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Der angegebene Pfad existiert nicht: {args.path}")
        sys.exit(1)

    print(f"Starte Verarbeitung im Ordner: {args.path}")
    if args.recursive:
        print("Rekursive Suche aktiviert.")

    try:
        _parse_directory(args.path, args.recursive)
        print("Verarbeitung abgeschlossen.")
    except KeyboardInterrupt:
        print("\nAbgebrochen durch Benutzer.")
