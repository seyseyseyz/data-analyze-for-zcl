# xhs_ceramics_analytics/reporting/content_templates.py
"""领域内容模板库 — static, reproducible ceramics content-creation templates.

Pure domain knowledge: parameterized skeletons a merchant fills with their own
系列/器型/尺寸/场景. Every template carries NO data and NO bare numbers (fill-in-the-blank
「占位」slots only), so this appendix ships byte-identically every run and never touches
the numeric-trust boundary. Host-neutral. Rendered as one 可复用内容模板 markdown section
by :func:`content_templates_markdown`. Pure; never raises.

Distilled from the recurring content playbook a手作陶瓷店 needs — 上新节奏、一图多规格、
买前确认、搜索承接、退款预期修正、老客复购 — generalized to placeholders so they apply to
any series/器型 rather than hardcoding this season's names.
"""
from typing import NamedTuple


class ContentTemplate(NamedTuple):
    name: str  # short label shown in bold
    skeleton: str  # the fill-in-the-blank structure (「占位」slots, digit-free)
    when: str  # when to reach for it


# ORDERED playbook. Keep every field digit-free — use 「容量」/「尺寸」placeholders rather
# than concrete measurements, so the library reads as structure, never as (fabricated) data.
CONTENT_TEMPLATES: tuple[ContentTemplate, ...] = (
    ContentTemplate(
        "开窑 / 上新预告",
        "「开窑 / 上新」+「系列名」+「器型」+「上新时间」+ 稀缺感(是否孤品 / 限量 / 手作随机)",
        "有新品或补货节奏时,先立预告、再放量",
    ),
    ContentTemplate(
        "一图多规格对比",
        "同「器型」的「尺寸 / 容量」并列 + 上桌比例参照 + 适用场景(一人食 / 早餐 / brunch / 下午茶)",
        "同系列多规格易选错时,用一张图讲清差异",
    ),
    ContentTemplate(
        "买前确认区(每篇固定收尾)",
        "尺寸 +「容量」+ 釉色随机性 + 是否现货 / 孤品 + 发货节奏 + 适合场景",
        "所有高退款商品笔记统一加,前置管理预期",
    ),
    ContentTemplate(
        "真实餐桌使用",
        "「器型」在真实餐桌 / 食物场景中的到手图 + 与「其他器型」的搭配",
        "内容偏氛围、成交弱时,补足「买回家怎么用」",
    ),
    ContentTemplate(
        "搜索承接笔记",
        "针对「泛类目词」(如 咖啡杯 / 盘子 / 餐具):手握比例 + 器型差异 + 价位带 + 搭配盘",
        "泛类目搜索词有量但转化低时,单独做承接",
    ),
    ContentTemplate(
        "退款预期修正 FAQ",
        "针对高退款「器型」:为什么会拍错 + 怎么选 + 和哪款不同 + 色差 / 随机釉说明",
        "某款「多拍 / 拍错 / 不想要」退款偏高时",
    ),
    ContentTemplate(
        "老客复购提醒",
        "「开窑日历」+ 老客优先提醒 + 成套「系列」搭配补购",
        "复购占比有空间时,给老客单独承接",
    ),
    ContentTemplate(
        "釉色 / 工艺故事",
        "「系列名」的釉色随机性与手作过程 + 「独一无二」预期管理",
        "用工艺叙事把随机性讲成卖点而非售后风险",
    ),
)

_HEADING = "## 可复用内容模板"
_INTRO = (
    "以下为按本店品类沉淀的内容动作模板(纯结构、无数字):"
    "把「占位」替换成自家的系列 / 器型 / 场景即可复用。"
)


def content_templates_markdown() -> str:
    """Render the template library to one markdown section (heading + intro + bullets).

    Plain markdown only — no raw-HTML passthrough, no numbers — so it round-trips through
    the narrative converter as ordinary prose and cannot affect the numeric-trust boundary.
    """
    lines = [_HEADING, "", _INTRO, ""]
    for tpl in CONTENT_TEMPLATES:
        lines.append(f"- **{tpl.name}**:{tpl.skeleton}(何时用:{tpl.when})")
    return "\n".join(lines)
