#!/usr/bin/env python3
"""Quick histrategy LLM benchmark — compare Gemini 2.5 Flash vs DeepSeek."""
import urllib.request, json, time, os

gemini_key = os.environ["GEMINI_API_KEY"]
ds_key = os.environ["DEEPSEEK_API_KEY"]

tests = [
    ("intent_parse", "你是军令官。解析玩家文本为JSON命令。\n玩家势力: qing\n指令: 多铎率两万八旗精锐南下攻打扬州；派三千火铳手支援开封；在直隶减税安抚汉民；与郑氏结盟\n输出JSON: {\"commands\": [{\"type\": \"...\", \"params\": {...}}]}", 1024),
    ("macro_sim", "你是战争模拟器。大清30K骑兵(士气85)攻南明15K守军(士气47)守扬州。平原骑兵1.3x，长江防线1.5x。输出JSON: {\"result\":\"攻陷/守住/围困\",\"attacker_losses\":N,\"defender_losses\":N,\"narrative\":\"战报\"}", 512),
    ("narrative", "你是历史叙事官。1645春大清攻陷开封，南明联寇抗清，郑氏退守福建。生成300字中文战报(大事纪/兵争武事/各方动向三段)。", 2048),
]

results = []
for provider, model, base, key, use_native in [
    ("DeepSeek", "deepseek-v4-flash", "https://api.deepseek.com/v1", ds_key, False),
    ("DeepSeek", "deepseek-v4-pro", "https://api.deepseek.com/v1", ds_key, False),
    ("Gemini", "gemini-2.5-flash", "", gemini_key, True),
]:
    for tname, prompt, maxtok in tests:
        t0 = time.time()
        try:
            if use_native:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                body = json.dumps({
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": maxtok, "temperature": 0.1}
                }).encode()
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read())
                lat = (time.time() - t0) * 1000
                u = d.get("usageMetadata", {})
                pt = u.get("promptTokenCount", 0)
                ct = u.get("candidatesTokenCount", 0)
                tt = u.get("thoughtsTokenCount", 0)
                content = d["candidates"][0]["content"]["parts"][0]["text"]
            else:
                body = json.dumps({
                    "model": model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": maxtok, "temperature": 0.1,
                }).encode()
                req = urllib.request.Request(
                    f"{base}/chat/completions", data=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read())
                lat = (time.time() - t0) * 1000
                u = d.get("usage", {})
                pt = u.get("prompt_tokens", 0)
                ct = u.get("completion_tokens", 0)
                tt = 0
                content = d["choices"][0]["message"].get("content", "") or ""

            valid = "?"
            if tname in ("intent_parse", "macro_sim"):
                try:
                    raw = content
                    if "```" in raw:
                        raw = raw.split("```")[1].split("```")[0].replace("json", "")
                    j = json.loads(raw.strip())
                    if "commands" in j:
                        valid = f"{len(j['commands'])}cmds"
                    elif "result" in j:
                        valid = j["result"]
                    else:
                        valid = "OK_JSON"
                except Exception:
                    valid = "BAD_JSON"
            else:
                valid = f"{len(content)}chars"
            results.append({
                "provider": provider, "model": model, "task": tname,
                "latency": lat, "prompt_tokens": pt, "completion_tokens": ct,
                "think_tokens": tt, "valid": valid,
                "preview": content[:80].replace("\n", " "),
            })
        except Exception as e:
            results.append({
                "provider": provider, "model": model, "task": tname,
                "latency": (time.time() - t0) * 1000, "error": str(e)[:60],
            })
        time.sleep(0.5)

print(json.dumps(results, indent=2, ensure_ascii=False))
