#!/usr/bin/env python3
"""Add neighbor relationships to mass-warlords territories.json based on geographic proximity."""

import json
from pathlib import Path

TERRITORIES_PATH = Path(__file__).parent.parent / "scenarios/mass-warlords/knowledge/territories.json"

# Neighbor relationships based on historical geography
NEIGHBORS: dict[str, list[str]] = {
    "xuchang": ["luoyang", "ye", "wan", "xiangyang", "jibei", "shouchun"],
    "luoyang": ["xuchang", "ye", "hongnong", "hejin"],
    "ye": ["xuchang", "luoyang", "hejin", "beihai", "jibei", "liaodong"],
    "jianye": ["wu", "shouchun", "mo", "jiangxia"],
    "xiangyang": ["xuchang", "wan", "jiangling", "xinye", "nanjun", "jiangxia"],
    "jiangling": ["xiangyang", "nanjun", "changsha", "wuling", "lingling"],
    "xinye": ["xiangyang", "wan"],
    "chengdu": ["jiangzhou", "hanzhong", "yunnan"],
    "tianshui": ["jincheng", "hanzhong", "hongnong", "mei"],
    "hanzhong": ["tianshui", "jincheng", "chengdu", "jiangzhou"],
    "liaodong": ["ye", "daibei", "shanggu", "beihai"],
    "jincheng": ["tianshui", "hanzhong", "daibei"],
    "wan": ["xuchang", "xiangyang", "xinye", "hejin"],
    "lingling": ["jiangling", "guiyang", "wuling"],
    "guiyang": ["lingling", "wuling", "changsha", "jiaozhi"],
    "wuling": ["jiangling", "lingling", "guiyang", "changsha"],
    "changsha": ["jiangling", "wuling", "guiyang", "jiangxia"],
    "beihai": ["jibei", "ye", "xiapi", "liaodong"],
    "hejin": ["luoyang", "ye", "wan", "yan_city"],
    "jibei": ["xuchang", "ye", "beihai", "xiapi", "yan_city"],
    "jiangxia": ["xiangyang", "jianye", "changsha", "wu", "shouchun"],
    "jiaozhi": ["guiyang", "yunnan"],
    "yunnan": ["jiaozhi", "chengdu"],
    "daibei": ["shanggu", "jincheng", "tianshui", "liaodong"],
    "shanggu": ["daibei", "liaodong", "ye"],
    "mo": ["jianye", "wu"],
    "wu": ["jianye", "mo", "jiangxia"],
    "xiapi": ["beihai", "jibei", "shouchun", "xuzhou_city"],
    "hongnong": ["luoyang", "tianshui", "mei", "hejin"],
    "mei": ["hongnong", "tianshui", "chengdu"],
    "xuzhou_city": ["xiapi", "shouchun", "jibei"],
    "shouchun": ["xuchang", "jianye", "jiangxia", "xiapi", "xuzhou_city"],
    "yan_city": ["hejin", "jibei", "xuchang"],
    "jiangzhou": ["chengdu", "hanzhong", "nanjun"],
    "nanjun": ["xiangyang", "jiangling", "jiangzhou", "changsha"],
}


def add_neighbors():
    with open(TERRITORIES_PATH, encoding="utf-8") as f:
        territories = json.load(f)
    
    for t in territories:
        tid = t["id"]
        if tid in NEIGHBORS:
            t["neighbors"] = NEIGHBORS[tid]
        else:
            t["neighbors"] = []
    
    with open(TERRITORIES_PATH, "w", encoding="utf-8") as f:
        json.dump(territories, f, ensure_ascii=False, indent=2)
    
    print(f"Updated {len(territories)} territories with neighbor data")


if __name__ == "__main__":
    add_neighbors()
