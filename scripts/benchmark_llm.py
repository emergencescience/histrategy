#!/usr/bin/env python3
"""Histrategy LLM Benchmark — compare models for strategy game simulation tasks.

Compares: Gemini 2.5 Flash, DeepSeek V4 Flash, DeepSeek V4 Pro
Tasks: intent parsing, Chinese narrative generation, macro simulation
Metrics: accuracy (valid JSON rate, correct IDs), speed (latency), cost (tokens)
"""

import json, os, sys, time
from dataclasses import dataclass, field
from typing import Any

# ── Model configs ──
MODELS = [
    {
        "name": "deepseek-v4-flash",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    {
        "name": "deepseek-v4-pro",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    },
    {
        "name": "gemini-2.5-flash",
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
    },
]

# ── Test inputs ──

INTENT_PARSE_TESTS = [
    {
        "name": "multi-step attack",
        "prompt": """你是军令官。解析以下指令为结构化JSON命令。

玩家势力: qing

指令: 多铎率两万八旗精锐南下攻打扬州，阿济格领偏师西进取襄阳；命吴三桂的关宁铁骑为先锋直扑南京；同时命山东驻军征粮备草支援前线

输出: {"commands": [{"type": "...", "params": {...}}]}""",
        "expected_types": ["attack", "attack", "move"],
        "expected_territories": ["yangzhou", "xiangyang", "nanjing"],
    },
    {
        "name": "recruit + develop + diplomacy",
        "prompt": """你是军令官。解析以下指令为结构化JSON命令。

玩家势力: qing

指令: 招募两万八旗步兵在北京训练；派三千火铳手支援开封前线；在直隶减税安抚汉民；与郑氏结盟共同抗清

输出: {"commands": [{"type": "...", "params": {...}}]}""",
        "expected_types": ["recruit", "move", "tax"],
        "expected_territories": ["beijing", "kaifeng"],
    },
    {
        "name": "internal development",
        "prompt": """你是军令官。解析以下指令为结构化JSON命令。

玩家势力: cao

指令: 在许昌大兴土木修建丞相府巩固权力；荀攸献策推行九品中正制选拔官员；减轻屯田农户赋税三成以收民心；命于禁在黄河沿岸修筑水寨防范河北

输出: {"commands": [{"type": "...", "params": {...}}]}""",
        "expected_types": ["develop", "tax"],
        "expected_territories": ["xuchang"],
    },
]

NARRATIVE_TESTS = [
    {
        "name": "battle report",
        "prompt": """你是历史叙事官。根据以下战况生成300字左右的中文战报。

年代: 1645年春
势力: 大清(清军)
当前状态: 兵力112,000，粮草28,000，民心77，领地：北京、盛京、山西、陕西、甘肃、开封
玩家决策: 多铎出潼关取河南，阿济格出居庸关经山西取陕西
本回合事件: 大清攻陷开封，农民军围困陕西
NPC动向: 南明遣使联络农民军，郑氏退守福建

要求: 使用文言白话混合风格，包含大事纪、兵争武事、各方动向三个段落。""",
    },
    {
        "name": "advisor speech",
        "prompt": """你是军师。根据以下局势为玩家提供上中下三策。

年代: 1645年夏
势力: 大清
局势: 兵力140,000，粮草21,800，民心95，领地7城。南明兵力98,000占据江南，农民军86,000在四川湖北，郑氏水师在福建。
上一回合: 大清攻陷开封和洛阳。
当前威胁: 粮草消耗过快，南明正在联合农民军和郑氏。

请以多尔衮的军师范文程口吻，提供上中下三策，每策100-150字，包含军事、外交、内政、生产四个方面。""",
    },
]

MACRO_SIM_TESTS = [
    {
        "name": "combat resolution",
        "prompt": """你是战争模拟器。根据以下攻防数据结算战斗结果。

攻击方: 大清，兵力30,000（八旗骑兵），士气85，从开封出发
防守方: 南明，兵力15,000（步兵+水军），士气47，防守扬州
地形: 平原（骑兵优势1.3x）
季节: 春季（粮草消耗正常）
其他: 南明有长江防线（防守方1.5x城市防御加成）

请输出JSON:
{"result": "攻陷/守住/围困", "attacker_losses": N, "defender_losses": N, "narrative": "简短战报"}""",
    },
]


@dataclass
class BenchResult:
    model: str
    task: str
    test_name: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    valid_json: bool = True
    error: str = ""
    extras: dict = field(default_factory=dict)


def call_llm(cfg: dict, messages: list[dict], max_tokens: int = 1024) -> dict:
    """Call LLM API, return {content, prompt_tokens, completion_tokens, latency_ms}."""
    import urllib.request, urllib.error

    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{cfg['api_base']}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"content": "", "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": (time.time()-t0)*1000, "error": str(e)}

    latency = (time.time() - t0) * 1000
    choice = data.get("choices", [{}])[0]
    usage = data.get("usage", {})

    return {
        "content": choice.get("message", {}).get("content", ""),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "latency_ms": latency,
        "error": "",
    }


def run_benchmark() -> list[BenchResult]:
    results: list[BenchResult] = []

    for cfg in MODELS:
        if not cfg["api_key"]:
            print(f"⚠️  Skipping {cfg['name']}: no API key")
            continue

        print(f"\n{'='*60}")
        print(f"🔬 Testing {cfg['name']} ({cfg['model']})")
        print(f"{'='*60}")

        # ── Intent Parse tests ──
        for test in INTENT_PARSE_TESTS:
            print(f"  📝 Intent: {test['name']}...", end=" ", flush=True)
            resp = call_llm(cfg, [{"role": "user", "content": test["prompt"]}], max_tokens=1024)

            r = BenchResult(
                model=cfg["name"],
                task="intent_parse",
                test_name=test["name"],
                latency_ms=resp["latency_ms"],
                prompt_tokens=resp["prompt_tokens"],
                completion_tokens=resp["completion_tokens"],
                error=resp["error"],
            )

            if resp["error"]:
                r.valid_json = False
                print(f"❌ {resp['error'][:60]}")
            else:
                # Validate JSON
                try:
                    content = resp["content"].strip()
                    # Extract JSON
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0]
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0]
                    parsed = json.loads(content)
                    cmds = parsed.get("commands", [])
                    types = [c.get("type", "") for c in cmds]
                    r.extras["command_count"] = len(cmds)
                    r.extras["command_types"] = types

                    # Check expected types
                    matched = sum(1 for et in test.get("expected_types", []) if et in types)
                    r.extras["type_match"] = f"{matched}/{len(test.get('expected_types',[]))}"

                    # Check expected territories
                    all_params = " ".join(json.dumps(c.get("params", {})) for c in cmds)
                    terr_match = sum(1 for et in test.get("expected_territories", []) if et in all_params)
                    r.extras["territory_match"] = f"{terr_match}/{len(test.get('expected_territories',[]))}"

                    status = "✅" if cmds else "⚠️ empty"
                    print(f"{status} {len(cmds)}cmds {r.latency_ms:.0f}ms {r.prompt_tokens}+{r.completion_tokens}tk")
                except (json.JSONDecodeError, KeyError) as e:
                    r.valid_json = False
                    r.error = str(e)[:80]
                    print(f"❌ JSON: {str(e)[:50]}")

            results.append(r)
            time.sleep(0.3)  # Rate limit safety

        # ── Narrative tests ──
        for test in NARRATIVE_TESTS:
            print(f"  📖 Narrative: {test['name']}...", end=" ", flush=True)
            resp = call_llm(cfg, [{"role": "user", "content": test["prompt"]}], max_tokens=2048)

            r = BenchResult(
                model=cfg["name"],
                task="narrative",
                test_name=test["name"],
                latency_ms=resp["latency_ms"],
                prompt_tokens=resp["prompt_tokens"],
                completion_tokens=resp["completion_tokens"],
                error=resp["error"],
            )

            if resp["error"]:
                print(f"❌ {resp['error'][:60]}")
            else:
                content = resp["content"]
                chars = len(content)
                r.extras["char_count"] = chars
                r.extras["preview"] = content[:80].replace("\n", " ")
                print(f"✅ {chars}chars {r.latency_ms:.0f}ms {r.prompt_tokens}+{r.completion_tokens}tk")

            results.append(r)
            time.sleep(0.5)

        # ── Macro Sim tests ──
        for test in MACRO_SIM_TESTS:
            print(f"  ⚔️  Macro: {test['name']}...", end=" ", flush=True)
            resp = call_llm(cfg, [{"role": "user", "content": test["prompt"]}], max_tokens=512)

            r = BenchResult(
                model=cfg["name"],
                task="macro_sim",
                test_name=test["name"],
                latency_ms=resp["latency_ms"],
                prompt_tokens=resp["prompt_tokens"],
                completion_tokens=resp["completion_tokens"],
                error=resp["error"],
            )

            if resp["error"]:
                print(f"❌ {resp['error'][:60]}")
            else:
                try:
                    content = resp["content"].strip()
                    if "```" in content:
                        content = content.split("```")[1].split("```")[0].replace("json", "")
                    parsed = json.loads(content)
                    r.extras["result"] = parsed.get("result", "?")
                    r.extras["attacker_losses"] = parsed.get("attacker_losses", "?")
                    r.extras["defender_losses"] = parsed.get("defender_losses", "?")
                    print(f"✅ {parsed.get('result','?')} {r.latency_ms:.0f}ms")
                except json.JSONDecodeError:
                    r.valid_json = False
                    print(f"⚠️  non-JSON {r.latency_ms:.0f}ms")

            results.append(r)
            time.sleep(0.3)

    return results


def print_report(results: list[BenchResult]):
    """Print comparison report."""
    from collections import defaultdict

    print("\n\n" + "=" * 80)
    print("📊 HISTRATEGY LLM BENCHMARK REPORT")
    print("=" * 80)

    # ── Per-model summary ──
    models = sorted(set(r.model for r in results))
    for model in models:
        mrs = [r for r in results if r.model == model]
        latencies = [r.latency_ms for r in mrs if r.latency_ms > 0]
        if not latencies:
            continue
        p_tokens = sum(r.prompt_tokens for r in mrs)
        c_tokens = sum(r.completion_tokens for r in mrs)
        errors = sum(1 for r in mrs if r.error)
        json_fails = sum(1 for r in mrs if not r.valid_json)

        print(f"\n## {model}")
        print(f"  Tests: {len(mrs)} | Errors: {errors} | JSON fails: {json_fails}")
        print(f"  Latency: avg={sum(latencies)/len(latencies):.0f}ms min={min(latencies):.0f}ms max={max(latencies):.0f}ms")
        print(f"  Tokens: {p_tokens:,} prompt + {c_tokens:,} completion = {p_tokens+c_tokens:,} total")

    # ── Task breakdown ──
    print(f"\n{'─'*80}")
    print("TASK BREAKDOWN")
    for task in ["intent_parse", "narrative", "macro_sim"]:
        print(f"\n### {task}")
        trs = [r for r in results if r.task == task]
        for model in models:
            mrs = [r for r in trs if r.model == model]
            if not mrs:
                continue
            avg_lat = sum(r.latency_ms for r in mrs if r.latency_ms > 0) / max(len([r for r in mrs if r.latency_ms > 0]), 1)
            errors = sum(1 for r in mrs if r.error)
            print(f"  {model}: {avg_lat:.0f}ms avg | {errors} errors | extras: {[r.extras for r in mrs]}")

    # ── Cost estimate ──
    print(f"\n{'─'*80}")
    print("COST ESTIMATE (per 1M tokens, approximate)")
    pricing = {
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
        "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    }
    for model in models:
        mrs = [r for r in results if r.model == model]
        p = sum(r.prompt_tokens for r in mrs)
        c = sum(r.completion_tokens for r in mrs)
        price = pricing.get(model, {"input": 0, "output": 0})
        cost = (p / 1_000_000) * price["input"] + (c / 1_000_000) * price["output"]
        print(f"  {model}: ${cost:.4f} for this benchmark ({p:,}+{c:,} tokens)")

    # ── Raw data ──
    print(f"\n{'─'*80}")
    print("RAW RESULTS (JSON)")
    raw = []
    for r in results:
        raw.append({
            "model": r.model,
            "task": r.task,
            "test": r.test_name,
            "latency_ms": r.latency_ms,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "valid_json": r.valid_json,
            "error": r.error,
            "extras": r.extras,
        })
    print(json.dumps(raw, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    results = run_benchmark()
    print_report(results)
