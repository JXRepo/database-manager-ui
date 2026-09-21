---
status: completed
branch: main
timestamp: 2026-09-21T21:57:41+02:00
code_commit: c8505a108f224e10202ea3030d5f4385707a5e48
files_modified:
  - HANDOFF.md
---

# Project handoff

## 当前状态

My Data 下拉筛选已完成，最新功能提交是 `c8505a1`；之前的 Search 和 Upload Data 修改保留。
写本交接前，工作区干净，已用 `git ls-remote origin refs/heads/main` 确认
GitHub 的 `main` 也是 `c8505a108f224e10202ea3030d5f4385707a5e48`。
本交接会另行提交并推送，所以拉取后 HEAD 应是包含本文件更新的文档提交。

用户计划 2026-09-22 去学校电脑继续。本次只更新交接文档，不改应用功能。
没有未完成的已授权代码任务或待合并的代理改动。最近在讨论 My Data 进入详情后的
stress-strain 曲线、CSV 下载，以及 ε_eq 和 ε_p,eq 的含义；具体结论和边界见下文。
CSV 下载已暂缓，曲线公式没有修改。下一步等用户明确指示，不要自行实施讨论中的想法。

之前给 Ronak 的 Upload Data 说明已整理成英文和中文，包含上传流程及下面的全部额度。
这里只提供了供用户复制的草稿，**没有代发 Zulip 消息**。

**代码已推送不代表 Render 已部署完成；线上部署及线上功能尚未确认。**
试用站点：[FAIR Materials Data Platform](https://fair-materials-data-hub.onrender.com/)。

## 学校电脑恢复步骤

1. 在学校电脑自己的仓库目录先运行 `git status --short --branch` 和
   `git log -10 --oneline`。如果有未提交内容，先检查并保留，不要覆盖、重置或强推。
2. 工作区干净且位于 `main` 时运行 `git pull --ff-only`。若本地分支与远端分叉，
   先查差异，不要用 `reset --hard` 或强推解决。拉取后重新阅读本文件、
   [AGENTS.md](AGENTS.md) 和 [README.md](README.md) 的 Upload and Storage Limits、
   Current Scope、My Data、Search、Local Setup、Verification。
3. 不要假定学校电脑保留了聊天记录、这台电脑的路径、登录状态或凭据。
   若有 PyCharm 环境工具，每次运行 Python 前用它确认学校电脑的项目解释器。
   README 推荐 Python 3.12；9 月 21 日在 Windows 实际测试用的是 Python 3.13.9，
   项目目录为 `D:\Projects\database-manager-ui`，解释器在该目录的 `.venv\Scripts\python.exe`。
   这些路径只是本机记录，不要照搬到学校电脑。
4. 本地开发使用 `DEBUG=True` 和 SQLite。已有 `.env` 不覆盖；若缺少配置，
   按 README 从 `env.sample` 建立本地配置，不借用生产数据库凭据。
   依赖或数据库落后时，按 README 安装 `requirements.txt` 并运行迁移。
   `c8505a1` 没有新增依赖或迁移，但更早的 identifier 功能有迁移 `0010`。
   本机原有环境仍是 Django 4.2.9，已按现有 requirements 升级到 Django 5.2.16 后完成最终验证；
   学校电脑也要检查实际安装版本，不能只看依赖文件。
5. `.env`、本地数据库、虚拟环境、上传数据和临时测试报告没有通过 Git 同步。
   学校电脑、这台电脑和线上站点的账户、数据各自独立。
6. 用户偏好中文简短直接沟通，UI、代码注释和 docstring 保持英文。
   明确的小修改直接完成、验证、检查 diff，然后 `git add .`、commit、push；
   不反复索要常规确认，不提交凭据或无关修改。不要把推送状态说成部署状态。
   **提问、讨论和“先看看”不等于授权改代码。** 用户明确反对尚未说明需求就开始修改；
   已经明确要求做的改动再直接完成，不要把这个偏好解释为每一步都要审批。

## 最近完成的提交

| 提交 | 内容 |
| --- | --- |
| `c8505a1` | My Data 增加 Access、Software、Phase、Creator 下拉筛选及 11 项回归测试 |
| `463b555` | 上一台电脑的 Upload 和 Search 交接文档 |
| `9a5228f` | 正式应用额度；上传释放前一文件的解析数据；搜索逐记录扫描并保留摘要 |
| `f0f67e5` | 每个文件右侧显示真实处理进度，逐文件转圈和确认结果 |
| `6ae2c72` | 放大上传白框和蓝色区域，让最多五个文件排列更宽松 |
| `0f7f8fb` | 有错的文件整份拒绝，继续检查其他文件和所有可读 object |
| `0577e4e` | 上传错误按文件、object、问题类别分组并给出对应指导 |
| `6cac927` | 自动 identifier 提示使用 will be |
| `effa93e` | 删除文本 Data field filters 下冗余的匹配提示 |
| `8fde8c8` | Clear 清空条件，但保留高级搜索展开或收起状态 |
| `e483778` | 普通搜索与 Common filters 统一为完整单词全部匹配 |
| `84d97bf` | Live Data Objects 改为每 10 秒刷新 |
| `c04cd27` / `05148cc` | 简化文本匹配；Grain number 和明确的数值比较名称 |
| `18849c7` | 搜索结果直接显示访问类型、总数，Public 排在 Private 前 |

旧提交 `550ed5f` 的“遇到错误文件就停止后续文件”已经被取代，不能恢复为最终需求。

## My Data 本轮完成内容

用户希望管理自己上传的数据，倾向直观的下拉框，不要搜索框；没有采用 Upload time。
用户确认了 Access、Software、Phase、Creator 四项后才实施。Search 仍用于搜索和浏览可访问数据。

- 列表及选项仅来自当前用户自己的记录，最新上传优先；别人的公开或分享记录都不进入这里。
  Access 为 All、Public、Private；Private 包含用户自己已分享给别人的私有记录。
  Creator 指 JSON 中的创建者，不是上传者。
- Software、Phase、Creator 支持文本、列表和带名称的字典；去除首尾空白、忽略大小写，
  按完整名称精确匹配。各条件之间取 AND；同一个 object 只计数一次。
  Phase 名称优先于编号，例如有 `name: Iron` 和 `phase_identifier: 7` 时显示 Iron。
- 下拉选项后的数字按其他已选条件计算；零结果选项禁用，但保留当前选中值。
  失效或未知 URL 条件保留为零结果，不能悄悄扩大范围。刷新和书签保留 GET 条件。
- 选择后自动筛选，Clear 清空全部条件；没有 JavaScript 时提供 Filter 按钮。
  空账户和无匹配结果仍显示筛选区。桌面四列、平板两列、小屏一列。
- 原有选择、批量 JSON 下载、删除保留；全选只选当前显示的记录，后端权限检查不变。
  `N of M data objects` 中 N 是当前匹配数，M 是用户自己的总记录数；
  `2 of 2 data objects` 即总共两条，当前显示两条。这里数的是解包后的 object，不是文件。
  用户询问过这句话的含义，但没有要求修改文案。

关键文件：[my_data_filters.py](apps/pages/my_data_filters.py)、
[test_my_data_filters.py](apps/pages/test_my_data_filters.py)、
[views.py](apps/pages/views.py) 的 `json_data_list_view`、
[data_list.html](templates/pages/data_list.html)。README 和 AGENTS 已同步规则。

### 9 月 21 日验证记录

以下为 `c8505a1` 提交前实际完成的验证；本次仅写 HANDOFF，不重跑应用测试。

- **584 项 Django 测试全部通过**，包含新增的 11 项 My Data 测试。
  命令为 `manage.py test --parallel 4 --verbosity 1`，使用 `DEBUG=True` 和测试 SQLite。
- **73 项 JavaScript 测试全部通过，0 项跳过**，使用真实 Chrome、Node 24.19.0。
  命令为 `node --test tests/js/*.test.cjs`。
- `manage.py check` 无问题，`manage.py makemigrations --check --dry-run` 无变化，
  `python -m pip check` 无依赖冲突，`git diff --check` 通过。
- 独立临时 SQLite 和真实浏览器验证了自动筛选、组合条件、刷新、Clear、权限隔离、
  当前结果全选和 JSON 下载、空账户、无匹配、无 JavaScript 回退。
  在 1440、390、320 像素宽度检查长名称和长 identifier，未见横向溢出或运行时错误。
- 审查发现 Phase 编号优先于名称的问题，先用回归测试重现，再修正并完成上述全量测试。

Windows 全量 Django 测试中的部署构建测试需要 Bash。本机第一次运行因 Bash 不在 PATH 失败；
在当前进程 PATH 前加入 `D:\Software\Git\bin` 和 `D:\Software\Git\usr\bin` 后全部通过，
没有跳过或削弱测试。Chrome 路径为 `C:\Program Files\Google\Chrome\Application\chrome.exe`，
通过 `CHROMIUM_BIN` 指定。学校电脑应按实际安装位置配置。

本轮临时浏览器脚本和截图在 Git 忽略的 `.gstack/my-data-verification/`，不会同步到学校。
临时服务曾使用 `127.0.0.1:8001`，已停止；不要复用临时登录会话。
本轮未修改本地 `.env` 和日常数据库，未使用生产数据库凭据。

## 详情页曲线讨论进度

**本节记录解释和核对结果，没有新增功能，也没有授权修改科学公式。**
用户不熟悉材料学，希望用白话解释；用户把 epsilon 口述成“epsel blabla”。
截图最后两个选项是 ε_eq 和 ε_p,eq，不应仅根据口述误判为两个 elastic strain 字段。

| 页面符号 | 代码变量或来源 | 已解释的含义 |
| --- | --- | --- |
| ε_11、ε_22、ε_33 | `strain_11` 等，来自 `total_strain` | 各方向的总拉伸或压缩应变 |
| ε_12、ε_13、ε_23 | `strain_12` 等 | 各平面的剪切变形，可用正方形变成平行四边形解释 |
| ε_p,11 等 | `plastic_strain_11` 等，来自 `plastic_strain` | 对应方向或平面的塑性应变 |
| ε_eq | `equivalent_total_strain` | 将多个总应变分量合成为一个等效量 |
| ε_p,eq | `equivalent_plastic_strain` | 将多个塑性应变分量合成为一个等效量 |
| σ_11 等、σ_eq | `stress_11` 等、`equivalent_stress` | 方向应力、等效应力；不是应变 |

ε 表示应变，σ 表示应力，p 表示 plastic，eq 表示 equivalent。1、2、3 是模型坐标方向，
通常可理解为 X、Y、Z，但需以数据的坐标约定为准；等效量不是简单平均。
白话例子：原长 100 mm，拉到 101 mm，卸载后剩 100.8 mm，则加载时伸长 1 mm，
其中 0.2 mm 可恢复、0.8 mm 留下。这个例子只用于解释单轴总变形与塑性变形；
不能据此断言多轴的各个等效标量都满足简单相加关系。

用户记得 Ronak 说这两条曲线“很接近，但不是完全一样”。合理的解释是总应变包含可恢复部分，
塑性应变反映留下的变形；塑性变形占主导时，两者可以接近。**没有会议原文，不能替 Ronak 确认原话，
也不能保证任意数据、任意加载路径下两条曲线都接近。**

已只读核对 [views.py](apps/pages/views.py) 中 `_get_plot_display_label`、
`_calculate_equivalent_strain` 和 `_extract_equivalent_plot_variables`：
ε_eq 和 ε_p,eq 分别由 `total_strain`、`plastic_strain` 的六个分量计算，没有使用同一份应变数组。
公式先去掉三个正应变分量的平均值，再计算偏应变张量的范数。
[data_detail.html](templates/pages/data_detail.html) 中 X 轴选择应变、Y 轴选择应力；
等效应变选项对应等效应力 σ_eq，比较这两个选项通常是更换 X 数据。

用本机示例 `example_json_files/a46fde6c1_public.json` 只读计算，
两组各 250 点，并不相同；最后一点 ε_eq 为 `0.1825263887995733`，
ε_p,eq 为 `0.17782413535290745`。这支持该示例的两者接近且不相同，
**不代表已核对用户截图对应的线上记录**。该示例没有纳入 Git，学校电脑不一定有副本。

定义边界：当前塑性等效量由各时刻塑性应变张量计算，不是沿加载历史积分的累计量。
不要直接把它等同于 Abaqus 的累计 PEEQ；反向、循环或非比例加载时尤其需要区分。
如果之后要求核实公式，先确认数据来源、应变度量、剪切分量约定和加载路径，再决定是否修改。
本轮没有确认数据存在剪切约定错误，也没有判定当前实现普遍错误。
可参考 [Abaqus 输出变量定义](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEOUTRefMap/simaout-c-std-elementintegrationpointvariables.htm)
以及 [DAMASK mechanics 实现](https://damask-multiphysics.org/_modules/damask/mechanics.html)。

### CSV 下载暂缓

用户记得教授可能要求在 stress-strain 曲线旁增加 CSV 下载，但会议 TXT 不在手边，
随后明确说“咱先弄别的”。只解释过曲线的数值点可以导出 CSV，供 Excel、Origin 等读取。
**本轮没有新增 CSV 按钮或导出逻辑，也没有确定导出当前坐标轴、全部分量或其他细节。**
等用户重新提出或提供会议内容后再推进，不要把这条讨论当成待自动执行的开发任务。

## Upload Data 最终规则

- 每个 JSON 文件可含一个 object、object 数组，或带顶层 `data` 数组的包装对象。
  每个有效 object 保存为独立 `JSONData`，但**整个文件是一个原子保存单位**。
- 只要求 24 个必填顶层字段，包含 `phase`，不是 `material`；允许额外字段。
  不做未经请求的深层科学 schema 校验，仍检查 identifier、共享和资源限制。
- 检查全部文件及其全部可读 object，收集独立错误。一个 object 有问题则整份文件
  不保存任何对象或通知，但仍检查这个文件其余 object，并继续后续文件。
  JSON 语法错误可能导致文件无法解析，这时只能报告文件错误。
- 文件数、合计字节数和整批原始 object 数在任何保存前检查；这些全局限制超标则
  整次提交拒绝。单文件大小、内容错误属于该文件，不妨碍其他合规文件继续。
  每个文件保存时仍在事务内复查 identifier 和当前用户配额。
- 错误按文件顺序、object 原始顺序、问题类别列出；缺少字段、空字段、identifier、
  共享等分别归类，每个问题单独列明，并给出该类别的指导。上传文字全部转义。
  用 Title 和合法自带 Identifier 识别 object，文件序号辅助定位或作为回退。
- 文件列表右侧显示 Waiting → Processing（转圈）→ Uploaded / Failed。
  同时只处理一个文件；不人为延迟动画，小文件太快看不到转圈是正常的。
  所有详细结果和错误在全部处理完成后统一显示在表单下方。
- 浏览器一次发送整个 multipart 请求，保留全批预检。服务端用 NDJSON 依次发送
  `file_start`、事务完成后的 `file_result`，最后发送 `complete`。
  不支持流读取的浏览器保留普通表单回退。
- 处理中防止重复提交，不禁用文件输入导致漏传。断线保留已确认结果，其他文件标为
  Unconfirmed，不自动重试。用户应先检查 My Data；完成后需重新选文件才能再次上传。
- 容量优化：预检逐文件解析、计数并释放，处理时重新读取当前文件；不再同时保留
  整批解析树。深度检查使用迭代器栈，避免为大型数值数组的每个值额外分配工作项。

### Identifier

- 页面短提示：`An identifier will be assigned automatically if missing.`
- 缺失、null 或空白时，从 24 个必填字段生成 8 位小写 base36 identifier；
  与不同内容冲突时逐位延长。合法自带文本 ID 保留，格式错误或首尾空白要报告。
- 内部保留完整 SHA-256 指纹，识别扩展后的重复内容，并兼容旧 64 位 identifier。
  可选字段不参与指纹，已有 identifier 不自动重算，重复记录不覆盖。
- 全库和上传批次都检查重复；最终分配与配额记账在事务锁内完成。
  失败文件不保留 identifier 或配额。自带不同 ID 不代表自动按完整内容去重。

### 当前额度

数值定义在 [config/settings.py](config/settings.py)，沿用已有 `PILOT_` 设置名。
不要因为变量名带 PILOT 就还原为旧的 10 MiB、25 MiB、100 objects、50 MiB。

| 项目 | 当前限制 |
| --- | --- |
| 每次文件数 | 5 |
| 单文件大小 | 100 MiB |
| 每次文件合计大小 | 250 MiB |
| 每次所有文件合计 object 数 | 1,000 |
| 每用户已存储 JSON | 5 GiB |
| JSON 嵌套深度 | 100 层，未改变 |
| 每用户上传频率 | 每小时窗口 20 次提交，失败也计数，未改变 |

存储配额按紧凑 UTF-8 JSON 字节计量，不是原始文件大小或每月流量；删除会释放额度。
这些是用户确认的正式平台初始**应用额度**，并不证明当前试用托管已具备对应容量。
README 的 Current Pilot Hosting 保留当前试用部署说明。尚无申请扩容入口。

关键文件：[views.py](apps/pages/views.py)、[upload_services.py](apps/pages/upload_services.py)、
[helpers.py](apps/dyn_api/helpers.py)、[upload.html](templates/pages/upload.html)、
[upload.js](static/assets/js/upload.js)。

## Search 最终规则

- 普通搜索、Common filters、新文本 Data field filters 统一：输入的所有完整单词
  必须出现，顺序和大小写无关。`isotropic` 不匹配 `anisotropic`。
  新文本条件隐藏 Match，下方冗余提示已删除；旧 Contains words / Equals text
  保存链接仍保留原有语义，不要因为兼容代码存在就说新搜索还在做子串匹配。
- 所有条件匹配同一个可访问 data object；不同条件仍可命中其中不同相或数组条目。
  普通搜索范围包含本人、公开和明确分享给本人的数据，并按所选 Access 缩小范围。
  四个 Access 选项是 Public、My Data、My Private、Shared with Me。
- Common filters 顺序：Identifier、Access、Owner (uploaded by)、Creator、Software、
  Phase、Title。上下 Search 提交同一个组合表单；关键词可以不填。
  Clear 清空全部条件但保留高级面板展开状态。
- 保留 12 个科学参数预设、按类型匹配和明确别名；字段键名归一化匹配并递归查找。
  `grain_count` 显示为 Grain number，`grain_number` 是显式计数别名。
  数值包含 Greater than or equal to / Less than or equal to 和包含端点的 Between。
- Loading type/mode 限定 `mechanical_BC`；RVE continuity 只接受真正 JSON 布尔；
  温度以 K 查询，按最近上级单位元数据换算。缺失或未知单位不匹配。
  旧精确路径、Ronak token 和退役参数的活动书签保持兼容。
  详细规则见 AGENTS / README；无效条件报错，不能扩大搜索范围。
- 搜索结果不展开就显示 Public / Private，并显示匹配总数；Public 优先，各组内最新优先。
  多个选中的可访问 object 可统一导出到一个 JSON 文件。
- Live Data Objects 是独立公开动态列表：只显示 `access_type="all"`，排除全部 private，
  包括自己的和分享给自己的；页面可见时每 10 秒刷新。显示最新 20 条，
  总数是所有公开 object 的数量；每行不再重复 Public 标识，保持紧凑滚动。
- public 指其他已登录平台用户可见，不是匿名可见。搜索与详情权限必须一致。
- 搜索已逐记录读取，并只保留结果显示摘要和 identifier；数据库原文不变。
  仍是应用层扫描，不是大数据索引搜索。My Data、Shared、Live 的原始 JSON 加载方式
  未在 `9a5228f` 容量修改中调整；本轮 My Data 筛选也不代表全站大数据性能已验证。

关键文件：[advanced_search.py](apps/pages/advanced_search.py)、[views.py](apps/pages/views.py)、
[search.html](templates/pages/search.html)、[advanced-search.js](static/assets/js/advanced-search.js)。

## 历史 Upload 和 Search 验证及容量限制

下面是上一台电脑在 `9a5228f` 提交前完成、由 9 月 19 日交接保留的验证。
本轮 My Data 的最新 584 项 Django 和 73 项 JavaScript 验证见上文；本轮没有重做大文件容量实测。

- 573 项 Django 测试通过；73 项 JavaScript 测试通过，包含真实 Chromium，0 项跳过。
- `manage.py check` 通过；`manage.py makemigrations --check --dry-run` 无变化。
- 新增默认额度边界测试：5/6 文件、100 MiB 及超 1 字节、250 MiB 及超 1 字节、
  1,000/1,001 objects、5 GiB 及超额拒绝；还覆盖上传解析释放、临时文件生命周期、
  数组深度遍历内存和搜索结果原始 JSON 释放。
- 单元测试的文件字节边界用 metadata、5 GiB 配额用记账边界，不实际生成 5 GiB 数据。
  另做了下面独立的真实 HTTP multipart 大文件测试，不要混淆两种验证。
- 较早的上传布局与逐文件进度在 1440、390、320 像素宽度验过；本次额度修改未改布局。

当时的大文件测试使用上一台电脑的 Python 3.10.12、`DEBUG=True`、独立临时 SQLite、单个 WSGI
进程。校验了流事件顺序、Uploaded 状态、最终对象数及实际存储字节；临时服务已关闭。

| 输入 | 服务端耗时 | 进程峰值 RSS |
| --- | --- | --- |
| 100 MiB 单文件，长文本 | 2.69 秒 | 1,166 MiB |
| 250 MiB 批次，100 + 100 + 50 MiB | 6.01 秒 | 1,266 MiB |
| 20 MiB 数值数组 | 4.15 秒 | 636 MiB |
| 100 MiB 数值数组 | 16.04 秒 | 2,768 MiB，约 2.7 GiB |

这些是当时那台电脑的观测值，不是线上承诺；正式服务器需配套内存、临时磁盘和数据库容量。
尚未做完整 5 GiB 数据库扫描、真实 PostgreSQL 多连接并发或生产负载验证。
Render 是否完成部署仍未确认，参见 [部署说明](docs/deployment/public-pilot.md)。

相关测试：[test_upload_limits.py](apps/pages/test_upload_limits.py)、
[test_upload_buffering.py](apps/pages/test_upload_buffering.py)、
[test_upload_progress.py](apps/pages/test_upload_progress.py)、
[test_upload_file_atomicity.py](apps/pages/test_upload_file_atomicity.py)、
[test_upload_feedback.py](apps/pages/test_upload_feedback.py)、
[test_upload_identifiers.py](apps/pages/test_upload_identifiers.py)、
[test_search_capacity.py](apps/pages/test_search_capacity.py)、
[upload.test.cjs](tests/js/upload.test.cjs)。

原始测试日志和容量脚本只留在上一台电脑的 `/tmp`，没有提交，不会随 Git 同步到学校电脑；
交接所需结果已在上面记录。需要复测时重新生成合成数据，不使用用户私有数据。

学校电脑后续改后端时，用确认过的本机解释器和 `DEBUG=True` 运行相关 Django 测试；
需要全量验证时按 README 运行 `manage.py test`、`manage.py check`、
`manage.py makemigrations --check --dry-run`。前端验证用
`node --test tests/js/*.test.cjs`；Node 要有全局 WebSocket，Chromium 可通过
`CHROMIUM_BIN` 指定。浏览器测试跳过不能算验证通过。

## 下一步

1. 学校电脑安全拉取最新 main，确认本地环境，先读本交接和 AGENTS，再按用户下一条指示继续。
2. 最近讨论集中在 My Data 和详情页。筛选已完成；CSV 暂缓；两个等效应变选项已解释并用示例核对，
   尚无曲线公式、命名或下载功能的进一步修改指令。
3. 若用户提供会议 TXT，可核对教授对 CSV 的要求和 Ronak 对曲线的原话，再讨论具体修改。
4. 若用户要验收线上行为，先确认 Render 实际部署的提交，再做线上检查。
5. 当前没有待完成的已授权功能修改；扩容入口、索引搜索、基础设施升级、AI 和知识图谱
   都不应未经请求直接展开。
