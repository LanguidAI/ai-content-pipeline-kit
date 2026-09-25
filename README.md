# ai-content-pipeline-kit

给 AI 驱动的短视频内容产线用的**质检与判定组件**。

这些模块解决的是一类特定问题：**自动化产线永远能给你一个成品，但成品不等于合格品。** 渲染脚本不会因为版式错了、语速超了、平台不适配就停下，它只会老实产出一个文件等着你发出去。所以判定必须发生在生成发布包之前，而且必须能输出「不发」。

来自一条连续运行 94 天、产出约 418 个发布包的真实产线。踩过的坑写在这里：[94 天 418 条视频、涨 176 粉、收入 0 元的复盘](https://github.com/LanguidAI/ai-video-pipeline-postmortem)。

## 设计原则

**1. 三态返回，不用布尔值**

所有质检函数返回 `pass` / `failed` / `needs_review`，而不是 `True` / `False`。

因为规则能确定的和不能确定的必须分开：把「规则判不了」静默当成 `pass` 会放过问题，当成 `failed` 会误杀正常内容。`needs_review` 是唯一诚实的第三种答案，它把决定权交回人工。

**2. 缺数据不等于不合格**

上游字段缺失时返回安全默认值（如 `aspect()` 在尺寸缺失时返回 `0.0`），而不是抛异常。抛异常会让当天整批发布包全部生产失败；返回默认值最坏只是少拦一条。

**3. 判定是生成的前置条件，不是后置筛选**

判定不通过就不生成那个平台的发布包——而不是生成完再人工挑。只要文件躺在那里，人就会心软发出去。

**4. 规则外置到配置，测试与配置同源**

平台规则一年改好几次，写死在代码里就得改代码。更要紧的是：测试里的规则常量必须从配置读，不能另抄一份。原实现把策略版本号硬编码在测试 fixture 里，线上配置一改版本号，判定就静默降级成「人工复核」，两条用例长期挂着没人发现。

## 已发布模块

### `acpk.layout_qa` — 竖版视频版式质检

竖版（9:16）视频里横向图片并排摆放，每张会被压到手机上不可读。这个错误渲染阶段不报错，只有人工看片才发现，所以必须提前拦。

```python
from acpk.layout_qa import assess_shot_layout

shot = {
    "assets": [
        {"asset_id": "a", "width": 1664, "height": 928},
        {"asset_id": "b", "width": 1664, "height": 928},
    ],
    "layout": "side_by_side",
}

assess_shot_layout(shot)
# {'status': 'failed',
#  'reason': 'horizontal images must not be side-by-side in vertical video; ...'}
```

| 输入 | 返回 |
| --- | --- |
| ≥2 张横向图 + `side_by_side` | `failed` |
| ≥2 张横向图 + `stacked` / `split_shots` | `pass` |
| ≥2 张横向图 + 其他版式 | `needs_review` |
| 1 张横向图 + `horizontal_focus` / `full_width` / `single` | `pass` |
| 全是竖向图 | `pass` |

可调参数：`HORIZONTAL_ASPECT_THRESHOLD`（默认 `1.4`，取 1.4 而非 16/9≈1.78 是因为实拍截图和图表常落在 1.4~1.7，用 16/9 会漏判）、`FOCUS_LAYOUTS`、`MULTI_HORIZONTAL_LAYOUTS`。

### `acpk.platform_router` — 多平台分发判定

一条素材做好、三个平台全发，看起来效率很高，实际是拿同一套表达去撞三个完全不同的推荐机制：一条内容不可能同时满足「完播+搜索」「社交转发」「前 3 秒冲突」，于是它在三个平台上都表现平庸。

```python
from acpk.platform_router import build_platform_decision

storyboard = {
    "selection_policy_version": "v1",
    "primary_platform": "bilibili",
    "secondary_platforms": [],
    "platform_publish_suggestion": {"bilibili": "publish", "shipinhao": "skip", "douyin": "skip"},
    "bilibili_fit": 82,
    "bilibili_version": {
        "search_question": "工作流调用模型失败怎么办",
        "search_keywords": ["工作流", "Tool Calling"],
        "opening_answer": "参数错误不能靠重试解决",
        "viewer_save_asset": "重试降级熔断判断树",
    },
}

decision = build_platform_decision(storyboard=storyboard)
# decision["mode"]                  -> 'strict_platform_assets_v2'
# decision["recommended_platforms"] -> ['bilibili']
# decision["platforms"]["shipinhao"]["action"] -> 'skip'
```

**三种判定模式**，由输入数据的完整度决定，不需要调用方指定：

| 模式 | 触发条件 | 行为 |
| --- | --- | --- |
| `legacy_no_platform_scores` | 没有策略版本、也没有任何适配分 | 保留发布任务交人工复核。**缺失不当 0 分**，否则存量选题会被全部 skip、产线空转 |
| `score_threshold_v1` | 有适配分、没有策略版本 | 只按阈值判：≥75 `publish`、70~74 `adapt`、<70 `skip` |
| `strict_platform_assets_v2` | 带策略版本 | 主平台 + 最多一个次平台，其余一律 `skip`；叠加分数闸门、必填资产闸门、策略版本闸门 |

**四道闸门按顺序收紧**，任何一道不过就从 `publish` 降级：

1. **产能闸门** —— 不在主/次平台名单里直接 `skip`。真正适配一个平台要重做角度、结构、标题、时长、封面，摊到三个平台就是三个都不达标。
2. **分数闸门** —— 低于该平台 `publish_min_score` 降级。抖音豁免：它的分数常年缺失，用分数判会永远误杀。
3. **资产闸门** —— 分数够不等于能发，缺必填资产一律降 `adapt`。`["", "  "]` 这种有长度没内容的空壳算缺失。抖音的动作点还有上下限（2~3 个）：塞太多等于没重点，太少等于没交付。
4. **策略版本闸门** —— 版本号认不出来时 fail-closed，不猜、不放行，降为人工改写复核。

另外提供 `topic_selection_blocked()` 和 `duplicate_promise()`，把拦截点提前到脚本生成之前。后者防的是自动化产线最大的隐性故障：它会非常稳定地生产同质内容，而流程本身一切正常、不报任何错——人工做号会腻，程序不会。

阈值、必填资产、平台数量上限全部在 `DEFAULT_CONFIG` 里，可以用 `config_from_dict()` / `config_from_json()` 覆盖，改规则不需要改代码。

## 路线图

| 模块 | 状态 | 内容 |
| --- | --- | --- |
| `layout_qa` | ✅ 已发布 | 竖版版式质检 |
| `platform_router` | ✅ 已发布 | 多平台分发判定：`publish` / `adapt` / `skip` 三态、三种判定模式、四道闸门、N 天内容承诺查重 |
| `media_qa` | 🚧 进行中 | 音视频质量闸门：口播语速上限、音频失真阈值、尾部静音时长、BGM 响度区间、TTS 音色参数整套继承 |

## 安装与测试

```bash
pip install -e ".[test]"
pytest
```

要求 Python ≥ 3.10。

## 署名与 AI 辅助

这个仓库里的**设计决策来自一条真实产线**：三态返回、四道闸门、产能守恒、规则外置，
都是在 94 天、418 个发布包的生产过程中迭代出来的判断，不是事后想出来的。

**代码的 Python 转写与测试由 AI（Codex）辅助完成。** 转写的正确性不靠人工肉眼比对，
而是用 20 个用例对原始实现做了逐字段差分验证，0 处不一致。

所以读这个仓库时，请把测试当契约读：`tests/` 里每一条都对应一次真实踩坑，
或一次从原始实现逐条移植的语义。

## 许可

MIT。见 [LICENSE](LICENSE)。
