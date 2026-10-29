# -*- coding: utf-8 -*-
"""场馆服务：直接读取史料 front matter 提供场馆目录（不经 LLM，秒级响应）。"""
import re
from functools import lru_cache

from app.config import VENUES_DIR

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
KEYS = ("name", "address", "district", "theme", "opening_hours",
        "reservation", "suggested_duration", "suitable_for")


@lru_cache(maxsize=1)
def list_venues() -> list[dict]:
    venues = []
    for path in sorted(VENUES_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = FM_RE.match(raw)
        if not m:
            continue
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        if not meta.get("name") or meta.get("theme") == "综述":
            continue
        venues.append({
            "name": meta.get("name", ""),
            "address": meta.get("address", ""),
            "district": meta.get("district", ""),
            "theme": meta.get("theme", ""),
            "opening_hours": meta.get("opening_hours", ""),
            "reservation": meta.get("reservation", ""),
            "suggested_duration": meta.get("suggested_duration", ""),
            "suitable_for": [g for g in meta.get("suitable_for", "").split(",") if g],
        })
    return venues


def get_venue(name: str) -> dict | None:
    for v in list_venues():
        if name in v["name"] or v["name"] in name:
            return v
    return None


@lru_cache(maxsize=64)
def get_venue_detail(name: str) -> dict | None:
    """读取场馆史料正文（预置讲解词，按二级小节切分，不调用 LLM）。"""
    for path in sorted(VENUES_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta = {}
        m = FM_RE.match(raw)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            raw = raw[m.end():]
        venue = meta.get("name") or path.stem
        if not (name in venue or venue in name):
            continue

        parts = re.split(r"^##\s+(.+)$", raw, flags=re.M)
        sections = []
        if len(parts) >= 3:
            for i in range(1, len(parts) - 1, 2):
                body = parts[i + 1].strip()
                if body:
                    sections.append({"title": parts[i].strip(), "content": body})
        elif raw.strip():
            sections.append({"title": "场馆简介", "content": raw.strip()})
        return {"name": venue, "sections": sections}
    return None


def themes() -> list[str]:
    return sorted({v["theme"] for v in list_venues()})


# 导览点位跳过的史料小节（面向教师/课程设计，不是参观点位）
_TOUR_SKIP_SECTIONS = {"研学价值"}


@lru_cache(maxsize=64)
def get_tour_route(name: str) -> dict | None:
    """将场馆史料小节解析为导览点位时序线（数据路线 A：小节即点位）。

    Chroma 中每个 chunk 的 metadata.section 即小节标题，因此点位可直接作为
    检索过滤条件，与向量库天然对齐。
    """
    venue = get_venue(name)
    if not venue:
        return None
    detail = get_venue_detail(venue["name"])
    if not detail:
        return None

    points = []
    for sec in detail["sections"]:
        if sec["title"] in _TOUR_SKIP_SECTIONS:
            continue
        # 简介取正文首句（截断），供时间线与卡片展示
        first_sentence = re.split(r"[。！？\n]", sec["content"].strip(), 1)[0]
        points.append({
            "title": sec["title"],
            "brief": first_sentence[:60],
            "section": sec["title"],
        })
    if not points:  # 无有效小节时兜底为单点位
        points.append({"title": "场馆概况", "brief": venue["name"], "section": "场馆概况"})
    return {"venue": venue, "points": points, "total": len(points)}
