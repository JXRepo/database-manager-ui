---
status: completed
branch: main
timestamp: 2026-09-17T19:34:25+02:00
code_commit: b9e5c3ac9de88946367a275d13afa1c2a4bf66fa
files_modified:
  - HANDOFF.md
---

# Project handoff

## 当前状态

2026-09-17 的功能修改已完成，最新功能提交是 `b9e5c3a`。本次恢复时已通过
`git ls-remote origin refs/heads/main` 确认远端也是该提交，工作区原本干净。

上一轮最后的请求是“写个 handoff 放仓库根目录”，但会话在写入前中断。
本文件补齐该交接；没有待继续实现的功能，也没有待合并的代理改动。
后续应以用户的新请求为准，不要把 README 的未来方向当作已授权任务。

代码已推送与 Render 部署完成是两件事。**尚未确认线上部署完成。**
试用站点：[FAIR Materials Data Platform](https://fair-materials-data-hub.onrender.com/)。

## 新会话先读

1. 阅读 [AGENTS.md](AGENTS.md)，再读 [README.md](README.md) 的 Search、
   Data object identifiers、Local Setup 和 Verification。
2. 检查 `git status --short`、`git log -10 --oneline` 和当前分支。
   本交接是时间快照，后续仓库状态可能已变化。
3. 使用本机 PyCharm 配置的解释器；运行 Python 前通过环境工具确认路径。
   本地开发和测试使用 `DEBUG=True`、SQLite，不使用生产数据库凭据。
4. 中文简洁沟通，应用 UI 保持英文。明确的修改直接做完、验证、检查 diff，
   然后按用户习惯 `git add .`、commit、push；排除凭据和无关文件。
   不强推，不丢弃其他电脑的未提交改动。

## 最近完成的修改

| 提交 | 内容 |
| --- | --- |
| `b9e5c3a` | 12 项科学字段预设，递归且按类型匹配，布尔周期性、温度换算和旧链接兼容 |
| `e1ca274` | Identifier 输入保持紧凑，标签换行后输入框仍对齐 |
| `39d0d0e` | Common filters 优先排列 Identifier、Access、Owner |
| `3b3eae1` | 自动生成 8 位小写 base36 标识符，冲突时逐位延长 |
| `31bfef7` | 整理 Common filters，增加高级区域 Search 和 Clear |
| `fbac1ca` | 对齐真实数据的科学筛选字段，补齐缺失 identifier |

### 搜索规则

- Common filters 顺序固定为 Identifier、Access、Owner (uploaded by)、Creator、
  Software、Phase、Title；Owner 仍使用 `owner` 参数。
- 上下 Search 提交同一个 GET 表单及全部条件；两处 Clear 清空全部条件；关键词可留空。
- 12 项预设分四组：微结构的 Texture type、Grain count、Crystal structure、
  Orientation identifier；离散化与边界的 Discretization type、Discretization count、
  RVE continuity；材料模型的 Elastic model、Plastic model；加载与温度的
  Loading type、Loading mode、Global temperature。
- 预设递归遍历字典和数组，搜索深度上限 32；键名忽略大小写、空白、下划线、连字符。
  只接受已定义别名，例如 `grain_number` 表示计数；不要推断任意同义词。
- Loading type 和 Loading mode 只匹配 `mechanical_BC` 内字段，排除 `thermal_BC`。
  计数、文本和布尔值按类型匹配，不能把整个参数字典当成目标值。
- RVE continuity 用 Is：Periodic / Non-periodic，对应真正的 JSON `true` / `false`。
  字符串和数字 0、1 不算布尔值。URL 布尔值带空白时的回显问题也已修复。
- Global temperature 输入单位为 K；按最近包围层的温度单位转换 K、Celsius、Fahrenheit。
  不借用兄弟对象单位；缺失或未知单位、低于绝对零度的数据不匹配。
- Orientation identifier 默认 Equals text。Match 类型在前后端均校验；无效条件报错，
  不放宽搜索。全部条件必须命中同一可访问记录，但可以命中该记录内不同数组条目。
- 旧 JSON 路径保留精确路径语义；旧 Ronak token 保留原键名匹配语义。
  退役的 elastic/plastic parameters 只在活动书签中显示，保持原路径与 Contains words。
- 普通搜索包含本人、公开及明确分享给本人的数据；Live Data Objects 仅显示
  `access_type="all"` 的最新 20 条，保持紧凑、限定高度并可滚动。

关键文件：[advanced_search.py](apps/pages/advanced_search.py)、
[views.py](apps/pages/views.py)、[search.html](templates/pages/search.html)、
[advanced-search.js](static/assets/js/advanced-search.js)。

### 上传标识符

- 上传校验只要求 24 个顶层字段，包含 `phase`；`identifier` 不再必填。
- 缺失、null 或空白 identifier 会从必填内容生成 8 位小写 base36 ID，
  不同内容占用同一 ID 时逐位延长；合法自带文本 ID 保留。
- 内部保存完整 SHA-256 指纹，用于识别延长后再次上传的相同必填内容，并兼容旧 64 位 ID。
  可选元数据不进入指纹；不自动重算旧 ID，也不覆盖重复记录。
- 最终分配与全库、整批复查在上传事务锁内完成，并按最终 JSON 字节大小计入存储配额。
  自带不同 ID 的记录不自动扩展为全内容去重。
- 关键文件：[helpers.py](apps/dyn_api/helpers.py)、
  [upload_services.py](apps/pages/upload_services.py)、[models.py](apps/pages/models.py)。
  相关迁移：[0010_jsondata_identifier_fingerprint.py](apps/pages/migrations/0010_jsondata_identifier_fingerprint.py)。
  最新搜索提交 `b9e5c3a` 本身不增加迁移。

## 验证记录与限制

以下是从上一轮会话恢复的验证结果，不是本次文档补写重新运行的结果：

- 最终 493 项 Django 测试、45 项前端测试通过。
- 搜索页面检查了 5 种屏幕宽度，包含桌面、手机、空内容、长内容与条件恢复。
- 布尔值空白回显修复后，101 项搜索测试及最终全量测试通过，独立复核未发现阻断问题。
- 12 项预设有合成夹具 [search_fields.json](apps/pages/fixtures/search_fields.json)；
  `example_json_files/` 在本机存在时也参与测试。合成夹具不是完整上传模板。
  本机 11 个示例科学内容相同，且没有 `lattice_structure`；不能据此推断线上数据分布。
- SQLite 下的标识符测试不是 PostgreSQL 真实多连接并发验证；后者尚未进行。
- 无 JavaScript 时，从空白条件首次切换到 RVE continuity，需先提交一次才由服务端
  显示 Is 与布尔选项；已保存条件的服务端回显正常，错误不会放宽搜索。

后续修改可按 README 使用本机已确认的解释器运行 Django 测试、
`manage.py check` 和 `manage.py makemigrations --check --dry-run`。
搜索或登录 JavaScript 修改需运行 `node --test tests/js/*.test.cjs`。
`.node-version` 指定 Node v22.0.0；浏览器测试需要全局 `WebSocket` 和 Chromium，
必要时设置 `CHROMIUM_BIN`。浏览器测试被跳过不能算验证通过。

## 后续事项

没有遗留的功能实现任务。本次只补写交接并检查文档路径、Git 差异与推送状态。
尚未完成的外部核实是 Render 部署状态和线上功能检查；如继续验收，先确认部署的提交，
再检查上述筛选、旧链接与权限。部署说明见
[public-pilot.md](docs/deployment/public-pilot.md)。

不要依赖旧会话、本机临时截图、登录状态或另一台电脑的解释器路径。
不要提交 `.env`、本地数据库、虚拟环境或私有上传数据。
