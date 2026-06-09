# Histrategy Server — Railway 部署指南

## 新建 Service

1. 在 Railway 项目中新建 Service，连接 histrategy GitHub 仓库
2. Railway 会自动读取 railway.toml 使用 Nixpacks 构建

## 必填环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `JWT_SECRET` | 与 Orchestrator 共享，值完全相同 | 从 Orchestrator Service 复制 |
| `ORCHESTRATOR_URL` | Orchestrator 生产地址 | `https://api.emergence.science` |

## 可选环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HISTRATEGY_DATA_DIR` | `/tmp/histrategy` | 临时文件存储（Railway 无持久化磁盘） |
| `LLM_MODEL` | `deepseek-v4-pro` | 默认 LLM 模型 |
| `ALLOWED_ORIGINS` | （空）| 追加 CORS 白名单，逗号分隔 |

## Orchestrator 端需要配置的变量

| 变量 | 说明 |
|------|------|
| `HISTRATEGY_SERVER_URL` | Histrategy Server 的 Railway 内网地址（同项目 Service 间可用 `http://histrategy.railway.internal:8080`）|
