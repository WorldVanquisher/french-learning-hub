# French Learning Hub

[English](README.md)

一个本地优先的 Go、SQLite 与 React 服务，用于把法语学习中的问题保存为可追溯的记录。每条记录之后可以被解释、
由人工更正、拆分为可复习的知识单元，并整理为长期稳定的 Concept；这些 Concept 可以被检索，并能追溯回原始问题。

## 要解决的问题

学习语言时提出的问题——在课堂上、日记里，或与 AI 助手的对话中——往往散落在一次次对话里。即使保存下来，
机器给出的解释也容易被误当成学习者自己的记录；后来的更正会悄悄覆盖先前的答案；而且没有人说得清哪条证据
支撑了哪个已学到的概念。

French Learning Hub 以学习者的原话为唯一事实来源，把关于它的一切——分析、人工更正、抽取的知识单元和
Concept 判断——作为独立的、版本化或只追加的记录保存。当前状态由这些历史推导得出，而不是覆盖历史。

## 工作流程

```text
学习者的问题（直接输入，或导入事先准备好的 capture 文档）
  -> Entry                    学习者的原始输入与上下文，永不改写
  -> Analysis（版本化）       默认本地规则分析器，可选 OpenAI
  -> Feedback（只追加）       接受 / 更正 / 拒绝；有效解释由此推导
  -> 知识抽取                 显式触发、依赖外部提供方；产生不可变的单元
  -> Concept Review          由人工把单元归入长期稳定的 Concept
  -> Knowledge Library       检索 Concept，并逐一追溯到来源
  -> 数据集与检索报告         只读的研究工具
```

整个系统贯穿两个区分：

- **证据与身份。** 抽取得到的单元是某次抽取的不可变证据；Concept 是长期的学习身份。重新抽取一条记录会产生
  新单元，而不会改写旧单元。
- **成员关系与支撑。** 一个单元可以*归入*某个 Concept（当前 SAME 成员关系）却不*支撑*它：支撑还要求该单元
  来自其记录的当前抽取版本，且未被学习者隐藏。支撑在读取时推导，从不存储。

完整说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（英文）。

## 当前功能

- 保存学习 **Entry**，并追加版本化的 **Analysis**：默认使用本地确定性规则分析器（无需 API key），也可选用
  OpenAI 分析器。
- 记录不可变的人工 **Feedback**，读取推导出的有效解释，以及支持 JSONL 导出的跨条目**学习清单**。
- 通过 API、工作台或 `cmd/capture` 命令行幂等导入事先准备好的 `learning_capture_v1` 文档。导入从不调用模型。
- 显式运行**知识抽取**（OpenAI 适配器，默认关闭），配合固定的准入规则集和只追加的人工覆盖。
- 在 **Concept Review** 工作台中审核单元：SAME、NEW CONCEPT、BROADER、NARROWER、RELATED、DISTINCT 与
  INVALID 判断，保留只追加的历史和显式更正；DISTINCT 与关系类请求在响应丢失时可幂等恢复。
- 在只读的 **Knowledge Library** 中检索和浏览已整理的 Concept：以平实的英文显示状态，并能从每个单元链接到
  它所来自的记录及当时使用的确切解释。
- 查看有效标注，导出版本化的 Concept Annotation Dataset v1，检查其质量报告，并在同一评估样本上比较
  精确匹配、加权词法、BM25 以及可选嵌入检索基线。
- 将服务端与构建好的工作台打包成一个 Docker 镜像，带健康与就绪检查，并提供有文档的备份、恢复和升级流程。

## 它不是什么

这是一个单用户的学习数据服务和研究工具，不是聊天机器人、面向消费者的课程、间隔重复调度器或掌握度追踪器，
也不是自动的机器学习消解器。系统没有身份认证：只在 localhost 或可信网络中运行。知识抽取与语义检索需要你自行
配置外部提供方；没有基于规则的抽取器，也不会静默回退。Library 检索是关键词前缀匹配，而不是语义检索。
参见[有意不实现的内容](docs/ARCHITECTURE.md#12-deliberately-not-built)。

## 环境要求

- Go 1.26.5（以 `go.mod` 为准）。SQLite 通过纯 Go 驱动 `modernc.org/sqlite` 内嵌，不需要 SQLite 服务器或
  CGO 工具链。
- `web/` 工作台需要 Node.js 与 npm。项目未声明最低版本；CI 使用 Node 22。
- HTTP 示例需要 `curl`，合成演示需要 Python 3。
- 仅在打包发布时需要带 Compose 插件的 Docker。

## 快速开始

```bash
cd web && npm ci && cd ..   # 首次安装锁定版本的前端依赖
make verify                 # 格式、Go 测试与 vet、构建、前端检查
make run                    # API 位于 http://localhost:8080，数据库为 data/app.db
```

在另一个终端中：

```bash
curl -sS http://localhost:8080/healthz
curl -sS -X POST http://localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Pourquoi dit-on je vais ?","original_context":"Étude du verbe aller."}'
curl -sS -X POST http://localhost:8080/entries/1/analysis
make capture ARGS="-file examples/captures/manual-example.json"
```

用 `cd web && npm run dev` 启动工作台，然后打开 `http://localhost:5173`。
[docs/QUICKSTART.md](docs/QUICKSTART.md)（英文）完整介绍首次运行，包括可选提供方，以及为什么全新数据库上的
研究报告为空。

## 两分钟合成演示

Knowledge Library 演示会构建服务端，用一个全新的隔离数据库在回环地址上启动，并通过公开 API 写入四条合成学习
记录和七个 Concept。它使用本地分析器和本地桩抽取器：不涉及 API key、付费提供方或个人数据库。

```bash
npm --prefix web ci && npm --prefix web run build
WORK=$(mktemp -d)/flh034-demo
sh scripts/demo/flh034/demo.sh setup "$WORK" "$PWD/web/dist"
# 打开 http://127.0.0.1:18934/，并按 docs/DEMO.md 操作
sh scripts/demo/flh034/demo.sh cleanup "$WORK"
```

演示步骤、数据内容、重启行为以及支持的平台（Linux 与 macOS）见 [docs/DEMO.md](docs/DEMO.md)（英文）。
准备步骤不计入两分钟的演示时间。

## 个人使用发布

`Dockerfile` 与 `compose.yaml` 把 API 和构建好的工作台打包为一个镜像，仅发布在 `http://127.0.0.1:8080`，
SQLite 数据位于 `./data/release`：

```bash
mkdir -p data/release
docker compose up -d --build   # 等待 docker compose ps 显示 "(healthy)"
docker compose stop
```

现有的 `data/app.db` 不会被自动迁移。只在服务停止时备份，通过暂存目录恢复，并在每次升级前备份：迁移只能向前
执行，旧镜像不得运行在新版本数据库上。完整流程见 [docs/RELEASE.md](docs/RELEASE.md)（英文）。

## 配置默认值

服务读取进程环境变量，以及其工作目录中可选的、未纳入版本控制的 `.env` 文件；进程环境变量优先。默认配置不需要
任何凭据：

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `PORT` | `8080` | HTTP 端口 |
| `LISTEN_HOST` | 空（所有接口） | 可选的绑定 IP 字面量，例如 `127.0.0.1` |
| `DB_PATH` | `data/app.db` | SQLite 数据库文件 |
| `AI_PROVIDER` | `rule-based` | 分析器：`rule-based` 或 `openai` |
| `EXTRACTOR_PROVIDER` | `disabled` | 知识抽取器：`disabled` 或 `openai` |
| `EMBEDDING_PROVIDER` | `disabled` | 语义检索器：`disabled` 或 `http` |
| `HTTP_ALLOWED_HOSTS` | 仅回环名称 | 额外允许的精确 Host 名称或 IP |
| `HTTP_TRUSTED_ORIGINS` | 5173 端口的 Vite 开发源 | 允许发送写请求的浏览器源 |

提供方设置（`OPENAI_*`、`EMBEDDING_*`）与超时见 [`.env.example`](.env.example)，说明见
[ARCHITECTURE §10.2](docs/ARCHITECTURE.md#102-configuration)。无效配置会阻止启动，不会静默回退。
不要提交凭据。

## 项目状态

上文描述的服务、工作台与打包均已在本仓库中实现。[docs/validation/](docs/validation/) 中带日期的验证报告记录了
检查内容、执行者与局限——例如 Docker 发布验收、工作台的浏览器验收、标注写请求的响应丢失调查，以及
Knowledge Library 在 Linux 上的验收和在 macOS 真实浏览器中的演练。报告会区分作者自验与独立评审；通过的报告
并不代表适用于所有环境。按主题整理、并链接到这些证据的开发历程见 [docs/history/](docs/history/README.md)（英文）。

## 文档

| 文档 | 用途 |
| --- | --- |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 从全新检出开始的首次运行 |
| [docs/DEMO.md](docs/DEMO.md) | 合成数据的 Knowledge Library 演示 |
| [docs/RELEASE.md](docs/RELEASE.md) | Docker 发布、备份、恢复、升级、浏览器边界设置 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统如何工作；附录 A 为 HTTP API 参考 |
| [web/README.md](web/README.md) | 工作台各视图与标注行为 |
| [docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md](docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md) | 可重复的本地学习流程（简体中文），配合[捕获提示词](docs/CAPTURE_PROMPT.zh-CN.md) |
| [docs/history/](docs/history/README.md) | 设计如何演进，附日期与证据 |
| [docs/blog/](docs/blog/README.md) | 回顾性文章草稿 |
| [docs/plans/](docs/plans/)、[docs/validation/](docs/validation/) | 原始任务约定与验证报告 |
| [AGENTS.md](AGENTS.md) | 面向在本仓库工作的编码代理的说明 |

除 `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md` 与 `docs/CAPTURE_PROMPT.zh-CN.md` 外，上述文档均为英文。

## 仓库结构

```text
cmd/server, cmd/capture    服务端入口；轻量 capture 命令行
internal/                  domain、application、storage/sqlite、transport/http、
                           analyzer、extractor、embedding、config、captureclient
migrations/                内嵌、只向前的 SQL 迁移
web/                       React + Vite + TypeScript 工作台
examples/captures/         learning_capture_v1 示例文档
captures/, seed_demo.py    16 个合成 capture 及其导入脚本，脚本会写入你指定的
                           运行中后端
scripts/demo/flh034/       合成数据的 Knowledge Library 演示
scripts/validation/        各验证报告使用的隔离验证脚本
docs/                      上面列出的文档
```

## 开发

```bash
make test           # go test ./...
make vet            # go vet ./...
make fmt            # gofmt -w .
make build          # bin/server
make build-capture  # bin/capture
make verify         # 不修改文件的发布检查；需要 web/node_modules（npm ci）
```

## 许可证

本项目以 [MIT 许可证](LICENSE)发布。Copyright (c) 2026 Sirui Liu。该许可证适用于本仓库自身的代码与文档；
第三方依赖保留各自的许可证。
