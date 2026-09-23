# cn-agri-factor-miner

> All from Vibe just a test please be careful
>
> 实验性研究项目：请先验证流程和数据，示例不代表已验证的投资信号。

**中国农业期货基本面因子研究技能 · Codex / WorkBuddy / 其他 Agent**

把农业基本面证据整理为可解释、可复现、可检验的因子，保留数据时点、修订历史、人工审核和失败记录。首批示例为豆粕与豆油，可以配置扩展到其他中国农业期货。

[中文使用说明与完整命令](.agents/skills/cn-agri-factor-miner/README.md) · [技能入口](.agents/skills/cn-agri-factor-miner/SKILL.md) · [农业研究检查表](.agents/skills/cn-agri-factor-miner/references/agriculture.md)

## 直接让 Agent 自己找数据

```text
使用 cn-agri-factor-miner 研究豆粕和豆油，周频决策、预测未来两周。
先检查项目里的数据、已有因子和修正记录，然后主动搜索官方及行业资料，
优先调用我已有的 API / MCP，再使用其他已配置接口获取可用数据。
保留来源、原始快照、抓取时间、发布时间与修订版本，列出实际缺口。
根据证据提出至多 6 个假设、筛选至多 3 个，给出机制、反证和候选规格。
在我明确批准前不要计算因子。
```

v0.3.0 加入的实际取数代码包括：Tushare 仓单与合约接口、Choice `csd/ctr/edb/edbquery`、公开 HTTPS 文件以及 CSV/JSON 标准化。内置 17 个农业品种的来源计划，agent 会接着执行公开资料搜索和缺口补充。没有某个付费接口权限时，继续找其他可访问来源。

**分工**：Python 负责接口访问、原始记录、标准化和时点校验；宿主 agent 负责联网搜索、读取报告、核实 Choice 指标与单位、提出经济假设。仅运行终端脚本不会自动调用一个 LLM。

从源码目录体验自动取数：

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/acquire.py \
  --work runs/real-discovery-001 start --commodity 豆粕 豆油 \
  --start 2026-09-01 --end 2026-09-21
```

日期改为实际研究区间。脚本使用已配置的 `TUSHARE_TOKEN`，不会输出凭据；有宿主连接器时可由 agent 直接调用后导入，无需另配 Token。Choice 需要已有的 SDK、激活权限及 pandas；不能凭空取得收费数据。详细的来源搜索、Choice 请求格式、数据映射与原研究引擎衔接见[主动取数教程](.agents/skills/cn-agri-factor-miner/references/data-acquisition.md)。

首次下载的旧数据没有历史版本证据时，只能从本次取得时刻起使用，不能按观察日期回填。仓单保留原单位和仓库明细，不能当作全市场库存。演示数据与真实下载数据分别保存。

## 优先使用你自己的 API / MCP

v0.4.0 增加可编辑的 `data-sources.json`，Codex、WorkBuddy 和其他兼容 agent 使用同一套配置：

**用户按顺序配置的 API / 已连接 MCP → 已有内置接口 → agent 主动搜索并试取其他基础日线接口。** 日线、仓单、合约和基本面按各自需求选择来源，有日线不代表有库存等基本面数据。

不需要在聊天里发 Key。配置里只写 API 地址、Key 的环境变量名、真实 MCP 工具和参数映射。没有自己的源时，也不要求先购买某个数据服务。

在终端生成模板（路径改为实际技能和研究目录）：

```bash
python3 "$SKILL_DIR/scripts/source_router.py" --work "$RUN_DIR/acquisition" init
```

编辑生成的 `data-sources.json`，启用并排列自己的来源。也可以直接对 agent 说：

```text
使用 cn-agri-factor-miner。先检查我已连接的 MCP 和项目的数据源配置，
把真实可用的工具、接口及字段映射写入研究目录的 data-sources.json。
优先调用我的来源，Key 只引用本机环境变量，缺失时再尝试已有接口。
若仍没有基础日线数据，请继续搜索其他可用接口、真实试取并验证后接入。
分别说明日线行情和基本面数据的实际覆盖、口径及缺口。
```

[完整中文配置教程：API Key、MCP 接力、日线回退、基本面接口](.agents/skills/cn-agri-factor-miner/references/data-sources.md)。MCP 由宿主 agent 实际调用，脚本负责请求绑定、归档和验证；不能仅凭填写工具名就自动获得权限。模板默认关闭，按自己的真实服务商文档填写后再启用。

## 选择安装方式

| Agent | 安装包 / 源码 | 使用方式 |
|---|---|---|
| Codex | 克隆本仓库，或安装 `.agents/skills/cn-agri-factor-miner/` | `$cn-agri-factor-miner` 或自然语言 |
| WorkBuddy | [下载 WorkBuddy 专用 ZIP](https://github.com/spikewzy/cn-agri-factor-miner/releases/download/v0.4.0/cn-agri-factor-miner-workbuddy-v0.4.0.zip) | 导入、启用后按技能名称调用 |
| 其他支持 SKILL.md 的 agent | [下载通用 ZIP](https://github.com/spikewzy/cn-agri-factor-miner/releases/download/v0.4.0/cn-agri-factor-miner-portable-v0.4.0.zip) | 按宿主的技能导入方式安装 |
| 只有文件和终端工具的 agent | 解压通用 ZIP | 明确要求读取 SKILL.md 的绝对路径并遵循它 |

两个包共用研究规则和计算脚本。WorkBuddy 包额外提供中英文描述、版本、作者，移除 Codex 展示元数据；ZIP 根目录直接包含 `SKILL.md`。**不要用 GitHub 的整仓库源码 ZIP 代替技能导入包。**

### WorkBuddy 安装教程

1. 下载上表的 **WorkBuddy 专用 ZIP**，保留完整压缩包。
2. 打开 WorkBuddy 左侧 **专家·技能·连接器 → 技能**，通过 **添加技能 → 上传技能 / 导入本地技能包** 选择 ZIP；不同版本按钮名称可能不同。导入后在已安装技能中启用它。这是本地安装，不是技能市场上架。
3. 新建任务，选定可读写的研究工作目录，然后粘贴：

```text
请使用 cn-agri-factor-miner（中国农业基本面因子研究）。
读取已安装技能的 SKILL.md 和 references/agent-compatibility.md。
定位 SKILL.md 的实际目录作为 SKILL_DIR，不要猜测安装路径。
在我的研究工作区中创建独立的 RUN_DIR，必须放在技能目录之外。
先运行 scripts/doctor.py --run-root RUN_DIR，再运行自带的合成演示。
保存并解释 demo-report.json。无法执行命令时返回 BLOCKED_ENVIRONMENT。
演示中的模拟审批不代表我批准真实研究，不要宣称因子已有效或回测通过。
```

4. 环境检查应为 `READY`；演示正常计算部分应为 `NOT_EVALUATED`，因为本项目不自带外部回测器。演示还会展示缺数阻塞、未来数据拦截和修订恢复。
5. 使用真实数据时，改为要求“检查我的数据、生成候选规格与审核材料，在计算前等待我的明确审批”。操作和命令见[完整中文教程](.agents/skills/cn-agri-factor-miner/README.md)。

**运行环境：Python 3.9+、macOS / Linux。Windows 使用 WSL 内的 Python**，WorkBuddy 需要能调用 WSL；也可手动在 WSL 中执行命令并将结果交给 agent。当前文件锁依赖 `fcntl`，不支持原生 Windows Python。导入成功不等于具备执行能力。

适配依据：[WorkBuddy 官方技能格式](https://open.workbuddy.cn/docs/skill)及[技能管理文档](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。已验证安装包格式及搬迁目录后的脚本执行；**尚未实测 WorkBuddy 客户端界面导入**，也不保证所有 agent 自动发现技能。

### Codex 安装教程

克隆或下载这个仓库，然后在仓库目录中打开 Codex。

```bash
git clone https://github.com/spikewzy/cn-agri-factor-miner.git
cd cn-agri-factor-miner
```

技能位于 `.agents/skills/cn-agri-factor-miner/`。请保留完整目录，不能只复制 `SKILL.md`。

在 Codex 中输入：

```text
使用 $cn-agri-factor-miner，先检查项目中的数据、已有因子和人工修正记录。
研究豆粕和豆油的基本面因子，每周决策，主要预测未来两周。
先生成候选规格和审核材料，等待我审核后再计算。
```

也可把完整技能目录复制到其他项目的 `.agents/skills/` 下，或在 Codex 中输入：

```text
使用 $skill-installer，从 https://github.com/spikewzy/cn-agri-factor-miner 安装
.agents/skills/cn-agri-factor-miner 目录中的技能。
```

技能扫描与安装规则见 [OpenAI 官方文档](https://learn.chatgpt.com/docs/build-skills)。GitHub 是源码分发入口；计算在使用者自己的环境执行，并非托管在线 API。

## 快速验证

Python 3.9+，macOS / Linux，Python 标准库即可。Windows 可使用 WSL。

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/doctor.py --run-root runs/my-first-run
python3 -m unittest discover -s .agents/skills/cn-agri-factor-miner/tests -v
python3 -m unittest discover -s tests -v
python3 .agents/skills/cn-agri-factor-miner/scripts/demo.py --output runs/my-first-demo
```

结果见 `runs/my-first-demo/demo-report.json`。再次运行时换一个输出目录，旧记录不会被覆盖。

当前有 80 项核心与取数测试和 4 项打包/迁移测试通过、353 条明确标记的合成记录、3 个未经验证的示例假设。演示覆盖正常计算、缺数阻塞、未来数据泄漏拦截、人工审核暂停及修订恢复。

若使用解压后的安装包，请将命令中的 `.agents/skills/cn-agri-factor-miner` 换成解压目录的绝对路径，并给输出目录指定技能目录之外的位置。仓库级 `tests/` 是打包测试，仅在源码仓库中运行。

从源码重新生成两个 ZIP 及 SHA-256 清单：

```bash
python3 tools/package_skill.py --target all --output dist
```

发布包和校验清单见 [v0.4.0 Release](https://github.com/spikewzy/cn-agri-factor-miner/releases/tag/v0.4.0)。打包测试会把两种 ZIP 分别解压到含中文和空格的新路径，检查全部核心测试、演示及审批暂停。

## 工作流和边界

**证据 → 经济假设 → 冻结规格 → 确定性计算 → 外部评估 → 人工审核 → 研究记录**

- 一批最多 6 个假设、3 个入选假设、每个最多 3 个规格版本；拒绝和失败也保留。
- 所有因子通过 as-of 接口读取数据；未知历史发布时间不能声称已验证时点安全。
- 人工批准绑定规格版本和哈希，实质修改后重新审核。
- 无外部评估器时返回 `NOT_EVALUATED`，不会编造 IC、收益率或夏普比率。
- 研究库接纳仅供进一步研究和前瞻影子验证，不授权实盘交易。

技能不覆盖非农业期货、股票估值或自动交易，也不内置回测引擎。三个示例仅展示流程，尚无预测能力或收益证据。技能会主动发现和获取权限范围内的数据；不可访问的数据、缺失的历史版本、合约日历及外部评估仍会列为具体缺口。

## 目录

```text
.agents/skills/cn-agri-factor-miner/
├── SKILL.md          技能触发条件与工作流
├── README.md         中英文操作说明
├── agents/           Codex 展示元数据
├── scripts/          来源计划、取数、归档、计算、审核与评估接口
├── references/       农业知识检查表及数据/评估协议
├── templates/        因子规格、人工决定与审核模板
├── examples/         完全合成的示例输入
└── tests/            测试与路由场景
```

本仓库发布技能代码、文档、模板和合成样例。运行产生的研究记录放在 `runs/`，已通过 `.gitignore` 排除。
