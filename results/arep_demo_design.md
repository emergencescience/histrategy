# Agent Resource Exchange Protocol (AREP) — Demo Design
# 正和博弈 + 自愿合约 + 价值创造

## 模型

3类Agent，每类3个实例（共9个），各自拥有不同的资源禀赋：

| Agent | 资源禀赋 | 单干产出 | 协作需求 |
|-------|---------|---------|---------|
| DataAgent-1/2/3 | 数据 (100/200/50条) | 数据清洗 (5/10/3 价值) | 需要算力跑分析 |
| ComputeAgent-1/2/3 | 算力 (10/5/20 TFLOPS) | 挖矿 (8/4/16 价值) | 需要数据来训练 |
| ModelAgent-1/2/3 | 算法 (GPT/RL/规则) | 空转推理 (3/2/1 价值) | 需要数据+算力 |

### 单干模式（无合约）
每个Agent用自己资源独立工作：
- DataAgent: 清洗数据 → 产出 5-10 价值
- ComputeAgent: 挖矿 → 产出 4-16 价值  
- ModelAgent: 空转 → 产出 1-3 价值
- **总产出: ~50 价值/轮**

### 合约模式
Agent两两签约形成pipeline：
- ModelAgent + DataAgent + ComputeAgent → 数据→训练→模型→推理→产出 80-150 价值
- 合约规定分成比例（如 3:3:4）
- **总产出: ~300 价值/轮 (6x提升)**

## 合约生命周期
1. **Discovery**: Agent扫描市场，发现互补资源
2. **Proposal**: 发出合约提案（资源类型、数量、分成比例）
3. **Accept/Reject**: 对方评估，接受最优报价
4. **Execution**: 履约 → 产出
5. **Settlement**: 按合约分成，记录信誉
6. **Reputation**: 履约+1，违约-10

## 演示效果
- 回合1-3: 混乱期，Agent各自单干 + 试探性签约
- 回合4-8: 合约网络形成，固定合作伙伴出现
- 回合9+: 稳态，高效率pipeline形成，总产出收敛到最优

## 可视化
终端Rich表格：
```
Round 5 | Contracts: 4 active | Total Output: 247 (↑394%)
────────┼──────────┼──────────┼──────────┼──────────
Agent   │ Partner  │ Role     │ Output   │ Rep
Model-1 │ Data-2   │ Trainer  │    85    │ +3
        │ Comp-3   │          │          │
Data-2  │ Model-1  │ Provider │    60    │ +2
Comp-3  │ Model-1  │ Provider │    72    │ +3
Data-1  │ —        │ Solo     │     5    │  0
...
```

## 对比：命令式 vs 自由市场
同时跑两个模式：
- **Command**: 中央分配配对 → 次优匹配，无激励
- **Free Market**: Agent自主签约 → 最优匹配，信誉激励
- **收敛速度**: Free Market 更快找到最优pipeline
- **总产出**: Free Market 高 20-40%
