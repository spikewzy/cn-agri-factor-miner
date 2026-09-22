# Agent compatibility / 跨 Agent 使用协议

同一套因子计算、时点访问、预算和人工审核逻辑适用于所有宿主。安装成功只说明技能文件可被识别；必须另行检查 Python、文件权限和脚本执行能力。宿主安全策略和用户决定优先，不要为了兼容而绕过它们。

## 能力和路径

| 能力 | 有此能力时 | 缺少时 |
|---|---|---|
| 读取完整技能目录 | 按相对路径读取 SKILL.md、references、templates、examples | BLOCKED_ENVIRONMENT，列出缺失文件；仅贴 SKILL.md 不够 |
| 执行本地 Python 3.9+ | 通过终端工具运行 doctor.py、cli.py 和测试 | 仅做经济假设及审核材料草稿，不编造执行结果 |
| POSIX 文件锁 | macOS/Linux/可访问的 WSL 环境可执行记录写入 | 原生 Windows 不支持；不删除锁来强行运行 |
| 读写用户研究目录 | 输出 Markdown、JSON、JSONL 到 RUN_DIR | BLOCKED_ENVIRONMENT，申请具体目录访问 |
| 取得用户明确决定 | 保存真实 APPROVE/REVISE/REJECT/MERGE/REQUEST_EVIDENCE | PAUSED_REVIEW；宿主工具授权不等于因子审核批准 |
| 外部评估器 | 使用冻结请求与匹配的开发集响应 | NOT_EVALUATED；没有内置回测器 |

`SKILL_DIR` 必须从实际加载的 SKILL.md 所在位置解析；不要假定 `~/.workbuddy/skills`、`.agents/skills` 或进程当前目录。`RUN_DIR` 必须位于技能目录之外的独立研究工作区。进程参数逐项传递或正确引用；空格、中文路径不应改变行为。Windows + WSL 下，路径必须换成 WSL 内可访问的路径，不能把 `C:\...` 直接传给 Linux Python。

`doctor.py --run-root ...` 会检查所需资源、Python、锁和目录可写性，并创建指定输出目录及一个随后删除的临时探测文件；不调用网络、不读凭据、不创建审批。READY 不等于数据合格或通过外部评估。

## 宿主适配

- **Codex**：仓库的 `.agents/skills/cn-agri-factor-miner/` 为标准源目录；可使用 `$cn-agri-factor-miner`。`agents/openai.yaml` 只影响 Codex 展示。
- **WorkBuddy**：使用专用 `workbuddy` ZIP，通过技能页面导入并启用，再按技能名自然语言调用。发布脚本根据开放平台文档补齐 `description_zh`、`description_en`、`version` 和 `author` 等信息。研究指令正文和 Python 代码与标准包一致，Codex UI 元数据不进入此包。
- **其他支持 SKILL.md 的 agent**：使用 `portable` ZIP，按该产品自己的安装入口导入；本项目不猜测产品目录，不宣称所有产品均能自动识别。
- **没有技能导入功能，但有本地文件和终端工具的 agent**：解压通用包，将 SKILL.md 的绝对路径交给 agent，要求读取并执行本协议。这个方式是手动加载指令，不是原生技能安装。
- **纯聊天/仅网页端 agent**：可以协助分析文字、起草假设与审核；无法访问本地 Python 时不得声称完成确定性计算。

不需要 Codex MCP、OpenAI API key、WorkBuddy API key、固定模型或专有数据库。模型/宿主只负责证据和研究推理；数值计算由相同 Python helper 执行。将实际 `host_agent`、`model`、`prompt`、`source_extraction_version` 和 `retrospective_llm` 记录在 manifest 的 `model_prompt_versions` 中。更换 agent 不重置搜索预算，不清除历史失败，不等于重新获得审批。

## 包格式与验证边界

版本 0.3.0 提供两个扁平 ZIP：解压根目录直接包含 SKILL.md、scripts/、references/、templates/、examples/、tests/ 和 README.md。不能把整个 GitHub 仓库 ZIP（带 `.agents/skills/...` 多层目录）当作 WorkBuddy 技能导入包。包由 `tools/package_skill.py` 从唯一源目录生成，附逐文件 SHA-256 清单。

WorkBuddy 专用包与通用包只允许 frontmatter / Codex 展示元数据存在差异；代码、因子规则、人工审核点和示例相同。相同数据与规格可重算；旧运行快照包含绝对 artifact 路径，不能承诺把旧 RUN_DIR 随意搬到另一机器后直接续跑，应在新路径建关联运行并保留历史。

已在本地验证包可迁移到含中文/空格的目录，从不同工作目录执行；对打包后的脚本运行测试和合成演示。没有安装 WorkBuddy 客户端进行真实界面导入，因此兼容状态是“按官方格式适配 + 独立运行验证”，不是“所有客户端已实测”。如果宿主拒绝导入，记录版本和错误，不降低安全或数据约束。

官方来源，核对于 2026-09-22：

- [WorkBuddy 开放平台：技能结构及 frontmatter](https://open.workbuddy.cn/docs/skill)
- [WorkBuddy 技能市场](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
- [腾讯云 WorkBuddy Enterprise：技能](https://cloud.tencent.com/document/product/1831/134432)（页面检索可见上传本地技能包说明，直接正文抓取超时；客户端按钮随版本变化）

市场上架是另一项操作。本仓库只分发本地导入包，未向 WorkBuddy 技能市场提交或声称官方认证。

## 主动取数能力

核心研究脚本仍只需 Python 标准库。主动取数另外使用宿主搜索/浏览、网络和已有的数据权限；Choice 额外需要 EmQuantAPI 与 pandas。Tushare 可用宿主连接器或环境变量，不需要固定 MCP。缺少某项能力时继续其他来源并记下阻塞，见 [取数流程](data-acquisition.md)。
