import pytest
from unittest.mock import MagicMock
from histrategy.llm.endgame_summary import generate_chronicle

def test_generate_chronicle_empty():
    res = generate_chronicle([])
    assert "默默无闻" in res

def test_generate_chronicle_offline_fallback():
    events = [
        {"title": "三顾茅庐", "description": "刘备三访诸葛亮并获得其效忠。"},
        {"title": "赤壁之战", "description": "大破曹操大军。"},
    ]
    res = generate_chronicle(events)
    assert "后汉三国志·列传" in res
    assert "三顾茅庐" in res
    assert "赤壁之战" in res
    assert "史官曰" in res
    assert "评曰" in res

def test_generate_chronicle_llm():
    events = ["起兵讨董", "收复徐州"]
    llm_mock = MagicMock()
    llm_mock.is_available = True
    llm_mock.chat.return_value = "史官曰：备起兵徐州，折而不挠，终成大业。"

    res = generate_chronicle(events, llm_adapter=llm_mock)
    assert res == "史官曰：备起兵徐州，折而不挠，终成大业。"
    llm_mock.chat.assert_called_once()
