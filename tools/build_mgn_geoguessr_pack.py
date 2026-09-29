from __future__ import annotations

import base64
import csv
import hashlib
import io
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

OUT = pathlib.Path(".mgn-pack-output")
PHOTOS = OUT / "photos"
B64 = OUT / "b64"
ZIP_PATH = OUT / "Magnitogorsk_GeoGuessr_40.zip"

items = [
    ("53.378356","58.996831","Views of Magnitogorsk-2021 - 2.jpeg","Магнитогорск. Вознесенская церковь (вид с ул. Завенягина)","https://thumb.wikimedia.org/wikipedia/commons/thumb/a/af/Views_of_Magnitogorsk-2021_-_2.jpeg/1280px-Views_of_Magnitogorsk-2021_-_2.jpeg"),
    ("53.385461","58.998108","Views of Magnitogorsk-2021 - 12.jpeg","Заводской пруд на реке Урал","https://thumb.wikimedia.org/wikipedia/commons/thumb/7/76/Views_of_Magnitogorsk-2021_-_12.jpeg/1280px-Views_of_Magnitogorsk-2021_-_12.jpeg"),
    ("53.407722","58.991169","Views of Magnitogorsk-2021 - 21.jpeg","Парк «У Вечного огня»","https://thumb.wikimedia.org/wikipedia/commons/thumb/4/46/Views_of_Magnitogorsk-2021_-_21.jpeg/1280px-Views_of_Magnitogorsk-2021_-_21.jpeg"),
    ("53.407494","58.992128","Views of Magnitogorsk-2021 - 23.jpeg","Городской пляж; на дальнем плане цеха ММК","https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7e/Views_of_Magnitogorsk-2021_-_23.jpeg/1280px-Views_of_Magnitogorsk-2021_-_23.jpeg"),
    ("53.407150","58.991117","Views of Magnitogorsk-2021 - 28.jpeg","Памятник Героям Советского Союза","https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e7/Views_of_Magnitogorsk-2021_-_28.jpeg/1280px-Views_of_Magnitogorsk-2021_-_28.jpeg"),
    ("53.407319","58.983600","Views of Magnitogorsk-2021 - 29.jpeg","Площадь торжеств и фонтан перед зданием городской администрации","https://thumb.wikimedia.org/wikipedia/commons/thumb/3/34/Views_of_Magnitogorsk-2021_-_29.jpeg/1280px-Views_of_Magnitogorsk-2021_-_29.jpeg"),
    ("53.419875","58.979747","Views of Magnitogorsk-2021 - 33.jpeg","Вход в университетский сквер со стороны пр. Карла Маркса","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/07/Views_of_Magnitogorsk-2021_-_33.jpeg/1280px-Views_of_Magnitogorsk-2021_-_33.jpeg"),
    ("53.420197","58.981469","Views of Magnitogorsk-2021 - 36.jpeg","Учебный корпус МГТУ на ул. Калинина","https://thumb.wikimedia.org/wikipedia/commons/thumb/9/98/Views_of_Magnitogorsk-2021_-_36.jpeg/1280px-Views_of_Magnitogorsk-2021_-_36.jpeg"),
    ("53.437072","58.980625","Views of Magnitogorsk-2021 - 40.jpeg","Железнодорожный вокзал станции Магнитогорск-Пассажирский","https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b0/Views_of_Magnitogorsk-2021_-_40.jpeg/1280px-Views_of_Magnitogorsk-2021_-_40.jpeg"),
    ("53.434453","58.983333","Views of Magnitogorsk-2021 - 46.jpeg","Жилой дом № 2 по ул. Строителей","https://thumb.wikimedia.org/wikipedia/commons/thumb/5/54/Views_of_Magnitogorsk-2021_-_46.jpeg/1280px-Views_of_Magnitogorsk-2021_-_46.jpeg"),
    ("53.428969","58.983344","Views of Magnitogorsk-2021 - 50.jpeg","Жилой дом № 23 на пр. Ленина","https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b5/Views_of_Magnitogorsk-2021_-_50.jpeg/1280px-Views_of_Magnitogorsk-2021_-_50.jpeg"),
    ("53.421458","58.984092","Views of Magnitogorsk-2021 - 55.jpeg","Площадь Ленина, дома № 43 и № 45 на пр. Ленина","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/01/Views_of_Magnitogorsk-2021_-_55.jpeg/1280px-Views_of_Magnitogorsk-2021_-_55.jpeg"),
    ("53.421050","59.003100","Views of Magnitogorsk-2021 - 58.jpeg","Заводской пруд на реке Урал","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/04/Views_of_Magnitogorsk-2021_-_58.jpeg/1280px-Views_of_Magnitogorsk-2021_-_58.jpeg"),
    ("53.419147","59.003594","Views of Magnitogorsk-2021 - 61.jpeg","Каскад водопадов в сторону пруда","https://thumb.wikimedia.org/wikipedia/commons/thumb/7/79/Views_of_Magnitogorsk-2021_-_61.jpeg/1280px-Views_of_Magnitogorsk-2021_-_61.jpeg"),
    ("53.417869","59.001625","Views of Magnitogorsk-2021 - 64.jpeg","ДК Металлургов (Набережная улица, 1)","https://thumb.wikimedia.org/wikipedia/commons/thumb/8/81/Views_of_Magnitogorsk-2021_-_64.jpeg/1280px-Views_of_Magnitogorsk-2021_-_64.jpeg"),
    ("53.417308","59.001969","Views of Magnitogorsk-2021 - 66.jpeg","Сквер им. 50-летия ММК","https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3e/Views_of_Magnitogorsk-2021_-_66.jpeg/1280px-Views_of_Magnitogorsk-2021_-_66.jpeg"),
    ("53.415700","59.001594","Views of Magnitogorsk-2021 - 68.jpeg","Фонтан «50-летие ММК» в одноимённом сквере","https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9d/Views_of_Magnitogorsk-2021_-_68.jpeg/1280px-Views_of_Magnitogorsk-2021_-_68.jpeg"),
    ("53.411194","58.984722","Views of Magnitogorsk-2021 - 70.jpeg","Стела Славы Магнитки","https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a0/Views_of_Magnitogorsk-2021_-_70.jpeg/1280px-Views_of_Magnitogorsk-2021_-_70.jpeg"),
    ("53.381222","58.990631","Views of Magnitogorsk-2021 - 72.jpeg","Арена «Металлург»","https://thumb.wikimedia.org/wikipedia/commons/thumb/5/55/Views_of_Magnitogorsk-2021_-_72.jpeg/1280px-Views_of_Magnitogorsk-2021_-_72.jpeg"),
    ("53.380375","58.988700","Views of Magnitogorsk-2021 - 74.jpeg","Вид на Арену «Металлург» и Вознесенскую церковь","https://thumb.wikimedia.org/wikipedia/commons/thumb/2/26/Views_of_Magnitogorsk-2021_-_74.jpeg/1280px-Views_of_Magnitogorsk-2021_-_74.jpeg"),
    ("53.378783","58.994806","Views of Magnitogorsk-2021 - 1.jpeg","Улица Завенягина; слева Вознесенская церковь","https://thumb.wikimedia.org/wikipedia/commons/thumb/6/6f/Views_of_Magnitogorsk-2021_-_1.jpeg/1280px-Views_of_Magnitogorsk-2021_-_1.jpeg"),
    ("53.385456","58.998131","Views of Magnitogorsk-2021 - 10.jpeg","Заводской пруд на реке Урал","https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/Views_of_Magnitogorsk-2021_-_10.jpeg/1280px-Views_of_Magnitogorsk-2021_-_10.jpeg"),
    ("53.385442","58.998139","Views of Magnitogorsk-2021 - 11.jpeg","Заводской пруд на реке Урал, другой ракурс","https://thumb.wikimedia.org/wikipedia/commons/thumb/2/29/Views_of_Magnitogorsk-2021_-_11.jpeg/1280px-Views_of_Magnitogorsk-2021_-_11.jpeg"),
    ("53.398269","58.986511","Views of Magnitogorsk-2021 - 13.jpeg","Магнитогорский цирк","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/08/Views_of_Magnitogorsk-2021_-_13.jpeg/1280px-Views_of_Magnitogorsk-2021_-_13.jpeg"),
    ("53.398317","58.986522","Views of Magnitogorsk-2021 - 14.jpeg","Цирк и тротуар на улице Грязнова","https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ae/Views_of_Magnitogorsk-2021_-_14.jpeg/1280px-Views_of_Magnitogorsk-2021_-_14.jpeg"),
    ("53.401111","58.985783","Views of Magnitogorsk-2021 - 15.jpeg","Проспект Ленина, вид на север от улицы Грязнова","https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1f/Views_of_Magnitogorsk-2021_-_15.jpeg/960px-Views_of_Magnitogorsk-2021_-_15.jpeg"),
    ("53.407208","58.986256","Views of Magnitogorsk-2021 - 16.jpeg","Стела «Магнитогорск»","https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1d/Views_of_Magnitogorsk-2021_-_16.jpeg/1280px-Views_of_Magnitogorsk-2021_-_16.jpeg"),
    ("53.407214","58.986267","Views of Magnitogorsk-2021 - 17.jpeg","Стела «Магнитогорск», другой ракурс","https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1a/Views_of_Magnitogorsk-2021_-_17.jpeg/1280px-Views_of_Magnitogorsk-2021_-_17.jpeg"),
    ("53.407825","58.991017","Views of Magnitogorsk-2021 - 20.jpeg","Парк «У Вечного огня»","https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5a/Views_of_Magnitogorsk-2021_-_20.jpeg/1280px-Views_of_Magnitogorsk-2021_-_20.jpeg"),
    ("53.407289","58.992456","Views of Magnitogorsk-2021 - 24.jpeg","Городской пляж и заводской пруд","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/0b/Views_of_Magnitogorsk-2021_-_24.jpeg/1280px-Views_of_Magnitogorsk-2021_-_24.jpeg"),
    ("53.407222","58.992458","Views of Magnitogorsk-2021 - 25.jpeg","Городской пляж, на дальнем плане цеха ММК","https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b3/Views_of_Magnitogorsk-2021_-_25.jpeg/1280px-Views_of_Magnitogorsk-2021_-_25.jpeg"),
    ("53.380131","58.996586","Views of Magnitogorsk-2021 - 3.jpeg","Вознесенская церковь","https://thumb.wikimedia.org/wikipedia/commons/thumb/0/07/Views_of_Magnitogorsk-2021_-_3.jpeg/1280px-Views_of_Magnitogorsk-2021_-_3.jpeg"),
    ("53.406850","58.978775","Views of Magnitogorsk-2021 - 30.jpeg","Городские куранты на площади Народных гуляний","https://thumb.wikimedia.org/wikipedia/commons/thumb/8/84/Views_of_Magnitogorsk-2021_-_30.jpeg/1280px-Views_of_Magnitogorsk-2021_-_30.jpeg"),
    ("53.406894","58.979672","Views of Magnitogorsk-2021 - 31.jpeg","Фонтаны на площади Народных гуляний","https://thumb.wikimedia.org/wikipedia/commons/thumb/2/28/Views_of_Magnitogorsk-2021_-_31.jpeg/1280px-Views_of_Magnitogorsk-2021_-_31.jpeg"),
    ("53.420147","58.981536","Views of Magnitogorsk-2021 - 35.jpeg","Учебный корпус МГТУ на улице Калинина","https://thumb.wikimedia.org/wikipedia/commons/thumb/8/87/Views_of_Magnitogorsk-2021_-_35.jpeg/1280px-Views_of_Magnitogorsk-2021_-_35.jpeg"),
    ("53.421300","58.979817","Views of Magnitogorsk-2021 - 37.jpeg","Учебный корпус МГТУ на проспекте Карла Маркса","https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a9/Views_of_Magnitogorsk-2021_-_37.jpeg/1280px-Views_of_Magnitogorsk-2021_-_37.jpeg"),
    ("53.430058","58.981883","Views of Magnitogorsk-2021 - 38.jpeg","Театр оперы и балета с западной стороны","https://thumb.wikimedia.org/wikipedia/commons/thumb/c/c1/Views_of_Magnitogorsk-2021_-_38.jpeg/1280px-Views_of_Magnitogorsk-2021_-_38.jpeg"),
    ("53.437058","58.981444","Views of Magnitogorsk-2021 - 41.jpeg","Памятная плита на постаменте памятника Рабочему","https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e3/Views_of_Magnitogorsk-2021_-_41.jpeg/960px-Views_of_Magnitogorsk-2021_-_41.jpeg"),
    ("53.437100","58.981239","Views of Magnitogorsk-2021 - 42.jpeg","Памятник Рабочему на привокзальной площади","https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Views_of_Magnitogorsk-2021_-_42.jpeg/1280px-Views_of_Magnitogorsk-2021_-_42.jpeg"),
    ("53.434906","58.983489","Views of Magnitogorsk-2021 - 43.jpeg","Проспект Ленина, вид на север от улицы Московской","https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2f/Views_of_Magnitogorsk-2021_-_43.jpeg/1280px-Views_of_Magnitogorsk-2021_-_43.jpeg"),
]

def commons_page(source_name: str) -> str:
    title = "File:" + source_name.replace(" ", "_")
    return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title, safe=":_-().")

def download(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 4, 12, 30, 60), start=1):
        if delay:
            print(f"  retry {attempt}/5 after {delay}s", flush=True)
            time.sleep(delay)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AnonMGN-GeoGame/1.0 (Wikimedia Commons CC BY-SA photo pack)",
                "Accept": "image/jpeg,image/*;q=0.8,*/*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if len(data) < 10_000:
                raise RuntimeError(
                    f"Downloaded image is unexpectedly small: {url} ({len(data)} bytes)"
                )
            return data
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
    raise RuntimeError(f"Could not download after retries: {url}") from last_error

def main() -> None:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    B64.mkdir(parents=True, exist_ok=True)

    credits = []
    for index, (lat, lon, source_name, description, url) in enumerate(items, start=1):
        filename = f"{lat}_{lon}.jpg"
        path = PHOTOS / filename
        print(f"[{index:02d}/{len(items)}] {filename}", flush=True)
        data = download(url)
        path.write_bytes(data)
        # Be polite to Wikimedia's thumbnail service and avoid burst throttling.
        time.sleep(1.5)
        credits.append({
            "filename": filename,
            "latitude": lat,
            "longitude": lon,
            "description": description,
            "author": "Vyacheslav Bukharov",
            "license": "CC BY-SA 4.0",
            "source_file": source_name,
            "source_page": commons_page(source_name),
        })

    credits_path = OUT / "CREDITS.csv"
    with credits_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(credits[0].keys()))
        writer.writeheader()
        writer.writerows(credits)

    readme = OUT / "README.txt"
    readme.write_text(
        "Magnitogorsk GeoGuessr — 40 photos\n"
        "Image filename format: latitude_longitude.jpg\n"
        "Coordinates are camera/location coordinates from Wikimedia Commons.\n"
        "Photos: Vyacheslav Bukharov, CC BY-SA 4.0.\n"
        "See CREDITS.csv for per-file source pages and attribution.\n",
        encoding="utf-8",
    )

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for photo in sorted(PHOTOS.glob("*.jpg")):
            zf.write(photo, arcname=photo.name)
        zf.write(credits_path, arcname="CREDITS.csv")
        zf.write(readme, arcname="README.txt")

    digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    (OUT / "SHA256.txt").write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")

    encoded = base64.b64encode(ZIP_PATH.read_bytes()).decode("ascii")
    for old in B64.glob("part_*.txt"):
        old.unlink()
    chunk_size = 400_000
    for idx in range(0, len(encoded), chunk_size):
        (B64 / f"part_{idx // chunk_size:03d}.txt").write_text(
            encoded[idx:idx + chunk_size],
            encoding="ascii",
        )
    print(f"ZIP: {ZIP_PATH} ({ZIP_PATH.stat().st_size} bytes)")
    print(f"SHA256: {digest}")
    print(f"base64 parts: {len(list(B64.glob('part_*.txt')))}")

if __name__ == "__main__":
    main()
