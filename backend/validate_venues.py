# -*- coding: utf-8 -*-
"""史料文件格式校验脚本：字段完整性 / 取值合法性 / 结构一致性 / 长度阈值。

用法：
    python validate_venues.py                    # 校验试点目录 data/venues_new
    python validate_venues.py data/venues        # 校验任意目录（如正式史料库）

校验项：
    1. front matter：首行 ---、8 字段齐全且顺序固定、无 BOM
    2. 取值合法性：theme / suitable_for / district（武汉行政区划）
    3. 结构一致性：# 标题与 name 一致；首小节=场馆概况、末小节=研学价值、小节数>=4
    4. 长度阈值：每小节 100~250 字（容忍 80~320），正文全文 900~2000 字（容忍 700~2400）
    5. 文件以换行符结尾
"""
import re
import sys
from pathlib import Path

# 与 venue_service.py / config.py 保持一致的取值域
THEMES = {"辛亥革命", "党史", "工运", "抗战", "综述"}
GRADES = {"primary_low", "primary_high", "junior", "senior"}
FIELDS = ["name", "address", "district", "theme", "opening_hours",
          "reservation", "suggested_duration", "suitable_for"]

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
H2_RE = re.compile(r"^##\s+(.+)$", re.M)


def parse_meta(fm_text: str) -> dict:
    """按行解析 front matter 键值（与 ingest.py 解析逻辑一致）。"""
    meta = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def validate(path: Path) -> tuple[list[str], list[str]]:
    """校验单个史料文件，返回 (错误列表, 警告列表)。"""
    errors, warnings = [], []

    # 0. 编码检查：不允许 UTF-8 BOM
    if path.read_bytes().startswith(b"\xef\xbb\xbf"):
        errors.append("文件含 UTF-8 BOM（ingest 可解析，但不符合规范）")

    raw = path.read_text(encoding="utf-8")

    # 1. front matter 存在性与字段
    m = FM_RE.match(raw)
    if not m:
        errors.append("缺少 front matter（--- 必须从文件第 1 行开始）")
        return errors, warnings
    meta = parse_meta(m.group(1))

    is_overview = meta.get("theme") == "综述"
    if not is_overview:
        missing = [f for f in FIELDS if not meta.get(f)]
        if missing:
            errors.append(f"front matter 字段缺失或为空：{', '.join(missing)}")
        extra = [k for k in meta if k not in FIELDS]
        if extra:
            warnings.append(f"存在额外字段：{', '.join(extra)}")
        # 字段顺序（按 front matter 文本行序）
        order = [k for k in (parse_meta_line(l) for l in m.group(1).splitlines()) if k]
        if order != [f for f in FIELDS if f in order]:
            errors.append(f"字段顺序不符合规范：{' -> '.join(order)}")

    # 2. 取值合法性
    theme = meta.get("theme", "")
    if theme and theme not in THEMES:
        errors.append(f"theme 取值非法：{theme}（允许：辛亥革命/党史/工运/抗战/综述）")
    district = meta.get("district", "")
    if district and not district.endswith("区") and district != "全市":
        warnings.append(f"district 疑似非武汉行政区划：{district}")
    grades = [g for g in meta.get("suitable_for", "").split(",") if g]
    if grades:
        bad = [g for g in grades if g not in GRADES]
        if bad:
            errors.append(f"suitable_for 含非法学段：{', '.join(bad)}（允许：primary_low/primary_high/junior/senior）")

    # 3. 正文结构
    body = raw[m.end():]
    if not raw.endswith("\n"):
        errors.append("文件未以换行符结尾")
    title_m = re.search(r"^#\s+(.+)$", body, re.M)
    name = meta.get("name", "")
    if not title_m:
        errors.append("正文缺少 # 一级标题")
    elif name and title_m.group(1).strip() != name:
        errors.append(f"# 标题与 name 不一致：标题「{title_m.group(1).strip()}」 vs name「{name}」")

    h2_titles = [t.strip() for t in H2_RE.findall(body)]
    if not is_overview:
        if len(h2_titles) < 4:
            errors.append(f"二级小节不足 4 个（当前 {len(h2_titles)} 个）")
        if h2_titles and h2_titles[0] != "场馆概况":
            errors.append(f"首个小节应为「场馆概况」，实际为「{h2_titles[0]}」")
        if h2_titles and h2_titles[-1] != "研学价值":
            errors.append(f"最后一个小节应为「研学价值」，实际为「{h2_titles[-1]}」")

    # 4. 长度阈值（按小节切分统计正文字数，不含标题行）
    parts = re.split(r"^##\s+(.+)$", body, flags=re.M)
    total = 0
    for i in range(1, len(parts) - 1, 2):
        n = len(parts[i + 1].strip())
        total += n
        if not is_overview:
            if n < 80:
                errors.append(f"小节「{parts[i].strip()}」过短：{n} 字")
            elif n < 100 or n > 320:
                warnings.append(f"小节「{parts[i].strip()}」长度越界：{n} 字（规范 100~250，容忍 80~320）")
    if not is_overview:
        if total < 700:
            errors.append(f"正文总长过短：{total} 字（规范 >=900，下限 700）")
        elif total < 900 or total > 2400:
            warnings.append(f"正文总长越界：{total} 字（规范 900~2000，容忍 700~2400）")

    return errors, warnings


def parse_meta_line(line: str) -> str | None:
    """提取 front matter 行的键名（保持行序用）。"""
    if ":" in line:
        return line.partition(":")[0].strip()
    return None


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data" / "venues_new"
    if not target.exists():
        print(f"[error] 目录不存在：{target}")
        return 2
    files = sorted(target.glob("*.md"))
    if not files:
        print(f"[error] 目录下无 .md 文件：{target}")
        return 2

    n_pass = n_warn = n_fail = 0
    for path in files:
        errors, warnings = validate(path)
        if errors:
            n_fail += 1
            print(f"[FAIL] {path.name}")
            for e in errors:
                print(f"       错误：{e}")
            for w in warnings:
                print(f"       警告：{w}")
        elif warnings:
            n_warn += 1
            print(f"[WARN] {path.name}")
            for w in warnings:
                print(f"       警告：{w}")
        else:
            n_pass += 1
            print(f"[PASS] {path.name}")

    print("-" * 60)
    print(f"合计 {len(files)} 个文件：通过 {n_pass}，警告 {n_warn}，失败 {n_fail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
