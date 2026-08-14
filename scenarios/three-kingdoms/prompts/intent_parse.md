# 三国场景领土与势力参考

## ⚠️ 领土参考 — 仅作初始参考，实际以系统注入的「全势力领土分布」为准

## ⚠️ 输出硬限制

- **总输出不得超过 2000 字符。超过则视为失败。**
- 精炼回答，不要写长篇大论。
- **仅输出 JSON，不要输出任何其他文本。**


（三国初始领土 — 仅供参考。游戏进行中领土会变化，以系统注入的实时数据为准。）
曹操初始领地: xuchang(许昌), luoyang(洛阳), ye(邺城), wancheng(宛城), changshan(常山), ji(蓟县), puyang(濮阳), beihai(北海), xiapi(下邳)
刘备初始领地: xinye(新野)
孙权初始领地: jianye(建业), wu(吴郡), kuaiji(会稽), chaisang(柴桑), lujiang(庐江)
刘表初始领地: xiangyang(襄阳), jiangling(江陵), changsha(长沙), jiangkou(江口)
刘璋初始领地: chengdu(成都)

## 三国场景解析示例

### 示例1：复杂战役
玩家指令：
```
【南征刘备】— 集结宛城5万步兵和1万骑兵，春季行军（粮草消耗正常），
进攻刘备仅5000兵的新野。预计一周内攻克，俘获刘备及其将领（关羽、张飞等）。
风险：孙权可能从庐江进攻下邳，需在下邳部署3万兵力防守；
刘表势力（襄阳）可能背刺宛城，需留警戒兵力。
```

解析输出：
```json
{
  "commands": [
    {
      "type": "attack",
      "params": {
        "target_territory": "xinye",
        "source_territory": "wancheng",
        "amount": 60000,
        "unit_type": "infantry, cavalry"
      },
      "notes": "【南征刘备战役】主力行动：从宛城集结6万大军（5万步兵+1万骑兵），春季行军进攻刘备仅5000兵的新野。预期一周攻克，目标俘获刘备、关羽、张飞。粮草消耗正常。"
    },
    {
      "type": "defend",
      "params": {
        "territory": "xiapi",
        "amount": 30000
      },
      "notes": "【南征刘备战役】东线防御：在下邳部署3万兵力，防范孙权从庐江方向进攻。"
    },
    {
      "type": "defend",
      "params": {
        "territory": "wancheng"
      },
      "notes": "【南征刘备战役】后方警戒：刘表从襄阳可能偷袭宛城，留警戒兵力。"
    }
  ]
}
```

### 示例2：招募+训练
玩家指令：「在许昌招募1万骑兵并加以训练」

解析输出：
```json
{
  "commands": [
    {
      "type": "recruit",
      "params": {"territory": "xuchang", "unit_type": "cavalry", "amount": 10000},
      "notes": "扩充骑兵力量，增强机动打击能力"
    },
    {
      "type": "train",
      "params": {"territory": "xuchang"},
      "notes": "对新募骑兵进行训练，提升战斗力"
    }
  ]
}
```

### 示例3：单纯防守
玩家指令：「在下邳部署重兵防守，防止孙权偷袭」

解析输出：
```json
{
  "commands": [
    {
      "type": "defend",
      "params": {"territory": "xiapi"},
      "notes": "东线防御重心：下邳为对吴前线，需重兵布防。威胁来源：孙权可能从庐江/建业方向进攻。"
    }
  ]
}
```

### 示例4：外交+进攻组合
玩家指令：「先派使者与孙权结盟，然后全力进攻新野的刘备」

解析输出：
```json
{
  "commands": [
    {
      "type": "negotiate",
      "params": {"target_faction": "wu", "proposal": "结盟", "action": "form_alliance"},
      "notes": "联吴抗蜀战略：先稳住东线，避免两线作战"
    },
    {
      "type": "attack",
      "params": {"target_territory": "xinye"},
      "notes": "主力南征：与孙权结盟后，集中兵力消灭刘备，夺取新野"
    }
  ]
}
```

### 示例5：流亡依附（seek_refuge）
玩家指令：「南撤襄阳依附刘表」（我方已无领地，是流亡军）

解析输出：
```json
{
  "commands": [
    {
      "type": "move",
      "params": {"destination": "xiangyang"},
      "notes": "流亡军南撤，开赴襄阳一带"
    },
    {
      "type": "negotiate",
      "params": {"target_faction": "liubiao", "proposal": "依附刘表，求割一城为基业", "action": "seek_refuge"},
      "notes": "依附/投靠刘表：请求割让一座非首都城作为新基地"
    }
  ]
}
```

⚠️ 「依附」「投靠」「投奔」「归附」「避难」「南撤投奔X」→ **negotiate** action=seek_refuge（请求割让一座非首都城作为流亡新基地）。
