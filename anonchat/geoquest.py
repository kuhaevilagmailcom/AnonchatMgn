"""Набор мест и геометрия для игры «Геогусер».

Фотографии берутся только из подготовленного JSON с явной лицензией и
атрибуцией. Это намеренно отделено от игровой логики: набор можно обновлять
без миграций SQLite и без изменения хендлеров.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


GEO_ROUNDS = 3
GEO_ROUND_OPTIONS = (3, 5, 10)
GEO_ROUND_SECONDS = 120
GEO_TIE_METERS = 25.0

# Награда теперь зависит не от победы как таковой, а от точности метки.
# Награда начисляется за каждый раунд без дневного лимита.
GEO_REWARD_TIERS: tuple[tuple[float, int], ...] = (
    (100.0, 10),
    (300.0, 8),
    (700.0, 6),
    (1_500.0, 5),
    (3_000.0, 4),
    (5_000.0, 3),
    (8_000.0, 2),
    (15_000.0, 1),
)
# Старые имена оставлены для совместимости с внешними импортами.
GEO_WIN_REWARD = GEO_REWARD_TIERS[0][1]
GEO_TIE_REWARD = GEO_REWARD_TIERS[0][1]

# Некоторые хостинги служебно исключают каталоги с именем ``data``. Поэтому
# игровой набор лежит рядом с модулем, а старый путь читается только для
# обратной совместимости локальных установок.
DATA_PATH = Path(__file__).with_name("geoquest_places.json")
LEGACY_DATA_PATH = Path(__file__).with_name("data") / "geoquest_places.json"
RIGHT_BANK_BOUNDS = (53.32, 53.49, 58.90, 59.025)
RECENT_PLACE_RADIUS_METERS = 180
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


@dataclass(frozen=True, slots=True)
class GeoPlace:
    id: int
    title: str
    latitude: float
    longitude: float
    image_url: str
    source_url: str
    author: str
    license: str
    license_url: str

    @property
    def credit(self) -> str:
        author = self.author.strip() or "автор указан в источнике"
        license_name = self.license.strip() or "свободная лицензия"
        return f"{author} · {license_name}"


def _valid_coordinate(latitude: float, longitude: float) -> bool:
    # Граница города с небольшим запасом для ближайших узнаваемых мест.
    return 53.20 <= latitude <= 53.60 and 58.70 <= longitude <= 59.35


def valid_guess_coordinate(latitude: float, longitude: float) -> bool:
    """Разрешаем любую корректную WGS-84 точку как игровой ответ."""
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    )


def geo_reward(distance: float) -> int:
    """Количество ⭐ за точность одной метки."""
    try:
        meters = max(0.0, float(distance))
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(meters):
        return 0
    for limit, reward in GEO_REWARD_TIERS:
        if meters <= limit:
            return reward
    return 0


def reward_scale_text() -> str:
    return (
        "до 100 м — 10 ⭐ · до 300 м — 8 ⭐ · до 700 м — 6 ⭐\n"
        "до 1,5 км — 5 ⭐ · до 3 км — 4 ⭐ · до 5 км — 3 ⭐\n"
        "до 8 км — 2 ⭐ · до 15 км — 1 ⭐"
    )


@lru_cache(maxsize=1)
def places() -> tuple[GeoPlace, ...]:
    raw = None
    for path in (DATA_PATH, LEGACY_DATA_PATH):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    if raw is None:
        # Аварийный минимум находится в Python-коде: даже если панель хостинга
        # ошибочно отфильтрует JSON, игра не покажет вечное «загружается».
        raw = [
            {
                "id": 10880047, "title": "Место в Магнитогорске",
                "latitude": 53.407019, "longitude": 58.985906,
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/7/7e/Actros_fire_engine_in_Russia.JPG",
                "source_url": "https://commons.wikimedia.org/wiki/File:Actros_fire_engine_in_Russia.JPG",
                "author": "Ardianen", "license": "CC BY-SA 3.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/3.0",
            },
            {
                "id": 16401669, "title": "Гора Мулдак-Тау",
                "latitude": 53.467767, "longitude": 58.769474,
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/e/e7/Quarry_mt._Muldak-Tau.jpg",
                "source_url": "https://commons.wikimedia.org/wiki/File:Quarry_mt._Muldak-Tau.jpg",
                "author": "Pesotsky", "license": "CC BY 3.0",
                "license_url": "https://creativecommons.org/licenses/by/3.0",
            },
            {
                "id": 17275942, "title": "Вершина Магнитной горы",
                "latitude": 53.436323, "longitude": 59.102615,
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/b/bf/Magnitnaya_gora.jpg",
                "source_url": "https://commons.wikimedia.org/wiki/File:Magnitnaya_gora.jpg",
                "author": "Pesotsky", "license": "CC BY 3.0",
                "license_url": "https://creativecommons.org/licenses/by/3.0",
            },
        ]
    result: list[GeoPlace] = []
    seen: set[int] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            place = GeoPlace(
                id=int(item["id"]),
                title=str(item.get("title", "Магнитогорск")).strip(),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                image_url=str(item["image_url"]).strip(),
                source_url=str(item["source_url"]).strip(),
                author=str(item.get("author", "")).strip(),
                license=str(item.get("license", "")).strip(),
                license_url=str(item.get("license_url", "")).strip(),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            place.id in seen
            or not _valid_coordinate(place.latitude, place.longitude)
            or not place.image_url.startswith("https://")
            or not place.source_url.startswith("https://")
        ):
            continue
        seen.add(place.id)
        result.append(place)
    return tuple(result)


def get_place(place_id: int) -> GeoPlace | None:
    return next((place for place in places() if place.id == int(place_id)), None)


def is_urban_place(place: GeoPlace) -> bool:
    title = place.title.casefold()
    return (
        53.32 <= place.latitude <= 53.49
        and 58.90 <= place.longitude <= 59.17
        and not any(word in title for word in NON_URBAN_WORDS)
    )


def is_right_bank_urban(place: GeoPlace) -> bool:
    south, north, west, east = RIGHT_BANK_BOUNDS
    title = place.title.casefold()
    return (
        is_urban_place(place)
        and south <= place.latitude <= north
        and west <= place.longitude <= east
        and any(word in title for word in URBAN_SCENE_WORDS)
    )


def select_place_ids(total: int = GEO_ROUNDS, *, excluded: Iterable[int] = ()) -> list[int]:
    excluded_ids = {int(value) for value in excluded}
    excluded_places = [place for place in places() if place.id in excluded_ids]
    pool = [
        place for place in places()
        if place.id not in excluded_ids
        and all(
            distance_meters(
                place.latitude, place.longitude,
                recent.latitude, recent.longitude,
            ) >= RECENT_PLACE_RADIUS_METERS
            for recent in excluded_places
        )
    ]
    if len(pool) < total:
        pool = list(places())
    if len(pool) < total:
        raise RuntimeError("Для Геогусера пока недостаточно фотографий")
    preferred = [place for place in pool if is_right_bank_urban(place)]
    other_urban = [
        place for place in pool
        if not is_right_bank_urban(place) and is_urban_place(place)
    ]
    other = [place for place in pool if not is_urban_place(place)]
    random.shuffle(preferred)
    random.shuffle(other_urban)
    random.shuffle(other)
    selected: list[GeoPlace] = []

    def add_spaced(candidates: list[GeoPlace], wanted: int) -> None:
        for candidate in candidates:
            if len(selected) >= wanted:
                return
            if all(
                distance_meters(
                    candidate.latitude, candidate.longitude,
                    chosen.latitude, chosen.longitude,
                ) >= 500
                for chosen in selected
            ):
                selected.append(candidate)

    # В каждой партии около 80% городских мест с правого берега.
    preferred_count = min(total, max(1, math.ceil(total * 0.8)))
    add_spaced(preferred, preferred_count)
    if len(selected) < preferred_count:
        remaining_preferred = [place for place in preferred if place not in selected]
        take = min(preferred_count - len(selected), len(remaining_preferred))
        selected.extend(random.sample(remaining_preferred, take))
    add_spaced(other_urban, total)
    add_spaced(other, total)
    add_spaced(preferred, total)
    if len(selected) < total:
        remaining = [place for place in pool if place not in selected]
        selected.extend(random.sample(remaining, total - len(selected)))
    random.shuffle(selected)
    return [place.id for place in selected]


def distance_meters(
    latitude_a: float, longitude_a: float,
    latitude_b: float, longitude_b: float,
) -> float:
    """Расстояние между двумя WGS-84 точками по формуле гаверсинусов."""
    radius = 6_371_008.8
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    d_lat = lat_b - lat_a
    d_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def format_distance(value: float) -> str:
    meters = max(0.0, float(value))
    if meters < 1_000:
        return f"{round(meters):,} м".replace(",", " ")
    return f"{meters / 1_000:.1f} км".replace(".", ",")

