# 自带 API / MCP 优先，缺失时主动发现日线来源

适用于 Codex、WorkBuddy 和其他能读写文件、运行 Python 的 agent。**Skill 负责规则和可移植脚本，MCP 调用与联网搜索由正在运行它的宿主 agent 执行。** 不要求别人也购买或配置 Tushare / Choice。

## 优先顺序

1. agent 先检查用户指定的数据源、项目配置、宿主已连接的 MCP/连接器和已有凭据。不要扫描或打印密钥内容；只检查相关环境变量是否存在。已连接的工具要实际发现名称、参数、返回结构和权限，再加入配置，不能虚构工具名。
2. `sources` 数组从前往后尝试；可以 MCP 优先，也可以自己的 API 优先。按**品种 + capability** 分别路由：有日线不代表有库存，取得仓单也不代表有社会库存。
3. 匹配的自有来源成功后，停止这一项的后续请求。拒绝访问、空结果、无效结构或日线校验失败才转向下一项。待调用的 MCP 返回 `PAUSED_MCP`，宿主完成调用/记录实际失败后才能继续，不能跳过它直奔默认来源。
4. 后续才尝试已有内置来源，例如已配置 `TUSHARE_TOKEN` 的 Tushare。已有 Choice 应以核实后的查询条目加入配置；脚本不猜指标代码、不安装或激活 SDK。`allow_builtin: false` 可关闭内置来源。
5. 日线均不可用时返回 `DISCOVER_DAILY_SOURCE` 和检索任务。**宿主必须接着执行搜索、读文档、小范围真实试取、配置可用候选并重试**。不能把这个状态当作工作完成。基本面缺口仍按来源计划继续查官方报告及其他数据源。

## 1. 创建使用者自己的配置

在 macOS/Linux/WSL 的终端执行。`SKILL_DIR`、`RUN_DIR` 使用实际绝对路径，运行目录必须在技能安装目录之外。

```bash
python3 "$SKILL_DIR/scripts/source_router.py" --work "$RUN_DIR/acquisition" init
```

它生成 `RUN_DIR/acquisition/data-sources.json`，包含**默认关闭**的 MCP 和 API 两个模板。修改并启用自己拥有的来源；示例地址和工具名不能直接使用。修改的是运行目录内的配置，升级技能不会覆盖它。

配置读取顺序：命令的 `--sources /absolute/path/data-sources.json` → 环境变量 `CN_AGRI_SOURCES` 指定的路径 → 当前 `--work` 目录下的 `data-sources.json`。显式指定的配置不存在时会报错，不会悄悄改用默认数据。

其他脚本也读取同一入口：

```bash
python3 "$SKILL_DIR/scripts/acquire.py" --work "$RUN_DIR/acquisition" \
  --sources "$RUN_DIR/acquisition/data-sources.json" start \
  --commodity 豆粕 豆油 --start 2026-09-01 --end 2026-09-21
```

日期替换为研究区间。`start` 路由仓单与合约元数据；宿主还需按计划选择并核实合约，然后执行下面的日线命令。不会自行猜一个主力合约。

## 2. 填自己的 API Key 和接口

编辑模板的 `my-daily-api`：

- `enabled` 改成 `true`；`request.url` 填服务商的 HTTPS 日线地址；按真实文档修改 GET 参数或 POST `json`。
- `auth.env` 填**保存 Key 的环境变量名**，例如 `MY_MARKET_DATA_KEY`，Key 本身只在你本机/宿主的凭据设置中配置。不要把 Key 发到聊天或写进 JSON、README、GitHub。
- 请求头鉴权示例：`{"env":"MY_MARKET_DATA_KEY","in":"header","name":"Authorization","prefix":"Bearer "}`。支持 `in: "query"`、`in: "body"`（仅 POST）；无前缀的 `X-API-Key` 可省略 `prefix`。公开接口直接删掉 `auth`。
- `response.rows_path` 描述数组位置。返回 `{"data":{"items":[...]}}` 时填 `["data","items"]`；顶层数组填 `[]`。支持 JSON、UTF-8 CSV、有限的赋值型 JSONP；从不执行响应中的 JavaScript。二维数组可用 `response.columns` 显式提供列名。
- `response.row_limit` 按服务商真实单次上限填写。达到上限会要求缩小区间或由宿主实现分页，不把被截断的数据当完整历史。通用 HTTP 适配器不自动猜分页协议、签名算法或 OAuth 流程；复杂鉴权可通过已有 MCP/SDK 获取后导入。
- `daily.columns` 填真实列名；必需 date/open/high/low/close，可选 contract/settle/volume/open_interest/amount。缺失可选字段保留为空，不填零。填写 `series_type`（`actual_contract` / `continuous`）、`price_unit`、`adjustment`；未知填 `unknown` 并继续核实，不能声称具备回测条件。
- `evidence` 保存接口文档与试取证据的位置，说明单位、覆盖期和限制。模板占位证据必须替换。

支持占位符：`{commodity}`、`{symbol}`、`{exchange}`、`{contract}`、`{contract_code}`（去掉点号交易所后缀）、`{start}` / `{end}`（YYYY-MM-DD）、`{start_date}` / `{end_date}`（YYYYMMDD）。必要时在特定品种的来源条目里直接填写已核实的供应商代码；不得假定各服务商代码一致。若响应代码无后缀而请求使用完整代码，可设置 `daily.contract_value: "{contract_code}"` 明确匹配关系。

然后让 agent 执行：

```bash
python3 "$SKILL_DIR/scripts/source_router.py" --work "$RUN_DIR/acquisition" daily \
  --commodity 豆粕 --contract M2701.DCE --start 2026-09-01 --end 2026-09-21
```

这里的合约只是命令示例，使用时核实上市/到期日期、代码和研究目的。成功返回 `daily_file`；文件保存在 `market/`，有来源、原始响应哈希、首次取得时间及日期排序后的 OHLC。重复日期冲突、错误合约、非有限数值和不合逻辑的高低价会触发回退。没有交易日历验证时仍标记 `calendar_coverage: UNVERIFIED`；仅“有数据”不能证明没有缺失交易日。

HTTP 响应按原样归档，认证参数只在内存中拼入请求，不记录到文件和报错文本。服务商若在响应中回显当前配置的 Key，会拒绝归档。脚本拒绝 API 重定向，避免向其他地址转交凭据。

## 3. 使用自己已经连接的 MCP

先在宿主自身的连接器/MCP 设置中完成连接和鉴权。Skill 不创建 MCP 服务器，也不要求你再填同一把 Key。

让 agent 读取实际工具定义，修改 `my-daily-mcp` 的 `server`、`tool`、`arguments` 和 `daily` 字段映射，填好 `evidence`、启用，放在你想要的优先位置。数据工具必须只读。同样运行上面的 `daily` 命令，会返回：

- `status: PAUSED_MCP`
- `handoff`: 带请求哈希、真实参数和工具映射的本地文件
- `request_id`: 本次接力标识

宿主读取 handoff，使用自己的工具调用能力执行 MCP。若结果被连接器包装，解包为**保持原数值、列名和单位的 JSON 行对象数组**，保存到运行目录，不写入个人凭据；保留实际调用引用。然后：

```bash
python3 "$SKILL_DIR/scripts/source_router.py" --work "$RUN_DIR/acquisition" resolve-mcp \
  --request-id ACTUAL_REQUEST_ID --status SUCCESS \
  --file "$RUN_DIR/acquisition/mcp-result.json" --call-evidence "实际工具调用引用或本地调用记录路径"
```

接着重新执行同一条 `daily` 命令，脚本校验、归档、生成日线文件。`SUCCESS` 只是宿主返回了数据，仍需通过字段/日线校验。

如果工具确实不存在，用 `--status BLOCKED_TOOL`，保留工具发现证据；调用失败可用 `BLOCKED_AUTH`、`BLOCKED_NETWORK`、`BLOCKED_PROVIDER`，无结果用 `EMPTY`；这些状态不带 `--file`。重新执行后才尝试下一个源。不允许模拟一次不存在的调用。一次 handoff 只解析一次；重新取快照或重新尝试已失败的 MCP 时创建新的 acquisition 目录，保留旧记录。凭据由宿主管理，不能放在 `arguments`。

测试覆盖模拟 MCP 的接力协议；仓库不声称已与所有供应商 MCP 或 WorkBuddy 客户端完成真实联调。

## 4. 没有 API / MCP 时，agent 怎么继续找日线

宿主按 `DISCOVER_DAILY_SOURCE` 的实际检索任务执行，不要求用户先购买服务：

1. 查交易所公开数据、数据提供方或开源库维护者的原始文档；确认是中国农业期货、日频、所需合约。可参考 [Tushare fut_daily](https://tushare.pro/document/2?doc_id=138)、[AKShare 官方实现](https://github.com/akfamily/akshare/blob/main/akshare/futures/futures_zh_sina.py)，也应搜索其他当前可用来源。
2. 小范围真实试取，保存调用失败/成功、响应和字段检查。区分需权限、网络失败、空数据、已下市合约、不支持的返回格式；不把一个接口失败当作所有渠道无数据。
3. 将证据和验证过的请求写入用户配置，再运行同一需求。模板 [discovered-public-daily.example.json](../templates/discovered-public-daily.example.json) 是 2026-09-23 试通的新浪日线候选配置；默认关闭，不保证未来可用、历史完整、任意合约可查询或单位已验证。参考它做现场试取；不可直接把连续合约当实盘合约。
4. 所有候选确实失败时保留检索/试取记录，说明还缺哪些合约、日期或字段。搜索工具不可用时明确 `BLOCKED_TOOL`，不得声称“已经搜索过”。

日线提供价格、成交量、持仓量等市场背景，**不能替代库存、产量、压榨、到港、饲料需求等基本面数据**。市场日线默认保留在 `market/`，不自动写入基本面 `predictors.json` 或未来收益标签。基差/利润等价格衍生因子需要另行审核规格和映射。所有未经历史发布版本验证的下载数据仍从实际 `first_seen_at` 起可用，不能按行情日期倒填可用时点。

## 5. 基本面、合约和其他自定义能力

同一个 `sources` 数组支持 `capability: "warehouse"`、`"contracts"`，以及自定义名称，例如 `"inventory"`。`commodities` 填技能中的品种 ID（如 `soybean_meal`）；省略表示所有品种，只有接口确实支持时才省略。

- `start` 会对 warehouse / contracts 先尝试自有来源，再使用默认接口。
- 其他基本面需求可用 `source_router.py ... request --capability inventory --commodity 豆粕 --start ... --end ...`。基本面来源需要 `mapping`，结构见 [table-mapping.json](../templates/table-mapping.json)；成功后用 `acquire.py normalize --receipt RECEIPT_ID --mapping /path/to/mapping.json` 导入。已有 `plan.json` 时，重跑 `start` 也会标准化其映射。
- HTTP 保留完整原始响应；为了与已有标准化兼容，会额外保存绑定原响应哈希的行数组。不存在将日线自动转换成基本面的映射。
- 配置也支持 `provider: "choice"`（实际 `api/args/options/mapping_evidence`）和 `provider: "tushare"`（实际 `api/params/fields`）。沿用 [主动取数教程](data-acquisition.md)，加入 `id/capability/commodities/evidence` 和需要的 `mapping` 或 `daily`；数组顺序同样生效。

`routing/` 保存每次来源选择和失败原因，`mcp/` 保存工具接力，`receipts/` 与 `raw/` 保存证据，`market/` 保存市场日线。把整个运行目录保留在本机或你的研究存储，不提交公共仓库。
