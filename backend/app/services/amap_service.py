# -*- coding: utf-8 -*-
"""高德地图 Web 服务封装：场馆地理编码 + 公交/地铁路径规划（跨场馆研学路线用）。

设计要点：
- 可选依赖：未配置 AMAP_KEY 时整体优雅降级（available=false），不影响主功能；
- 定位两级策略：地址地理编码失败时回退 POI 名称检索（纪念馆类地标按名称更稳，
  且部分门牌含连字符区间（如"胜利街332-352号"）会导致地理编码失败）；
- 地理编码结果进程内缓存（场馆位置固定，无需持久化）；
- v5 换乘接口的 city1/city2 必须传城市 adcode（武汉=420100），传城市名会被拒绝；
- 解析 v5 换乘接口返回的步行/公交分段，重组为前端可直接渲染的简洁结构；
- 任何网络/解析异常均转为单段错误信息，不阻断其它路段规划。
"""
import asyncio
import time

import httpx

from app.config import AMAP_KEY

GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
POI_URL = "https://restapi.amap.com/v3/place/text"
TRANSIT_URL = "https://restapi.amap.com/v5/direction/transit/integrated"
CITY = "武汉"
CITY_ADCODE = "420100"  # 武汉市 adcode（v5 路径规划接口要求）

_geo_cache: dict[str, tuple[str, str]] = {}  # "name|address" -> (lng, lat)

# 换乘方案最多返回给前端的条数
MAX_PLANS_PER_LEG = 2


def available() -> bool:
    return bool(AMAP_KEY)


async def _get(url: str, params: dict) -> dict | None:
    """GET 请求并校验高德返回结构；异常返回 None（附失败原因日志便于排查）。"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={**params, "key": AMAP_KEY})
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") == "1" or data.get("errcode") == 0:
            return data
        reason = data.get("info") or data.get("errmsg") or f"infocode={data.get('infocode')}"
        print(f"[warn] 高德接口返回失败 {url.split('/')[-1]}：{reason}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 高德接口请求异常 {url.split('/')[-1]}：{type(e).__name__}: {e}")
        return None


async def _geocode(address: str) -> tuple[str, str] | None:
    """地址 -> (lng, lat)，v3 地理编码。"""
    data = await _get(GEO_URL, {"address": address, "city": CITY})
    if not data:
        return None
    geos = data.get("geocodes") or []
    if geos and geos[0].get("location"):
        lng, lat = geos[0]["location"].split(",")
        return (lng, lat)
    return None


async def _poi_search(name: str) -> tuple[str, str] | None:
    """场馆名 POI 检索 -> (lng, lat)：纪念馆类地标的地址门牌编码失败时更稳。"""
    data = await _get(POI_URL, {"keywords": name, "city": CITY, "citylimit": "true"})
    if not data:
        return None
    pois = data.get("pois") or []
    if pois and pois[0].get("location"):
        lng, lat = pois[0]["location"].split(",")
        return (lng, lat)
    return None


async def locate(name: str, address: str) -> tuple[str, str] | None:
    """场馆定位：先地址地理编码，失败回退场馆名 POI 检索（结果进缓存）。"""
    cache_key = f"{name}|{address}"
    if cache_key in _geo_cache:
        return _geo_cache[cache_key]
    loc = await _geocode(address) or await _poi_search(name)
    if loc:
        _geo_cache[cache_key] = loc
    return loc


def _fmt_duration(seconds) -> str:
    try:
        minutes = max(1, round(int(seconds) / 60))
        return f"约 {minutes} 分钟" if minutes < 60 else f"约 {minutes // 60} 小时{minutes % 60}分钟"
    except (TypeError, ValueError):
        return "时长未知"


def _fmt_distance(meters) -> str:
    try:
        m = int(meters)
        return f"{m / 1000:.1f} 公里" if m >= 1000 else f"{m} 米"
    except (TypeError, ValueError):
        return "距离未知"


def _parse_segments(transit: dict) -> list[dict]:
    """把高德 v5 换乘方案的 segments 重组为 [{type, text}]。"""
    segments = []
    for seg in transit.get("segments") or []:
        walking = seg.get("walking") or {}
        if walking.get("distance") and int(walking.get("distance") or 0) > 0:
            segments.append({
                "type": "walk",
                "text": f"步行 {_fmt_distance(walking['distance'])}（{_fmt_duration(walking.get('duration'))}）",
            })
        bus = seg.get("bus") or {}
        for line in (bus.get("buslines") or [])[:1]:  # 每段只取推荐线路
            name = line.get("name", "公交/地铁")
            dep = line.get("departure_stop") or {}
            arr = line.get("arrival_stop") or {}
            dep_name = dep.get("name", "") if isinstance(dep, dict) else str(dep)
            arr_name = arr.get("name", "") if isinstance(arr, dict) else str(arr)
            stops = line.get("via_num")
            stop_part = f"{stops} 站" if stops else ""
            route_part = f"{dep_name} → {arr_name}" if dep_name and arr_name else ""
            text = " ".join(x for x in (name, route_part, stop_part) if x)
            segments.append({"type": "subway" if "地铁" in name or "轨道交通" in name else "bus", "text": text})
    return segments


def _parse_transit(transit: dict) -> dict | None:
    segments = _parse_segments(transit)
    if not segments:
        return None
    summary = " → ".join(
        (s["text"].split("（")[0].split("：")[0] if s["type"] == "walk" else s["text"].split("：")[0])
        for s in segments
    )
    return {
        "summary": summary[:120],
        "duration": _fmt_duration(transit.get("duration")),
        "distance": _fmt_distance(transit.get("distance")),
        "segments": segments,
    }


async def _plan_leg(from_name: str, from_addr: str, to_name: str, to_addr: str) -> dict:
    """规划相邻两场馆的公交换乘方案。"""
    origin, dest = await asyncio.gather(
        locate(from_name, from_addr), locate(to_name, to_addr))
    if not origin or not dest:
        return {"from": from_name, "to": to_name,
                "error": "场馆定位失败（地址与名称均未解析到坐标）"}

    data = await _get(TRANSIT_URL, {
        "origin": ",".join(origin),
        "destination": ",".join(dest),
        "city1": CITY_ADCODE,
        "city2": CITY_ADCODE,
        "show_fields": "cost",
        "strategy": "0",  # 推荐方案（速度优先）
    })
    if not data:
        return {"from": from_name, "to": to_name, "error": "换乘规划请求失败，请稍后重试"}

    route = (data.get("route") or {})
    plans = []
    for t in (route.get("transits") or [])[:MAX_PLANS_PER_LEG]:
        parsed = _parse_transit(t)
        if parsed:
            plans.append(parsed)
    if not plans:
        return {"from": from_name, "to": to_name, "error": "未找到可行公交方案，建议打车或步行"}
    return {"from": from_name, "to": to_name, "plans": plans}


async def plan_transit(venue_items: list[dict]) -> dict:
    """按顺序规划多场馆两两换乘。venue_items: [{name, address}]。"""
    if not available():
        return {"available": False, "message": "未配置高德地图 Key（AMAP_KEY），暂无法查询真实换乘"}

    legs = []
    for a, b in zip(venue_items, venue_items[1:]):
        legs.append(await _plan_leg(a["name"], a["address"], b["name"], b["address"]))
    return {"available": True, "legs": legs, "planned_at": int(time.time())}
