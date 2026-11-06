# -*- coding: utf-8 -*-
"""输入安全边界：未成年人产品的第一道内容闸门（本地规则层）。

职责：拦截明显的违规输入与提示注入，清洗控制字符。
定位：本地规则只做"明确违规"的粗过滤（色情/赌博/毒品/暴力教唆/注入攻击），
不做语义判断——正常红色文化提问不会误伤；精细审核依赖硅基流动服务端内容安全。
"""
import re

# 明确违规词表（拼音变体常见形式一并覆盖；保持短小，避免误伤正常历史提问）
_BLOCKLIST = [
    "色情", "裸聊", "约炮", "嫖娼", "卖淫", "成人片", "av网站",
    "赌博", "博彩", "下注", "网赌", "六合彩",
    "吸毒", "冰毒", "大麻", "摇头丸", "贩毒",
    "自杀教程", "自残方法", "制爆", "造枪",
    "开盒", "人肉搜索教程",
]

# 提示注入特征：试图改写系统角色/泄露系统提示的指令
_INJECTION_PATTERNS = [
    re.compile(r"忽略(之前|以上|上面)(的)?(所有)?(指令|提示|设定)", re.I),
    re.compile(r"(system\s*prompt|系统提示词|你的设定).{0,6}(是什么|输出|泄露|打印)", re.I),
    re.compile(r"(你现在是|从现在开始你是|扮演).{0,12}(没有限制|无限制|不受约束|dan)", re.I),
]

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_question(text: str) -> str:
    """清洗输入：去除控制字符与首尾空白，压缩连续空白。"""
    cleaned = _CONTROL_RE.sub("", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def check_question(text: str) -> tuple[bool, str]:
    """规则审查。返回 (是否放行, 拒绝理由)。拒绝理由面向儿童，语气友好。"""
    normalized = text.lower()
    for word in _BLOCKLIST:
        if word in normalized:
            return False, "这个问题不太适合小助手回答，我们可以聊聊革命先辈的故事哦～"
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return False, "小助手只回答武汉红色文化相关的问题哦～"
    return True, ""
