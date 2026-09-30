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
GEO_DAILY_REWARD_LIMIT = 100

# Награда теперь зависит не от победы как таковой, а от точности метки.
# Верхняя граница 10 ⭐ за раунд держит экономику предсказуемой даже в игре
# на 10 раундов.
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
    """Разрешаем только игровую метку в районе Магнитогорска.

    Это заодно защищает от случайной отправки пользователем своей текущей
    геопозиции из другого города вместо выбора произвольной точки на карте.
    """
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and _valid_coordinate(latitude, longitude)
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


def select_place_ids(total: int = GEO_ROUNDS, *, excluded: Iterable[int] = ()) -> list[int]:
    excluded_ids = {int(value) for value in excluded}
    pool = [place for place in places() if place.id not in excluded_ids]
    if len(pool) < total:
        pool = list(places())
    if len(pool) < total:
        raise RuntimeError("Для Геогусера пока недостаточно фотографий")
    random.shuffle(pool)
    selected: list[GeoPlace] = []
    # В одной партии не показываем три соседних ракурса одного здания.
    for candidate in pool:
        if all(
            distance_meters(
                candidate.latitude, candidate.longitude,
                chosen.latitude, chosen.longitude,
            ) >= 500
            for chosen in selected
        ):
            selected.append(candidate)
            if len(selected) == total:
                return [place.id for place in selected]
    return [place.id for place in random.sample(pool, total)]


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

