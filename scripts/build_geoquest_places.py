"""Собирает легальный набор геофотографий Магнитогорска из Wikimedia Commons.

Запуск:
    python scripts/build_geoquest_places.py

Скрипт сохраняет только файлы со свободной лицензией, координатами и полной
атрибуцией. Изображения не копируются в репозиторий: Telegram получает URL
уменьшенной версии от Wikimedia.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from pathlib import Path


API = "https://commons.wikimedia.org/w/api.php"
OUTPUT = Path(__file__).resolve().parents[1] / "anonchat" / "geoquest_places.json"
# Правый берег Магнитогорска — западнее Урала, здесь сосредоточена основная
# жилая застройка. Несколько небольших радиусов дают улицы и дома, а не поля
# в десяти километрах от города.
CENTERS = (
    (53.424, 58.982),
    (53.451, 58.991),
    (53.398, 58.975),
    (53.373, 58.982),
    (53.348, 58.965),
    (53.405, 58.935),
)
ALLOWED_LICENSES = ("CC BY", "CC0", "PUBLIC DOMAIN", "NO RESTRICTIONS")
TARGET_COUNT = 650
RIGHT_BANK_BOUNDS = (53.32, 53.49, 58.90, 59.025)
NON_URBAN_WORDS = (
    "поле", "степ", "гора", "горы ", "вершина", "карьер", "озеро", "лес", "закат",
    "восход", "обла", "цвет", "птиц", "eclipse", "mountain", "quarry",
    "landscape", "forest", "sunset", "lake", "парад", "мото", "автомоб",
    "машин", "вагон", "мкс", "гроз", "truck", "vehicle", "motorcycle", "parade", "iss ",
)
URBAN_SCENE_WORDS = (
    "улиц", "просп", "дом", "здан", "двор", "район", "квартал", "площад",
    "парк", "театр", "храм", "церк", "школ", "универс", "мгту", "памят",
    "стел", "мост", "переправ", "вокзал", "станц", "арен", "цирк",
    "администрац", "бульвар", "шоссе", "street", "ulitsa", "building",
    "theatre", "church", "monument", "park",
)


def plain(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(value or "")).split())


def is_right_bank(row: dict) -> bool:
    south, north, west, east = RIGHT_BANK_BOUNDS
    return south <= float(row["latitude"]) <= north and west <= float(row["longitude"]) <= east


def looks_urban(row: dict) -> bool:
    title = str(row.get("title", "")).casefold()
    return (
        not any(word in title for word in NON_URBAN_WORDS)
        and any(word in title for word in URBAN_SCENE_WORDS)
    )


def request(params: dict[str, str]) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "AnonMGN-GeoQuest/1.0 "
                "(https://github.com/kuhaevilagmailcom/AnonchatMgn)"
            )
        },
    )
    for attempt in range(10):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if attempt >= 9:
                raise
            retry_after = int(error.headers.get("Retry-After", "0") or 0)
            time.sleep(max(retry_after, min(60, 10 + attempt * 5)))
        except Exception:
            if attempt >= 9:
                raise
            time.sleep(min(60, 5 + attempt * 5))
    return {}


def collect() -> list[dict]:
    by_id: dict[int, dict] = {}
    if OUTPUT.exists():
        try:
            for item in json.loads(OUTPUT.read_text(encoding="utf-8")):
                by_id[int(item["id"])] = item
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            by_id.clear()
    for latitude, longitude in CENTERS:
        continuation: dict[str, str] = {}
        pages_read = 0
        while len(by_id) < TARGET_COUNT:
            params = {
                "action": "query", "format": "json", "formatversion": "2",
                "generator": "geosearch", "ggsprimary": "all", "ggsnamespace": "6",
                "ggsradius": "4500", "ggscoord": f"{latitude}|{longitude}", "ggslimit": "50",
                "prop": "coordinates|imageinfo", "iiprop": "url|extmetadata|mime",
                "iiurlwidth": "1280", "maxlag": "5", **continuation,
            }
            data = request(params)
            pages_read += 1
            for page in data.get("query", {}).get("pages", []):
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata") or {}
                coordinates = page.get("coordinates") or []
                try:
                    lat = float(coordinates[0]["lat"] if coordinates else meta["GPSLatitude"]["value"])
                    lon = float(coordinates[0]["lon"] if coordinates else meta["GPSLongitude"]["value"])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if not (53.20 <= lat <= 53.60 and 58.70 <= lon <= 59.35):
                    continue
                license_name = plain(meta.get("LicenseShortName", {}).get("value", ""))
                if not any(license_name.upper().startswith(prefix) for prefix in ALLOWED_LICENSES):
                    continue
                if not str(info.get("mime", "")).startswith("image/"):
                    continue
                image_url = str(info.get("thumburl", ""))
                source_url = str(info.get("descriptionurl", ""))
                if not image_url.startswith("https://") or not source_url.startswith("https://"):
                    continue
                page_id = int(page.get("pageid", 0))
                title = plain(meta.get("ImageDescription", {}).get("value", ""))
                if not title:
                    title = str(page.get("title", "Магнитогорск")).removeprefix("File:")
                by_id[page_id] = {
                    "id": page_id,
                    "title": title[:160],
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "image_url": image_url,
                    "source_url": source_url,
                    "author": plain(meta.get("Artist", {}).get("value", ""))[:120],
                    "license": license_name[:80],
                    "license_url": str(meta.get("LicenseUrl", {}).get("value", "")),
                }
            nxt = data.get("continue") or {}
            if not nxt or pages_read >= 10:
                break
            continuation = {str(key): str(value) for key, value in nxt.items()}
            # Wikimedia просит не делать массовые запросы рывком.
            time.sleep(12)
        if len(by_id) >= TARGET_COUNT:
            break
        time.sleep(12)

    # Сначала жилой правый берег и городские сюжеты. Левобережные и природные
    # фотографии остаются небольшой добавкой для разнообразия, но не забивают игру.
    rows = list(by_id.values())
    rows.sort(
        key=lambda row: (
            not (is_right_bank(row) and looks_urban(row)),
            not is_right_bank(row),
            not looks_urban(row),
            int(row["id"]),
        )
    )
    return rows[:TARGET_COUNT]


def main() -> None:
    rows = collect()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    right = sum(is_right_bank(row) for row in rows)
    urban_right = sum(is_right_bank(row) and looks_urban(row) for row in rows)
    print(f"saved {len(rows)} places: right_bank={right}, urban_right_bank={urban_right}")


if __name__ == "__main__":
    main()
