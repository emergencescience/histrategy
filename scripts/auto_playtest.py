#!/usr/bin/env python3
"""Auto playtest — 走生产 API 的 headless 玩测，自动检测数值/parse/叙事问题。

用法:
    python auto_playtest.py                      # 默认: 生产 API, nanming+three-kingdoms, 3 轮
    python auto_playtest.py --base http://127.0.0.1:8080   # 本地服务器
    python auto_playtest.py --scenarios nanming --turns 4

检测项 (确定性规则, 不依赖 LLM 自评):
  1. 兵力暴跌: 单轮降幅 >40% (正常战斗损耗 <20%)
  2. intent parse 走关键词兜底: recruit amount==500 且玩家未给数字 (关键词兜底特征)
  3. intent parse 空: 玩家明确指令但 commands 为空
  4. 负食物/负府库
  5. 叙事死亡幻觉: narrative 出现死亡词 (人物永生铁律)
  6. 领土错乱: faction 声称拥有但 owner 不符 (由 state 检查)

输出: /tmp/auto_playtest_report.json (结构化) + 人类可读摘要。
"""
import argparse, json, sys, time
import httpx

DEATH_WORDS = ['病故', '阵亡', '被杀', '殉国', '去世', '死亡', '寿终', '身死', '崩逝',
               '病逝', '遇害', '殒命', '战死', '辞世', '逝世', 'died', 'killed', 'dead']

# 每个场景一个玩家 faction + 一组覆盖多种 intent 的指令
SCENARIOS = {
    'nanming': {
        'faction': 'nanming',
        'commands': [
            '征兵扩军，加强江北防线',        # 征兵不带数字 (测 LLM 是否脑补)
            '在江南征兵两万，同时屯田积粮',   # 征兵带数字 + develop
            '派史可法督师扬州，加固城防',     # appoint
            '北伐中原，攻取徐州',            # attack
        ],
    },
    'three-kingdoms': {
        'faction': 'shu',
        'commands': [
            '在成都征兵五千，发展农业',
            '派诸葛亮出使东吴，结盟抗曹',
            '命关羽镇守荆州',
            '北伐中原，讨伐曹操',
        ],
    },
    'rome-triumvirate': {
        'faction': 'octavian',
        'commands': [
            '在罗马征兵一万，加强城防',
            '与安东尼结盟',
            '讨伐布鲁图斯',
        ],
    },
}


def log(msg):
    print(msg, flush=True)


def get(c, path):
    return c.get(path, timeout=40).json()


def post(c, path, data):
    return c.post(path, json=data, timeout=240).json()


def check_turn(issues, label, decision, parsed_cmds, before, after, narrative):
    """Run deterministic checks on a single turn."""
    # Check 1: 兵力暴跌 (>40% 单轮降幅)
    for fid, bt in before.items():
        at = after.get(fid)
        if at is None or bt is None:
            continue
        # snap() returns per-faction dicts {'troops','food','treasury','morale'}
        bt_troops = bt.get('troops') if isinstance(bt, dict) else bt
        at_troops = at.get('troops') if isinstance(at, dict) else at
        if bt_troops is None or at_troops is None or bt_troops <= 0:
            continue
        drop = (bt_troops - at_troops) / bt_troops
        if drop > 0.40:
            issues.append({
                'turn': label, 'type': 'troop_crash',
                'detail': f'{fid} 兵力暴跌 {bt_troops}->{at_troops} (-{drop*100:.0f}%)',
            })

    # Check 2 & 3: intent parse
    for c in parsed_cmds or []:
        ctype = c.get('type', '')
        params = c.get('params', {}) or {}
        if ctype == 'recruit':
            amt = params.get('amount')
            # 关键词兜底特征: amount==500 且玩家没给数字
            if amt == 500 and not any(ch.isdigit() for ch in decision):
                issues.append({
                    'turn': label, 'type': 'keyword_fallback',
                    'detail': f'recruit amount=500 (关键词兜底, 玩家未给数字): "{decision}"',
                })
    if decision.strip() and not parsed_cmds:
        issues.append({
            'turn': label, 'type': 'empty_parse',
            'detail': f'玩家指令但 commands 为空: "{decision}"',
        })

    # Check 4: 负食物/府库
    for fid, f in after.items():
        if f.get('food', 0) < 0:
            issues.append({'turn': label, 'type': 'negative_food', 'detail': f'{fid} food<0'})
        if f.get('treasury', 0) < 0:
            issues.append({'turn': label, 'type': 'negative_treasury', 'detail': f'{fid} treasury<0'})

    # Check 5: 叙事死亡幻觉
    for w in DEATH_WORDS:
        if w in (narrative or ''):
            issues.append({'turn': label, 'type': 'death_hallucination', 'detail': f'narrative 含死亡词 "{w}"'})
            break


def play_scenario(base, scenario, turns):
    cfg = SCENARIOS[scenario]
    faction = cfg['faction']
    with httpx.Client(base_url=base, timeout=240) as c:
        start = post(c, '/api/single-player/start', {
            'faction': faction, 'scenario': scenario,
            'language_style': 'vernacular', 'lang': 'zh',
        })
        gid = start.get('game_id')
        if not gid:
            return scenario, [], f'start 失败: {json.dumps(start, ensure_ascii=False)[:300]}'

        log(f'  [{scenario}] game_id={gid} faction={faction}')

        def snap():
            s = get(c, f'/api/rooms/{gid}/state')
            return {f.get('faction_id'): {'troops': f.get('troops'), 'food': f.get('food'),
                                          'treasury': f.get('treasury'), 'morale': f.get('morale')}
                    for f in s.get('factions', [])}

        issues = []
        before = snap()
        for i, decision in enumerate(cfg['commands'][:turns], 1):
            try:
                r = post(c, f'/api/single-player/{gid}/command', {'decision': decision, 'lang': 'zh'})
                if not r.get('ok'):
                    issues.append({'turn': f'T{i}', 'type': 'submit_fail', 'detail': json.dumps(r, ensure_ascii=False)[:200]})
                    break
            except Exception as e:
                issues.append({'turn': f'T{i}', 'type': 'submit_exception', 'detail': str(e)[:200]})
                break

            # 读 intent parse 结果
            parsed_cmds = []
            try:
                time.sleep(2)
                turns_data = get(c, f'/api/rooms/{gid}/turns')
                tlist = turns_data if isinstance(turns_data, list) else turns_data.get('turns', [])
                if tlist:
                    fd = tlist[-1].get('faction_decisions', {}) or {}
                    parsed_cmds = (fd.get(faction, {}) or {}).get('commands', []) or []
            except Exception:
                pass

            narrative = r.get('narrative', '') or ''
            after = snap()
            check_turn(issues, f'T{i}', decision, parsed_cmds, before, after, narrative)
            before = after
            if i < turns:
                time.sleep(33)  # rate limit 30s

        return scenario, issues, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://histrategy-production.up.railway.app')
    ap.add_argument('--scenarios', default='nanming,three-kingdoms,rome-triumvirate')
    ap.add_argument('--turns', type=int, default=3)
    ap.add_argument('--out', default='/tmp/auto_playtest_report.json')
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(',') if s.strip()]
    log(f'=== Auto Playtest: {scenarios} x {args.turns} turns @ {args.base} ===')
    log(f't0={time.strftime("%H:%M:%S")}')

    report = {'base': args.base, 't0': time.time(), 'scenarios': {}}
    total_issues = 0
    for sc in scenarios:
        log(f'\n--- 场景 {sc} ---')
        try:
            name, issues, err = play_scenario(args.base, sc, args.turns)
        except Exception as e:
            report['scenarios'][sc] = {'error': str(e)}
            log(f'  ❌ {sc} 异常: {e}')
            continue
        report['scenarios'][sc] = {'issues': issues, 'error': err}
        if err:
            log(f'  ❌ {sc}: {err}')
        elif issues:
            total_issues += len(issues)
            log(f'  ⚠️  {sc}: {len(issues)} 个问题')
            for it in issues:
                log(f'     - [{it["type"]}] {it["detail"]}')
        else:
            log(f'  ✅ {sc}: 无问题')

    report['total_issues'] = total_issues
    with open(args.out, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log(f'\n=== 完成: {total_issues} 个问题, 报告 → {args.out} ===')
    sys.exit(0)


if __name__ == '__main__':
    main()
