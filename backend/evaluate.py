# -*- coding: utf-8 -*-
"""分学段评测脚本：量化 RAG 系统的检索命中、答案质量与拒答正确性。

用法（在 backend/ 目录下执行）：
    python evaluate.py                          # 等价 --mode retrieval（免费，不调 LLM）
    python evaluate.py --mode retrieval --grade junior
    python evaluate.py --mode full --limit 8    # 抽样全链路评测（消耗 GLM 配额，较慢）
    python evaluate.py --mode full --no-cache   # 绕过语义缓存强制重新生成

指标说明：
    检索命中率   知识库内题目中，期望场馆出现在 Top-K 召回来源里的比例
    关键词覆盖率 答案包含期望关键词的平均比例（仅 full 模式，考察答案质量）
    拒答正确率   知识库外题目中，答案包含规范拒答话术的比例（仅 full 模式，考察幻觉抑制）
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DATASET_PATH = Path(__file__).resolve().parent / "data" / "eval_dataset.json"
# 与 prompts.py 中"诚实告知无史料"的规范话术对齐
REFUSAL_MARKERS = ["没有找到", "未找到", "未检索到", "没有相关", "无法回答",
                   "暂时没有", "找不到", "没有可靠史料", "无法提供"]

GRADE_LABELS = {
    "primary_low": "小学低年级", "primary_high": "小学高年级",
    "junior": "初中", "senior": "高中",
}
GRADE_ORDER = ["primary_low", "primary_high", "junior", "senior"]


def load_items(grade: str | None, limit: int | None) -> list[dict]:
    items = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if grade:
        items = [it for it in items if it["grade"] == grade]
    if limit:
        items = items[:limit]
    return items


def check_retrieval(item: dict) -> bool:
    """检索评测：期望场馆是否出现在 Top-K 召回中。"""
    from app.core.vectorstore import search
    docs = search(item["question"])
    item["_venues"] = [d.metadata.get("venue", "") for d in docs]
    return item["expected_venue"] in item["_venues"]


async def check_full(item: dict) -> None:
    """全链路评测：真实生成（学段分级），记录答案与耗时。"""
    from app.core.rag import agenerate
    t0 = time.time()
    try:
        result = await agenerate(item["question"], grade=item["grade"])
        item["_answer"] = result["answer"]
        item["_cached"] = result.get("cached", False)
    except Exception as e:  # noqa: BLE001
        item["_answer"] = ""
        item["_error"] = f"{type(e).__name__}: {str(e)[:80]}"
    item["_elapsed"] = round(time.time() - t0, 1)


def keyword_coverage(item: dict) -> float:
    kws = item.get("expected_keywords") or []
    if not kws:
        return 0.0
    answer = item.get("_answer", "")
    return sum(1 for k in kws if k in answer) / len(kws)


def refused(item: dict) -> bool:
    return any(m in item.get("_answer", "") for m in REFUSAL_MARKERS)


def print_item(item: dict, mode: str) -> None:
    tag = item["id"]
    if item.get("_error"):
        print(f"  [{tag}] ERROR {item['_error']}  {item['question']}")
        return
    if item.get("out_of_kb"):
        if mode == "full":
            mark = "拒答✓" if item.get("_refused") else "拒答✗(疑似编造)"
            print(f"  [{tag}] {mark}  {item['question']}")
        else:
            top = (item.get("_venues") or ["-"])[0]
            print(f"  [{tag}] 知识库外题（Top1 召回：{top}）  {item['question']}")
        return
    ret = "检索✓" if item.get("_ret_hit") else "检索✗"
    if mode == "full":
        kws = item.get("expected_keywords") or []
        hit = sum(1 for k in kws if k in item.get("_answer", ""))
        cached = " [缓存]" if item.get("_cached") else ""
        print(f"  [{tag}] {ret} 关键词 {hit}/{len(kws)} {item.get('_elapsed', 0)}s{cached}  {item['question']}")
        if not item.get("_ret_hit"):
            print(f"         召回：{'、'.join(item.get('_venues') or [])}")
    else:
        print(f"  [{tag}] {ret}  {item['question']}")
        if not item.get("_ret_hit"):
            print(f"         召回：{'、'.join(item.get('_venues') or [])}")


def summarize(items: list[dict], mode: str) -> None:
    print(f"\n====== 评测汇总（mode={mode}，共 {len(items)} 题）======")
    print(f"{'学段':<6}{'题数':>4}  {'检索命中':>8}", end="")
    if mode == "full":
        print(f"  {'关键词覆盖':>8}  {'拒答正确':>8}", end="")
    print()
    for g in GRADE_ORDER:
        sub = [i for i in items if i["grade"] == g]
        if not sub:
            continue
        in_kb = [i for i in sub if not i.get("out_of_kb")]
        out_kb = [i for i in sub if i.get("out_of_kb")]
        ret = sum(1 for i in in_kb if i.get("_ret_hit"))
        line = f"{GRADE_LABELS[g]:<6}{len(sub):>4}  {ret:>4}/{len(in_kb):<3}"
        if mode == "full":
            cov = sum(i.get("_cov", 0.0) for i in in_kb) / max(len(in_kb), 1)
            ref = sum(1 for i in out_kb if i.get("_refused"))
            line += f"  {cov:>7.0%}  {ref:>4}/{len(out_kb):<3}"
        print(line)
    # 总计
    in_kb = [i for i in items if not i.get("out_of_kb")]
    out_kb = [i for i in items if i.get("out_of_kb")]
    ret = sum(1 for i in in_kb if i.get("_ret_hit"))
    line = f"{'总计':<6}{len(items):>4}  {ret:>4}/{len(in_kb):<3}"
    if mode == "full":
        cov = sum(i.get("_cov", 0.0) for i in in_kb) / max(len(in_kb), 1)
        ref = sum(1 for i in out_kb if i.get("_refused"))
        errs = sum(1 for i in items if i.get("_error"))
        line += f"  {cov:>7.0%}  {ref:>4}/{len(out_kb):<3}  生成失败 {errs}"
    print(line)


async def run_full(items: list[dict]) -> None:
    for i, item in enumerate(items, 1):
        await check_full(item)
        item["_ret_hit"] = check_retrieval(item)
        item["_cov"] = keyword_coverage(item)
        item["_refused"] = refused(item)
        print_item(item, "full")
        print(f"         ({i}/{len(items)})", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="武汉红色文化导览系统分学段评测")
    parser.add_argument("--mode", choices=["retrieval", "full"], default="retrieval",
                        help="retrieval=仅检索（免费）；full=完整生成（消耗 GLM 配额）")
    parser.add_argument("--grade", choices=GRADE_ORDER, default=None, help="只评测指定学段")
    parser.add_argument("--limit", type=int, default=None, help="限制评测题数（截断数据集）")
    parser.add_argument("--no-cache", action="store_true", help="full 模式下绕过语义缓存")
    parser.add_argument("--engine", choices=["auto", "vector", "hybrid"], default="auto",
                        help="检索引擎：auto=按配置；vector=纯向量基线；hybrid=BM25+RRF 混合（对比实验）")
    args = parser.parse_args()

    # 环境开关需在导入 app 模块前生效（load_dotenv 不覆盖已存在的环境变量）
    if args.no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    if args.engine == "vector":
        os.environ["HYBRID_ENABLED"] = "false"
        os.environ["RERANKER_ENABLED"] = "false"
    elif args.engine == "hybrid":
        os.environ["HYBRID_ENABLED"] = "true"

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    items = load_items(args.grade, args.limit)
    if not items:
        print("评测集为空：请检查 --grade / --limit 参数")
        return

    engine_note = f"，engine={args.engine}" if args.engine != "auto" else ""
    print(f"载入评测集 {len(items)} 题（mode={args.mode}{engine_note}"
          f"{'，grade=' + args.grade if args.grade else ''}）\n")

    if args.mode == "retrieval":
        for item in items:
            if item.get("out_of_kb"):
                check_retrieval(item)  # 仅记录召回分布，不计入命中统计
                item["_ret_hit"] = False
            else:
                item["_ret_hit"] = check_retrieval(item)
            print_item(item, "retrieval")
    else:
        asyncio.run(run_full(items))

    summarize(items, args.mode)


if __name__ == "__main__":
    main()
