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


def themes() -> list[str]:
    return sorted({v["theme"] for v in list_venues()})
