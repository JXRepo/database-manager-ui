---
status: completed
branch: main
timestamp: 2026-09-19T00:20:11+02:00
code_commit: 9a5228f3188182c916bede2c1ec276eed0766909
files_modified:
  - HANDOFF.md
---

# Project handoff

## 当前状态

Search 和 Upload Data 本轮修改均已完成。最新功能提交是 `9a5228f`。
写本交接前，工作区干净，已用 `git ls-remote origin refs/heads/main` 确认
GitHub 的 `main` 也是 `9a5228f3188182c916bede2c1ec276eed0766909`。
本交接会另行提交并推送，所以拉取后 HEAD 应是包含本文件更新的文档提交。

用户接下来会换到笔记本工作。本次只更新交接文档，不再改应用功能。
没有未完成的代码任务或待合并的代理改动。用户准备继续检查其他页面，
具体从哪一页开始等下一条指示，不要自行开展未来的 AI、知识图谱或平台重构。

给 Ronak 的 Upload Data 说明已整理成英文和中文，包含上传流程及下面的全部额度。
这里只提供了供用户复制的草稿，**没有代发 Zulip 消息**。

**代码已推送不代表 Render 已部署完成；线上部署及线上功能尚未确认。**
试用站点：[FAIR Materials Data Platform](https://fair-materials-data-hub.onrender.com/)。

## 笔记本恢复步骤

1. 在笔记本自己的仓库目录先运行 `git status --short --branch` 和
   `git log -10 --oneline`。如果有未提交内容，先检查并保留，不要覆盖、重置或强推。
2. 工作区干净且位于 `main` 时运行 `git pull --ff-only`。若本地分支与远端分叉，
   先查差异，不要用 `reset --hard` 或强推解决。拉取后重新阅读本文件、
   [AGENTS.md](AGENTS.md) 和 [README.md](README.md) 的 Upload and Storage Limits、
   Current Scope、Search、Local Setup、Verification。
3. 不要假定笔记本保留了聊天记录、这台电脑的路径、登录状态或凭据。
   通过笔记本的 PyCharm 环境工具确认项目解释器，再运行 Python。
   README 推荐 Python 3.12；本轮实际测试使用本机配置的 Python 3.10.12。
4. 本地开发使用 `DEBUG=True` 和 SQLite。已有 `.env` 不覆盖；若缺少配置，
   按 README 从 `env.sample` 建立本地配置，不借用生产数据库凭据。
   依赖或数据库落后时，按 README 安装 `requirements.txt` 并运行迁移。
   `9a5228f` 没有新增依赖或迁移，但更早的 identifier 功能有迁移 `0010`。
5. `.env`、本地数据库、虚拟环境、上传数据和临时测试报告没有通过 Git 同步。
   笔记本、这台电脑和线上站点的账户、数据各自独立。
6. 用户偏好中文简短直接沟通，UI、代码注释和 docstring 保持英文。
   明确的小修改直接完成、验证、检查 diff，然后 `git add .`、commit、push；
   不反复索要常规确认，不提交凭据或无关修改。不要把推送状态说成部署状态。

## 最近完成的提交

| 提交 | 内容 |
| --- | --- |
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
  未在本次容量修改中调整，不能宣称全站的大数据性能都已验证。

关键文件：[advanced_search.py](apps/pages/advanced_search.py)、[views.py](apps/pages/views.py)、
[search.html](templates/pages/search.html)、[advanced-search.js](static/assets/js/advanced-search.js)。

## 验证证据和实际限制

下面是 `9a5228f` 提交前已实际完成的验证；这次仅更新交接文档，没有重新跑全量测试。

- 573 项 Django 测试通过；73 项 JavaScript 测试通过，包含真实 Chromium，0 项跳过。
- `manage.py check` 通过；`manage.py makemigrations --check --dry-run` 无变化。
- 新增默认额度边界测试：5/6 文件、100 MiB 及超 1 字节、250 MiB 及超 1 字节、
  1,000/1,001 objects、5 GiB 及超额拒绝；还覆盖上传解析释放、临时文件生命周期、
  数组深度遍历内存和搜索结果原始 JSON 释放。
- 单元测试的文件字节边界用 metadata、5 GiB 配额用记账边界，不实际生成 5 GiB 数据。
  另做了下面独立的真实 HTTP multipart 大文件测试，不要混淆两种验证。
- 较早的上传布局与逐文件进度在 1440、390、320 像素宽度验过；本次额度修改未改布局。

真实大文件测试使用本机 Python 3.10.12、`DEBUG=True`、独立临时 SQLite、单个 WSGI
进程。校验了流事件顺序、Uploaded 状态、最终对象数及实际存储字节；临时服务已关闭。

| 输入 | 服务端耗时 | 进程峰值 RSS |
| --- | --- | --- |
| 100 MiB 单文件，长文本 | 2.69 秒 | 1,166 MiB |
| 250 MiB 批次，100 + 100 + 50 MiB | 6.01 秒 | 1,266 MiB |
| 20 MiB 数值数组 | 4.15 秒 | 636 MiB |
| 100 MiB 数值数组 | 16.04 秒 | 2,768 MiB，约 2.7 GiB |

这些是本机观测值，不是线上承诺；正式服务器需配套内存、临时磁盘和数据库容量。
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

原始测试日志和容量脚本只留在这台电脑 `/tmp`，没有提交，也不会出现在笔记本；
交接所需结果已在上面记录。需要复测时重新生成合成数据，不使用用户私有数据。

笔记本后续改后端时，用确认过的本机解释器和 `DEBUG=True` 运行相关 Django 测试；
需要全量验证时按 README 运行 `manage.py test`、`manage.py check`、
`manage.py makemigrations --check --dry-run`。前端验证用
`node --test tests/js/*.test.cjs`；Node 要有全局 WebSocket，Chromium 可通过
`CHROMIUM_BIN` 指定。浏览器测试跳过不能算验证通过。

## 下一步

1. 笔记本安全拉取最新 main，确认本地环境后，根据用户下一条消息继续检查其他页面。
2. 若用户要验收线上行为，先确认 Render 实际部署的提交，再做线上检查。
3. 当前没有待完成的功能修改；正式扩容入口、索引搜索和基础设施升级只是已知后续方向，
   不属于本轮已实现功能，也不要未经请求直接展开。
