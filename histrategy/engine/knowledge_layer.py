"""
Knowledge Layer — generates and serves historical knowledge cards.

Each card connects a game event to:
1. Historical source (史料引用)
2. Modern scholarship (现代学术解读)
3. Engine logic (系统逻辑解释)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeCard:
    """A knowledge card connecting game events to real history."""
    topic: str
    trigger_event: str = ""              # What game event triggered this card
    historical_source: str = ""          # e.g., "《三国志·魏书·武帝纪》"
    source_quote: str = ""               # Original text quote
    modern_scholarship: str = ""         # Modern academic interpretation
    scholar: str = ""                    # Scholar name
    scholar_work: str = ""               # Scholar's work
    engine_logic: str = ""               # How the engine models this
    related_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "trigger_event": self.trigger_event,
            "historical_source": self.historical_source,
            "source_quote": self.source_quote,
            "modern_scholarship": self.modern_scholarship,
            "scholar": self.scholar,
            "scholar_work": self.scholar_work,
            "engine_logic": self.engine_logic,
            "related_topics": self.related_topics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeCard":
        return cls(
            topic=data.get("topic", ""),
            trigger_event=data.get("trigger_event", ""),
            historical_source=data.get("historical_source", ""),
            source_quote=data.get("source_quote", ""),
            modern_scholarship=data.get("modern_scholarship", ""),
            scholar=data.get("scholar", ""),
            scholar_work=data.get("scholar_work", ""),
            engine_logic=data.get("engine_logic", ""),
            related_topics=data.get("related_topics", []),
        )


# ─── Pre-built knowledge cards ─────────────────────────────────

BUILTIN_CARDS: dict[str, KnowledgeCard] = {
    "屯田制": KnowledgeCard(
        topic="屯田制",
        historical_source="《三国志·魏书·武帝纪》",
        source_quote="是岁，乃兴屯田，以任峻为典农中郎将，募百姓屯田于许下，得谷百万斛。于是州郡例置田官，所在积谷。",
        modern_scholarship="田余庆认为曹操屯田制的核心不是经济效率，而是将流民与土地重新绑定——本质上是人口控制制度，这解释了为何屯田制下的农民地位低于自耕农。",
        scholar="田余庆",
        scholar_work="《秦汉魏晋史探微》",
        engine_logic="屯田制效果: 粮食产出+30%, 民心+5。因为流民获得土地和种子，军队自给自足减轻百姓负担。",
        related_topics=["均田制", "府兵制", "曹操经济政策"],
    ),
    "九品中正制": KnowledgeCard(
        topic="九品中正制",
        historical_source="《三国志·魏书·陈群传》",
        source_quote="文帝在东宫，深敬器焉……及即王位，封群昌武亭侯，徙为尚书。制九品官人之法，群所建也。",
        modern_scholarship="唐长孺指出九品中正制最初是为了在汉末乱世中恢复人才选拔秩序，但逐渐被门阀士族把持，成为魏晋南北朝门阀政治的制度基础。",
        scholar="唐长孺",
        scholar_work="《魏晋南北朝史论丛》",
        engine_logic="九品中正制: 行政效率+10%, 民心-3(寒门上升通道收窄), 士族忠诚度+10",
        related_topics=["察举制", "科举制", "门阀政治"],
    ),
    "赤壁之战": KnowledgeCard(
        topic="赤壁之战",
        historical_source="《三国志·吴书·周瑜传》",
        source_quote="瑜部将黄盖曰：'今寇众我寡，难与持久。然观操军方连船舰，首尾相接，可烧而走也。'",
        modern_scholarship="张作耀认为赤壁之战曹操失败的根本原因不是火攻，而是北方士兵不习水战、军中瘟疫流行、以及战略上的轻敌冒进。火攻只是压垮骆驼的最后一根稻草。",
        scholar="张作耀",
        scholar_work="《曹操传》",
        engine_logic="赤壁触发条件: 曹操占襄阳 + 孙刘各自存活 + 208年冬季。结果由 LLM 根据兵力对比和随机因素推演。",
        related_topics=["官渡之战", "夷陵之战", "孙权战略", "周瑜"],
    ),
    "三顾茅庐": KnowledgeCard(
        topic="三顾茅庐",
        historical_source="《三国志·蜀书·诸葛亮传》",
        source_quote="先帝不以臣卑鄙，猥自枉屈，三顾臣于草庐之中，咨臣以当世之事，由是感激，遂许先帝以驱驰。",
        modern_scholarship="易中天认为三顾茅庐不仅是刘备求贤，更是诸葛亮精心设计的'面试'——他在等待一个能让他实现政治理想的君主，而刘备的诚意和志向打动了他。",
        scholar="易中天",
        scholar_work="《品三国》",
        engine_logic="触发条件: 刘备存活 + 诸葛亮未出仕 + 207年。效果: 诸葛亮加入刘备势力，忠诚度95。",
        related_topics=["隆中对", "诸葛亮北伐", "刘备战略"],
    ),
}


class KnowledgeBase:
    """In-memory knowledge card repository."""

    def __init__(self, cards: dict[str, KnowledgeCard] | None = None):
        self._cards: dict[str, KnowledgeCard] = dict(BUILTIN_CARDS)
        if cards:
            self._cards.update(cards)

    def get(self, topic: str) -> KnowledgeCard | None:
        return self._cards.get(topic)

    def get_all(self) -> list[KnowledgeCard]:
        return list(self._cards.values())

    def add(self, card: KnowledgeCard) -> None:
        self._cards[card.topic] = card

    def search(self, query: str) -> list[KnowledgeCard]:
        q = query.lower()
        results = []
        for card in self._cards.values():
            if (q in card.topic.lower() or
                q in card.historical_source.lower() or
                q in card.modern_scholarship.lower() or
                any(q in t.lower() for t in card.related_topics)):
                results.append(card)
        return results

    def get_cards_for_events(self, events: list[dict]) -> list[KnowledgeCard]:
        """Extract knowledge cards from LLM-generated events."""
        cards = []
        for evt in events:
            if isinstance(evt, dict) and "topic" in evt:
                try:
                    card = KnowledgeCard.from_dict(evt)
                    cards.append(card)
                except Exception:
                    pass
        return cards
