# cn-agri-factor-miner

## 跨 Agent 安装：Codex、WorkBuddy 与其他工具（v0.2.0）

本技能不依赖 Codex 专有 API。Python 计算与审核规则共用一份代码，不同宿主仅使用不同的安装包与调用方式。

| 使用场景 | 获取方式 | 调用方式 | 验证范围 |
|---|---|---|---|
| Codex | 克隆仓库或用 skill-installer 安装 `.agents/skills/cn-agri-factor-miner` | `$cn-agri-factor-miner` 或自然语言 | 本地 CLI、审核暂停和完整测试已验证 |
| WorkBuddy | 下载 Releases 中的 `cn-agri-factor-miner-workbuddy-v0.2.0.zip` | 导入并启用后，用技能名自然语言调用 | 按官方格式适配，打包后的脚本已测试；未实测客户端 UI |
| 其他支持 SKILL.md 的 agent | 下载 `cn-agri-factor-miner-portable-v0.2.0.zip`，按该 agent 的导入入口安装 | 产品的技能选择器或自然语言 | 移动目录后的执行已验证；不保证所有宿主自动识别 |
| 无技能管理但有文件/终端工具的 agent | 解压通用包，将 SKILL.md 的绝对路径交给 agent | 明确要求读取该文件并执行 | 手动加载模式；计算仍需本地 Python |

下载入口：[GitHub Releases](https://github.com/spikewzy/cn-agri-factor-miner/releases/tag/v0.2.0)。不要把 GitHub 的整个源码 ZIP 当作 WorkBuddy 技能导入包。

### WorkBuddy：逐步导入与首次使用

1. 下载 **`cn-agri-factor-miner-workbuddy-v0.2.0.zip`**。包内根目录直接是 `SKILL.md` 和资源目录，已补齐 WorkBuddy 开放平台要求的中英文描述、版本和作者字段。
2. 打开 WorkBuddy 左侧的 **专家·技能·连接器 → 技能**（部分版本直接显示“技能”）。进入 **添加技能 → 上传技能/导入本地技能包**，选择上述 ZIP；具体按钮名称以你的客户端版本为准。导入后在已安装列表启用它。这里是本地导入，不是公开市场上架。
3. 新建一个任务，选定你可读写的研究工作目录。让 WorkBuddy 读取完整技能包并定位真实的 `SKILL_DIR`，不要让它猜安装路径。运行目录另选在研究工作区中。
4. 粘贴下面这段提示词；WorkBuddy 不要求 Codex 的 `$技能名` 写法：

```text
请使用已安装的 cn-agri-factor-miner（中国农业基本面因子研究）。
先找到该技能的 SKILL.md 实际路径，读取技能与跨 Agent 协议。
把 SKILL_DIR 设为该文件所在目录，RUN_DIR 设为我的研究工作区中的新目录，且必须在技能目录之外。
先运行 scripts/doctor.py --run-root RUN_DIR 检查 Python、文件锁和目录权限。
这次只运行自带的合成示例，保存 demo-report.json，解释每个状态。
模拟审批只用于示例；不要伪造我的真实批准，不要宣称因子有效或回测完成。
若无法执行脚本，请返回 BLOCKED_ENVIRONMENT 并列出缺失能力。
```

5. 正常演示应出现 `NOT_EVALUATED`、缺数阻塞和泄漏拦截，并保留 v1→v2 的修订记录。正常计算不是外部评估通过。准备真实数据后，按下方“接真实数据”部分继续，先在规格审核点等待你的明确决定。

官方依据：[WorkBuddy 技能结构](https://open.workbuddy.cn/docs/skill)、[技能市场](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)、[腾讯云技能说明](https://cloud.tencent.com/document/product/1831/134432)。菜单会随版本变化；本项目未在 WorkBuddy 客户端中实际点击导入，因此不把格式检查描述成 UI 实测。

### Windows 上使用 WorkBuddy

技能导入和 Python 运行是两件事。当前记录锁依赖 `fcntl`，**原生 Windows Python 不支持**，请使用 WSL 内的 Python 3.9+。WorkBuddy 还必须能够调用 WSL，或由你在 WSL 终端手动执行命令，再把结果交给它审核。

例如先在 PowerShell 中用 `wsl --list --verbose` 检查已安装的 WSL 发行版，并用 `wsl -- python3 --version` 确认 Python。进入 WSL 后，在可访问的研究目录克隆源码，再执行下方同样的 Linux 命令。不要把 Windows 的 `C:\...` 路径直接作为 Linux Python 路径。如果没有 WSL/终端能力，保持 `BLOCKED_ENVIRONMENT`，不要让 agent 用文字模拟计算。

### 所有 agent 通用的执行命令

以下在 macOS/Linux/WSL 的终端执行。先把两个示例路径替换成你的实际**绝对路径**；含空格或中文时保留双引号。

```bash
SKILL_DIR="/path/to/cn-agri-factor-miner"
RUN_DIR="/path/to/research/agri-run-001"
python3 "$SKILL_DIR/scripts/doctor.py" --run-root "$RUN_DIR"
python3 -m unittest discover -s "$SKILL_DIR/tests" -v
python3 "$SKILL_DIR/scripts/demo.py" --output "$RUN_DIR/synthetic-demo"
```

如果要在解压的技能包里直接参考本文后续的仓库命令，请把 `.agents/skills/cn-agri-factor-miner` 替换为 `$SKILL_DIR`。`agents/openai.yaml` 只是 Codex 展示元数据，不进入 WorkBuddy 包，也不影响计算。

### 自行构建导入包

在源码仓库根目录执行：

```bash
python3 tools/package_skill.py --target all --output dist
python3 -m unittest discover -s tests -v
```

`dist/` 生成通用 ZIP、WorkBuddy ZIP 及对应的逐文件 SHA-256 清单。打包器只读取技能定义，不会打入 `runs/`、本机凭据或研究快照。代码升级会改变既有运行的代码哈希；旧运行应保留并建立关联的新运行，不修改旧记录来绕过校验。

## 中文说明

这是一个面向**中国农业及农产品加工期货**的跨 Agent 技能，用于把基本面研究整理成可复现、可检验的因子。研究链路是：

**证据 → 经济假设 → 因子规格 → 确定性计算 → 外部评估 → 人工审核 → 研究记录。**

当前以豆粕、豆油为演示，可以通过配置扩展至谷物、畜禽、鸡蛋、水果、糖、棉花等农业品种。它不处理股票估值、金属或能源期货，也不负责自动交易、组合优化或替代现有回测器。

### 别人如何安装和调用

需要分享**完整的技能目录**，不能只上传 `SKILL.md` 或 README：计算脚本、参考资料、规格模板和示例也是技能的一部分。

方式一：克隆公开仓库，在该仓库目录中打开 Codex。

```bash
git clone https://github.com/spikewzy/cn-agri-factor-miner.git
cd cn-agri-factor-miner
```

仓库内的 `.agents/skills/cn-agri-factor-miner/` 是技能目录。在 Codex 中输入：

```text
使用 $cn-agri-factor-miner，先检查这个项目中已有的数据、字段字典、因子和人工修正记录。
研究豆粕和豆油的基本面因子，默认每周决策、两周预测期。
先提出候选假设并生成审核材料，等待我审核后再计算。
```

方式二：复制到自己的项目中。

```bash
# 将 /path/to/your-project 替换为自己的项目目录；目标不存在时再复制
mkdir -p /path/to/your-project/.agents/skills
cp -R cn-agri-factor-miner/.agents/skills/cn-agri-factor-miner /path/to/your-project/.agents/skills/
```

也可以在 Codex 中让 `$skill-installer` 从实际 GitHub 仓库安装 `.agents/skills/cn-agri-factor-miner` 目录。技能发现和安装方式参考 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)。如果安装后没有出现在技能列表中，重新打开任务或重启 Codex。

GitHub 提供的是技能源码和安装入口，不会自动提供在线 API、行情数据或运行中的交易服务。安装后，使用者在自己的 agent / Python 环境里运行；接入真实数据和外部评估器需要另行配置。

### 先运行合成数据示例

环境要求：Python 3.9 或更新版本，macOS / Linux；运行脚本只用 Python 标准库。由于记录锁使用 `fcntl`，Windows 原生 Python 未支持，可在 WSL 中使用。

以下命令在克隆后的仓库根目录执行：

```bash
# 运行验证测试
python3 -m unittest discover -s .agents/skills/cn-agri-factor-miner/tests -v

# 完整演示：正常计算、缺数阻塞、泄漏拦截、审核暂停与修订恢复
python3 .agents/skills/cn-agri-factor-miner/scripts/demo.py --output runs/my-first-demo
```

每次演示请选择新的输出目录，避免覆盖旧记录。结果在 `runs/my-first-demo/demo-report.json`；人工审核包、实验记录和因子面板在其各个子目录中。运行产物不属于技能定义，不需要随公开技能发布。

当前包含 **38 项核心测试（另有 4 项仓库级打包/迁移测试）、353 条合成数据记录和 3 个未经验证的豆粕/豆油假设**：季节性异常库存覆盖、未来两周到港与压榨平衡、受原料和油粕库存约束的压榨利润变化。合成数据只证明流程能够运行，不证明任何因子有预测能力。

### 看懂运行状态

| 状态 | 中文含义 | 下一步 |
|---|---|---|
| `PAUSED_REVIEW` | 尚未取得当前版本的人工批准 | 阅读审核包，再由本人提交对应版本和哈希的决定 |
| `BLOCKED_DATA` | 缺数据、字段过期或历史可用性不足 | 查看具体缺失字段，准备正确的数据快照 |
| `BLOCKED_INTEGRITY` / `LEAKAGE_TEST_FAILED` | 时点、数据完整性或泄漏检查失败 | 修复原因并保留失败记录，不能用人工批准绕过 |
| `NOT_EVALUATED` | 已计算并导出，但尚未经过外部评估 | 将冻结的评估请求交给独立维护的评估器 |
| `EVALUATED` | 已导入外部开发集评估结果 | 审阅证据、稳定性及增量贡献，仍不等于入库或交易授权 |
| `ACCEPTED_RESEARCH` | 经人工批准进入后续研究/影子测试 | 继续前瞻验证，不代表允许实盘交易 |

### 接真实数据之前需要准备什么

准备 `manifest.json`、`predictors.json`、`data_dictionary.json`、`existing_factors.json` 和 `human_corrections.json`，格式见下方英文操作说明与 `references/data-contract.md`。重点包括：

- 每条数据对应的观察/预测期间、来源、单位、发布时间、真正可用时间和修订版本。
- 经核验的期货代码、有效期内的合约与交割规则、节假日及夜盘交易日映射。
- 一致样本口径的库存、消耗、到港预测、压榨计划等实际数据；样本中 M/Y 仅是未经核验的提示。
- 单独维护的评估器及真实合约标签；本技能不会自行拼接连续价格来制造收益。

默认每批最多提出 6 个假设、入选 3 个，每个最多 3 个规格版本；绩效驱动的修改也计入次数。规格入选后、研究库接纳前均需本人明确审核。演示中的模拟审核不构成真实批准。

当前没有附带付费数据、真实历史发布时间库或外部回测器，因此示例正常返回 `NOT_EVALUATED`。详细英文命令与接口说明保留在下面，便于按字段接入。

---

A host-independent Agent Skill for bounded, evidence-first research on Chinese agricultural futures, with Codex and WorkBuddy packaging. Python 3.9+; standard library only; macOS/Linux (`fcntl` for append-only ledger locking). No API keys, network calls, GPU, database, dashboard, autonomous service or built-in backtester.

## Run the acceptance demonstrations

From the workspace root:

```bash
python3 -m unittest discover -s .agents/skills/cn-agri-factor-miner/tests -v
```

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/demo.py --output runs/agri-demo-001
```

Choose a fresh output directory on subsequent runs; immutable artifacts are not overwritten. The demo uses fixed seed 241, three illustrative hypotheses, 353 synthetic vintage records and three weekly decisions. Its **simulated test decisions are not human approvals**. It produces:

| Demonstration | Expected result |
|---|---|
| Unapproved specification | `PAUSED_REVIEW` |
| Normal synthetic computation, three hypotheses | Frozen specs, panels, lineage, diagnostics and requests; `NOT_EVALUATED` |
| Remove arrival forecasts | `BLOCKED_DATA` listing `arrivals_14d:eligible_vintage` for each affected decision |
| Deliberately unsafe test double reads future data | `LEAKAGE_TEST_FAILED`; subsequent approval blocked |
| REVISE, increment version, reopen and approve new version | Version history `[1, 2]`; pauses before reapproval, resumes to `NOT_EVALUATED` |
| Accept synthetic results into research library | Blocked; approved library remains empty |

Inspect `runs/agri-demo-001/demo-report.json`, `normal/experiments.jsonl`, `normal/review-*-logic.md`, `normal/exports/`, and separate `missing-data/` and `leakage-failure/` runs. Artifacts contain data/code/spec hashes; the original data generator and supplied examples must match.

## Invoke in Codex

“Use `$cn-agri-factor-miner` to inspect the available data for soybean meal/oil, consult prior research decisions, and propose at most six hypotheses. Stop at the specification review checkpoint.”

The canonical Codex workspace skill directory is `.agents/skills/cn-agri-factor-miner/`. If the current task's available-skill catalog was created before installation, open a new task or explicitly reference `SKILL.md`. Automatic skill discovery is enabled by default. [Routing cases](tests/routing-cases.json) cover agricultural positives and copper, energy, crypto, stocks, mixed non-agricultural groups and trade-execution negatives. Tests enforce structured commodity scope; natural-language skill selection is an LLM behavior and is not proven by those unit tests. The description and explicit scope instructions were reviewed against these cases.

## Start a file-based research run

For a manual synthetic run, initialize from shipped examples (no approvals are implied):

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic init --inputs .agents/skills/cn-agri-factor-miner/examples
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic propose --spec .agents/skills/cn-agri-factor-miner/examples/spec-inventory_coverage.json
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic shortlist inventory_coverage
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic compute inventory_coverage
```

The last command returns `PAUSED_REVIEW`. The human reviews the logic packet and supplies a completed copy of `templates/decision.json` with actual action/reviewer/timestamp, exact scope, version and hash. An agent must never fill in approval on the human's behalf.

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic review --decision /path/to/human-decision.json
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/manual-synthetic compute inventory_coverage
```

For a real run, prepare the five JSON inputs described in [data-contract.md](references/data-contract.md). Supply actual licensed/verified records, observed availability, effective-dated contract metadata, real calendar mappings and an external evaluation plan. Consult and import relevant previous histories:

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/next-batch init --inputs /path/to/development-inputs --history /path/to/previous-run
```

A new directory does not reset an authorized cross-run search budget. Preserve all linked attempts and stop for explicit expansion after six proposals/three shortlisted hypotheses/three specifications each.

## Revise and resume

Submit a human `REVISE` or `REQUEST_EVIDENCE` decision first. Create a complete new specification with the same id and next version; changing formula/evidence/parameters invalidates prior approval. Run:

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch revise --spec /path/to/spec-v2.json --reason 'Human-requested correction with evidence; counts as a revision'
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch review --decision /path/to/human-v2-decision.json
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch compute factor_id
```

All state is reconstructed from `experiments.jsonl`; `status` reads it without starting computation. Input or code changes require a fresh linked run and new approval. Never mutate frozen inputs or erase failed trials to recover.

## External evaluation and acceptance

Deliver the frozen `evaluation-request.json` to the separately maintained evaluator. The adapter does not execute arbitrary evaluator code or fetch final holdouts. A completed development-only response must match the request hash and [evaluation protocol](references/evaluation.md):

```bash
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch import-evaluation factor_id --result /path/to/external-development-result.json
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch packet --stage acceptance
python3 .agents/skills/cn-agri-factor-miner/scripts/cli.py --run runs/my-batch review --decision /path/to/human-acceptance-decision.json
```

Use `stage: acceptance` in that human decision. Acceptance requires observed PIT lineage, real data, completed/passing external diagnostics and no integrity failures. It creates `approved_research/factor_id.json` for further research/shadow testing only. The evaluator/custodian must provide actual access separation for final holdout; the CLI's scope flags are not filesystem security. Evaluation import attestations and human-origin fields are validated structurally, not independently authenticated.

## Files and extension boundaries

Host-independent setup, WorkBuddy frontmatter and capability fallbacks are documented in [agent-compatibility.md](references/agent-compatibility.md). Run `scripts/doctor.py --run-root /absolute/research/path` before first use in a new host. WorkBuddy UI import is not yet live-tested.

- `SKILL.md`: discovery metadata, workflow and hard checkpoints.
- `references/`: agricultural distinctions, source/data contract, three hypotheses, evaluation and memory protocols.
- `templates/`: complete spec structure, review packet, blank human decision/correction and honest evaluator-response template.
- `scripts/pit.py`, `factors.py`: as-of vintages, forecast alignment, mature-label helper and safe arithmetic.
- `scripts/records.py`, `workflow.py`: append-only ledger, hashes, local research history and bounded approval state machine.
- `scripts/adapter.py`, `cli.py`: external file contract and supervisory commands.
- `scripts/synthetic.py`, `demo.py`, `examples/`, `tests/`: reusable synthetic examples, positive/negative tests and acceptance demonstrations.

v1 implements only calendar-month historical seasonality and exact next-N-day forecast windows. It checks input unit identity but leaves full formula dimensionality, sample overlap and physical conversions to explicit review. It does not implement crop/lunar calendars, source scraping, exchange session lookup, signature authentication, a global budget database, live trading or performance estimation. Add a new agricultural family through the registry/specification and relevant data checks; new mathematical operators require review/tests.

## Remaining real-research blockers

The workspace originally contained no data, factors, corrections or evaluator. Missing inputs include historical same-sample processor stocks and disappearance; locally cleared soybean-arrival forecast vintages; raw-stock and dated crush plans; consistent price-derived margins with plant/feedstock conversion assumptions; observed publication/availability history; contract/session/holiday metadata; and external real-contract labels/evaluation. Official source entry-point access is recorded honestly in [data-contract.md](references/data-contract.md); it is not a connected historical database. No factor is validated or accepted for live use.
