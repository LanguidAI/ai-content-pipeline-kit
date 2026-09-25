"""三态判定与模式常量。

为什么是 publish / adapt / skip 而不是布尔值：
自动化产线永远能产出一个成品，所以「不发」必须是一个显式的、
能真正阻止发布包生成的状态，而不是「生成了但标记为不推荐」。
只要文件存在，人就会心软发出去。
"""

from __future__ import annotations

PUBLISH = "publish"
ADAPT = "adapt"
SKIP = "skip"

VALID_ACTIONS = frozenset({PUBLISH, ADAPT, SKIP})

# legacy：老选题没有平台适配分。缺失按「保留 + 人工复核」处理，
# 绝不当 0 分——当 0 分会让存量选题全部被 skip，产线直接空转。
MODE_LEGACY_NO_SCORES = "legacy_no_platform_scores"
# strict：带选题策略版本，走严格的必填资产校验。
MODE_STRICT_ASSETS = "strict_platform_assets_v2"
# score：有适配分但没有策略版本，只按阈值判。
MODE_SCORE_THRESHOLD = "score_threshold_v1"

# 策略版本可识别。
POLICY_CURRENT = "current"
# 策略版本无法识别时 fail-closed：不猜、不放行，降级为人工改写复核。
POLICY_UNKNOWN_FAIL_CLOSED = "unknown_fail_closed"


def normalize_action(value: object) -> str:
    """把任意来源的动作值归一到三态之一；无法识别时返回空串。

    返回空串而不是抛异常或默认 skip，是为了让调用方能继续尝试
    下一个来源（平台建议 → 版本动作 → 评估建议 → 兜底），
    这条优先级链是判定正确性的关键。
    """
    text = str(value or "").strip().lower()
    return text if text in VALID_ACTIONS else ""
