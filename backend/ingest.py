# -*- coding: utf-8 -*-
"""知识库入库脚本：解析场馆史料 Markdown -> 分块 -> BGE 向量化 -> 写入 Chroma。

用法：
    python ingest.py            # 增量入库（默认）
    python ingest.py --reset    # 清空集合后重建
    python ingest.py --stats    # 仅查看统计
"""
import argparse
import re
import sys
from pathlib import Path

# 保证以 `python ingest.py` 直接运行时能导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import (  # noqa: E402
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHROMA_COLLECTION,
    CHROMA_DIR,
    VENUES_DIR,
)

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_venue_md(path: Path) -> tuple[dict, list[dict]]:
    """解析单个场馆 Markdown：front matter 元数据 + 按 `##` 小节切分正文。"""
    raw = path.read_text(encoding="utf-8")
    meta = {}
    m = FM_RE.match(raw)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]

    title_m = re.search(r"^#\s+(.+)$", raw, re.M)
    venue = meta.get("name") or (title_m.group(1).strip() if title_m else path.stem)

    sections = []
    # 概览块：场馆名 + 元数据，保证"XX馆几点开门/在哪"类问题可命中
    overview = [f"场馆名称：{venue}"]
    for key in ("address", "district", "theme", "opening_hours", "reservation",
                "suggested_duration", "suitable_for"):
        if meta.get(key):
            overview.append(f"{key}：{meta[key]}")
    sections.append({"section": "场馆信息", "content": "\n".join(overview)})

    # 正文按二级标题切分
    parts = re.split(r"^##\s+(.+)$", raw, flags=re.M)
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            body = parts[i + 1].strip()
            if body:
                sections.append({"section": parts[i].strip(), "content": body})
    elif raw.strip():
        sections.append({"section": "正文", "content": raw.strip()})
    return meta, sections


def chunk_sections(sections: list[dict], venue: str, meta: dict) -> list:
    """小节内再做细粒度分块，控制召回块的上下文长度。"""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "，", " "],
    )
    docs = []
    for sec in sections:
        for chunk in splitter.split_text(sec["content"]):
            docs.append(Document(
                page_content=f"{venue}｜{sec['section']}\n{chunk}",
                metadata={
                    "venue": venue,
                    "section": sec["section"],
                    "theme": meta.get("theme", ""),
                    "district": meta.get("district", ""),
                    "source": "venues",
                },
            ))
    return docs


def ingest(reset: bool = False) -> dict:
    if reset and CHROMA_DIR.exists():
        import shutil
        shutil.rmtree(CHROMA_DIR)
        print(f"[reset] 已删除旧集合目录 {CHROMA_DIR}")

    all_docs = []
    files = sorted(VENUES_DIR.glob("*.md"))
    if not files:
        print(f"[error] 未找到史料文件：{VENUES_DIR}")
        return {"venues": 0, "chunks": 0}

    for path in files:
        meta, sections = parse_venue_md(path)
        docs = chunk_sections(sections, meta.get("name", path.stem), meta)
        all_docs.extend(docs)
        print(f"[parse] {path.name:<28} -> {len(docs):>3} 块  ({meta.get('name', '')})")

    print(f"[embed] 正在加载 {CHROMA_COLLECTION} 用的 BGE 模型并生成向量 …")
    from app.core.vectorstore import add_documents

    add_documents(all_docs)  # BGE 向量化后 upsert 入 Chroma，自动持久化
    print(f"[done] 共入库 {len(all_docs)} 个文本块，集合：{CHROMA_COLLECTION}")

    # 知识库已重建，清空语义缓存，避免回放基于旧史料的答案
    from app.core import cache as answer_cache
    cleared = answer_cache.clear()
    print(f"[cache] 已清空语义缓存 {cleared} 条")
    return {"venues": len(files), "chunks": len(all_docs)}


def stats() -> dict:
    from app.core.vectorstore import collection_stats

    print(collection_stats())
    return collection_stats()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="武汉红色文化知识库入库")
    parser.add_argument("--reset", action="store_true", help="清空后重建")
    parser.add_argument("--stats", action="store_true", help="仅查看统计")
    args = parser.parse_args()

    if args.stats:
        stats()
    else:
        ingest(reset=args.reset)
