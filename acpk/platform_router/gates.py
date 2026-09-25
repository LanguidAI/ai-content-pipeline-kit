"""选题闸门：在进入脚本生成之前就拦掉不该投产的选题。

这个闸门必须在生成之前，不是之后。原因和判定一样——
产线永远能给你一个成品，拦不住的唯一办法是让下一步根本不发生。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .decision import _as_dict, _text


def topic_selection_blocked(topic: Any) -> bool:
    """选题是否应在生成脚本前被阻断。

    阻断条件：未被选中，或查重判定为重复。
    非法输入（None、非对象）一律阻断——fail-closed。
    """
    data = _as_dict(topic)
    if not data:
        return True
    duplicate_status = _text((data.get("duplicate_check") or {}).get("status")).strip().lower()
    if data.get("selected") is False:
        return True
    return duplicate_status == "duplicate"


def duplicate_promise(
    promise: str,
    recent_promises: Iterable[str],
    *,
    lookback_days: int = 14,
    used_days_ago: Mapping[str, int] | None = None,
) -> dict:
    """检查内容承诺是否在回溯窗口内重复使用。

    自动化产线最大的隐性故障是：它会非常稳定地生产同质内容，
    而流程本身一切正常、不报任何错。人工做号会腻，程序不会。
    因此相同的标题句式、视觉结构或内容承诺，在回溯窗口内不许复用。

    `used_days_ago` 传入 {承诺: 距今天数}；缺省时认为所有近期承诺都在窗口内。
    """
    key = _text(promise).strip()
    if not key:
        return {"status": "clear", "reason": "空承诺不参与查重。"}

    recent = {_text(p).strip() for p in recent_promises if _text(p).strip()}
    used = used_days_ago or {}
    if key in recent:
        age = used.get(key)
        if age is None or age <= lookback_days:
            days = f"（{age} 天前用过）" if age is not None else ""
            return {
                "status": "duplicate",
                "reason": f"内容承诺在 {lookback_days} 天内已使用{days}，必须换角度；换不出来就降级或暂缓。",
            }
    return {"status": "clear", "reason": f"{lookback_days} 天内未使用该内容承诺。"}
