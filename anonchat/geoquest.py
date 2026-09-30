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
GEO_WIN_REWARD = 3
GEO_TIE_REWARD = 2
GEO_TIE_METERS = 25.0
GEO_DAILY_REWARD_LIMIT = 30

DATA_PATH = Path(__file__).with_name("data") / "geoquest_places.json"


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


@lru_cache(maxsize=1)
def places() -> tuple[GeoPlace, ...]:
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
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

