---
status: completed
branch: main
timestamp: 2026-09-24T17:44:24+02:00
code_commit: 0b2adcf4006ccd14aa929b1e571b5d0f98d47485
files_modified:
  - HANDOFF.md
---

# Project handoff

## 当前状态

最新功能提交是 `0b2adcf`：应力、应变 CSV 下载，多个对象各一份 CSV 打包为 ZIP。
9 月 23—24 日还完成了详情页字段排序／折叠、Ronak 最新字段适配、边界条件表格布局、
cube 标签间距和字号、曲线符号斜体、坐标数字放大。更早的上传和 ORCID 功能继续保留。
写本交接前，工作区干净，已用 `git ls-remote origin refs/heads/main` 确认
GitHub 的 `main` 也是 `0b2adcf4006ccd14aa929b1e571b5d0f98d47485`。
本交接会另行提交并推送，所以拉取后 HEAD 应是包含本文件更新的文档提交。

用户准备回家在笔记本继续，**先读本交接，再等用户接着提供 Ronak 的反馈，逐项推进**。
本次只更新交接文档，不改应用功能。当前已授权的改动均已完成，没有待合并的代理改动。
Ronak 的“100 个对象的 JSON 上传两次都没有结果”仍未定位：用户明确要求先略过，
待向 Ronak 要到原始 JSON 后再查，不能将这次进度和后台处理改动说成已修复该问题。
CSV 已由用户明确说“做吧，csv不是excel”授权并完成；科学计算公式未修改。

此前已确认的上传 UI 要求：**限制名称、冒号、数值；每项一行，桌面两列；不要在下面恢复大段解释。**
保持界面英文，中文简短沟通。用户不喜欢为了常规小修改反复确认。

之前给 Ronak 的 Upload Data 说明已整理成英文和中文，包含上传流程及下面的全部额度。
这里只提供了供用户复制的草稿，**没有代发 Zulip 消息**。

**代码已推送不代表 Render 已部署完成；线上部署及线上功能尚未确认。**
试用站点：[FAIR Materials Data Platform](https://fair-materials-data-hub.onrender.com/)。

## 新聊天／另一台电脑恢复步骤

1. 在当前电脑自己的仓库目录先运行 `git status --short --branch` 和
   `git log -10 --oneline`。如果有未提交内容，先检查并保留，不要覆盖、重置或强推。
2. 工作区干净且位于 `main` 时运行 `git pull --ff-only`。若本地分支与远端分叉，
   先查差异，不要用 `reset --hard` 或强推解决。拉取后重新阅读本文件、
   [AGENTS.md](AGENTS.md) 和 [README.md](README.md) 的 Upload and Storage Limits、
   Current Scope、Data Object Details、My Data、Search、Local Setup、Verification。
3. 不要假定新聊天或另一台电脑保留了聊天记录、路径、登录状态或凭据。
   若有 PyCharm 环境工具，每次运行 Python 前用它确认项目解释器。
   9 月 24 日工作目录为 `/home/users/xuejungs/Projects/database-manager-ui`，
   实际测试解释器是本项目 `.venv/bin/python`，Python 3.10.12；Render 配置为 Python 3.12.13。
   这些只是当前环境记录，换电脑应重新确认，不能直接照搬路径。
4. 本地开发使用 `DEBUG=True` 和 SQLite。已有 `.env` 不覆盖；若缺少配置，
   按 README 从 `env.sample` 建立本地配置，不借用生产数据库凭据。
   依赖或数据库落后时，按 README 安装 `requirements.txt` 并运行迁移。
   9 月 24 日详情页和 CSV 功能没有新增依赖或迁移；9 月 23 日新增过迁移
   `0012_accountprofile_research_details` 和 `0013_upload_jobs`。
   另一台电脑仍须运行未应用的迁移。
   本地 `runserver` 默认走原有 NDJSON 上传；测试后台上传要按部署文档启动 Gunicorn，
   由它启动上传处理进程，不要只启动 `runserver` 就判断后台功能失效。
5. `.env`、本地数据库、虚拟环境、上传数据和临时测试报告没有通过 Git 同步。
   学校电脑、这台电脑和线上站点的账户、数据各自独立。
   用户反复提供的 `example_json_files/a46fde6c.json` 及 `a46fde6c1_public.json`
   属于被 Git 忽略的本地样例；笔记本没有时需另行复制，不能认为拉取仓库就会出现。
   原样例路径不可读而跳过，表示那次测试没有读取成功，不代表样例已验证。
6. 用户偏好中文简短直接沟通，UI、代码注释和 docstring 保持英文。
   明确的小修改直接完成、验证、检查 diff，然后 `git add .`、commit、push；
   不反复索要常规确认，不提交凭据或无关修改。不要把推送状态说成部署状态。
   **提问、讨论和“先看看”不等于授权改代码。** 用户明确反对尚未说明需求就开始修改；
   已经明确要求做的改动再直接完成，不要把这个偏好解释为每一步都要审批。

## 最近完成的提交

| 提交 | 内容 |
| --- | --- |
| `0b2adcf` | 详情页当前 X/Y、全部、自选列 CSV；列表多对象 ZIP；权限及精度测试 |
| `c9bcf01` | 曲线坐标数字 15px、科学计数指数 11px，匹配测量和留白 |
| `67809ac` / `3a598a1` | 下拉菜单、提示、图例、坐标标题和 PNG 的 σ／ε 斜体；下标直立 |
| `93d6570` / `423140f` / `95da7d3` | 顶点标签稍外移、X 字与箭头拉开、放大顶点和参考轴文字 |
| `0cf08a5` | 多个 loaded 详情可同时展开，三列充分利用表格宽度 |
| `c89aaf0` | 边界载荷显示四舍五入两位小数；Loading Type / Mode 标题 |
| `0bbb951` / `2ced93f` | schema 头字段及各层 properties 相对顺序；隐藏已绘图的根字段 |
| `a7ee54a` / `0da262d` | 采用当前 MiMeDat 的 phase_name、等效量与边界载荷结构 |
| `82e6e46` | 按真实 JSON 结构折叠，不再显示 Additional 分组 |
| `661f4a8` | 上传限制精简为两列“名称：数值”，删除解释段落 |
| `22a304b` | 真实文件传输和对象校验进度、后台上传任务、站内跨页面继续处理、页面显示限制 |
| `e3a0716` | ORCID 可选研究资料补全和 Account Settings 编辑字段 |
| `75e3b82` | 从公开 ORCID 资料补全空的 institution、email |
| `977d009` / `a3583b7` | 引导文案、强调和动效，以及更易读的字号与配色 |
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
旧提交 `2803c41` 的“只按 mandatory 排序、其余放 Additional”也已被后续需求取代。

## 9 月 24 日详情页最终约定

### 字段顺序与折叠

- Ronak 参考仓库为 [MiMeDat](https://github.com/Ronakshoghi/MiMeDat)；参考文件是
  `microstructure_sensitive_mechanical_metadata_schema.json` 和 `metadata_template.py`。
  `Dict_Test` 是包含必要及可选项的示例；schema 是结构规则。展示顺序和上传验证是两件事。
- **最终展示不再采用“必要字段在前、可选字段放 Additional”。** 用户提供的字段，凡当前
  schema 对应层级定义了，就按其 `properties` 相对顺序展示，必要、可选都包括。
  未定义字段放同一父对象最后，保留其自身顺序；不移动到别的父对象，不添加空占位。
- 顶层用户提供的 `$schema`、`$id`、`version`、`type`、`description` 依次在前，随后
  `identifier` 等。只展示上传的值，不从 schema 文档复制值；description 不重复显示。
- 顶层 `stress`、`total_strain`、`plastic_strain`、`mechanical_BC` 不在元数据列表重复展示，
  由下方图和边界条件表使用。完整 JSON 下载仍保留这些字段。
- 按真实对象／对象数组结构折叠，包括只有一个子项的对象；不按“子项多于两个”判定。
  `creator_affiliation`、`creator_institute` 等独立字段不因前缀相同而合并。
  没有 Additional 分组；长数组仍有 Show values。未知字段也可展示字符串、数值、列表等。
- 展示使用本地排序表，不联网获取用户上传的 `$schema` 地址，不在详情页重新做嵌套验证。
  **上传仍只校验必要顶层字段**；没有因为本轮展示讨论启用所有层级的 required 校验。
- 用户已删除平台此前上传的旧数据，明确要求按 Ronak 当前命名走；不要主动恢复旧显示名称。
  phase 使用 `phase_name`；总等效应变字段为 `total_strain.equivalent_strain`。
- 曾反馈 title 的 Stress 变为 tress；当时本地样例自身的首字母问题已处理，不是字段排序应删除字符。
  若再出现，分别核对源文件、存储内容、DOM，不能推定当前上传逻辑仍在截断标题。

关键文件：[detail_metadata.py](apps/pages/detail_metadata.py)、
[views.py](apps/pages/views.py)、[data_detail.html](templates/pages/data_detail.html)、
[test_detail_metadata.py](apps/pages/test_detail_metadata.py)、
[test_plot_schema.py](apps/pages/test_plot_schema.py)、[test_bc_schema.py](apps/pages/test_bc_schema.py)。

### Mechanical Boundary Condition Cube 和载荷表

- 表头保持 `Target`、`Constraints`、`Loading Type / Mode`。用户提过 Vortex，未采用；
  target 可能是顶点组合或整个 cube，Vortex 不是顶点的英文。
- 载荷显示按 ROUND_HALF_UP 四舍五入两位小数，step 保持整数；不改原值或导出精度。
- X/Y/Z 标签保持同一行。各方向的 loaded 详情可同时展开，正常文档流增加该行高度，
  其他方向标签仍停在顶部；不要恢复一次只能开一个或浮层互相遮盖的版本。
- 三列表宽约 14% / 62% / 24%；cube 与表格采用 2:3 比例和最小宽度约束。
- 顶点标签约 14 CSS px，参考轴字 17px；顶点标签向外偏移从 0.22 调到 0.28。
  X 标签已额外拉开与箭头的距离，不要把所有标签推得很远。
- 顶点命名严格按二进制坐标：Vxyz 的每位 0→-0.5、1→+0.5。V000 的三个相邻点是
  V100、V010、V001，对角点 V111；检查过八个点与边的对应关系。
- 右下角是固定参考坐标系。用户明确说其不跟随旋转没关系，**不要另做动态坐标轴同步**。
- cube 在浏览器用 Three.js 渲染，不是 Node.js。当前按需渲染，空闲不持续重绘；仍有抗锯齿、
  high-performance 提示和最大 1.5 像素比。实测静止 5 秒及拖动停止后无额外 WebGL 渲染，
  4 倍 CPU 降速下可操作。未测用户笔记本断电状态，不能承诺所有硬件都不卡。
  这部分性能核查是只读检查，没有擅自重写渲染器。

cube 实现位于 [mechanical-bc-viewer.js](static/assets/js/mechanical-bc-viewer.js)。

### 曲线字体

- Ronak 要求表示标量的 σ 和 ε 斜体；eq、p,eq、数字下标及单位直立。
  图例、坐标标题、PNG、下拉菜单、tooltip 和原始值摘要均已适配。
  原生 select／纯文本使用数学斜体 Unicode；Canvas 和 HTML 使用对应字体样式。
- 坐标数字从 12px 放大到 15px，科学计数指数从 9px 到 11px，并更新测量和留白。
  CSV 提交同步修正了旧测试中残留的 12px／固定字体字符串断言，没有再改字体功能。

## CSV 导出已完成（0b2adcf）

Ronak 原意是既能选择应力／应变导出，也能一键导出所有可用曲线，并支持选多个 data objects。
用户已明确授权 CSV，**不是 XLSX 或 Excel 多 sheet**。

- 详情页曲线区：`Download X/Y CSV`、`Download All CSV`；展开 `Choose CSV columns`
  可勾选任意多列，有 Select all、Clear 和 Download Selected CSV。原图像按钮明确为 Download PNG。
- My Data：`Download Curves as CSV`；Search 结果：`Export Curves as CSV`。
  选一个对象直接下载 CSV；选多个则每对象一份 CSV，打包 `stress_strain_csv.zip`。
  文件名采用清理后的 identifier／title 加数据库记录 ID，避免同名覆盖。
- 列头是完整字段路径加可用单位；首列 `index` 从 0 开始，是数组索引，不是物理时间。
  每行对应相同数组位置；长度不同的列末尾补空白，不截断、不插值、不重采样。
  保存数值精度，不套用载荷表的两位小数。编码 UTF-8 BOM；CSV 自动处理逗号和引号。
- 复用 `_extract_plot_variables`，与曲线可选的数值序列一致。用户提供的等效量优先，只有缺失
  且分量完整才沿用现有公式计算；显式空等效数组不补算。计算列标记 `(calculated)`。
- 后端逐对象检查 owner／public／explicit share；My Data 导出仅本人记录。
  混入不可访问、已删除或没有数值曲线的对象，整次拒绝并提示，不悄悄跳过。
  批量 POST 保留 CSRF、最多 1,000 个选择；单对象及选列使用 GET。
- 所有内容准备成功后才返回下载；使用 8 MiB 阈值的临时缓冲，大结果落临时文件，ZIP 逐对象写入。
  不把整个批次 JSON 同时留在内存。Python 3.10 的 SpooledTemporaryFile 无 readable 方法，
  已用 codecs writer 避免 TextIOWrapper 不兼容；不要恢复有问题的包装方式。
- 没有改上传验证、科学计算公式、存储数据、原有 JSON 导出或访问规则，没有新增依赖／迁移。

代码：[mechanical_csv.py](apps/pages/mechanical_csv.py)、[views.py](apps/pages/views.py)、
[urls.py](apps/pages/urls.py)、三个页面模板 `data_detail.html`、`data_list.html`、`search.html`。
回归测试：[test_mechanical_csv.py](apps/pages/test_mechanical_csv.py)，共 11 项新测试。

### 本轮验证与恢复运行

- 85 项相关 Django 测试通过：`apps.pages.test_mechanical_csv`、`apps.pages.test_bc_schema`、
  `apps.pages.tests`、`apps.pages.test_my_data_filters`。覆盖精度、单位、不等长、自选列、五对象 ZIP、
  同名文件、访问权限、缺失对象、无曲线、计算标记、Unicode／逗号／公式前缀等。
- `node --test tests/js/*.test.cjs`：98 项通过，0 跳过，包含真实 Chromium。
- 本地真实浏览器 1280／1440 桌面共 52 项检查通过：实际点击当前 X/Y、全部、任意三列下载，
  清空／全选、PNG 保留、My Data 五对象 ZIP 内容、Search 单对象 CSV、长字段名、无曲线页面。
- 此前独立浏览器验证还覆盖符号 90 项、坐标字号 40 项、顶点间距 24 项。
  不把这些历史检查或上传的 652 项检查说成本次 CSV 的全量测试。
- 测试使用隔离 SQLite／合成数据，临时 QA 位于本机 `/tmp/detail-mimedat-qa-YmWzwQ`，
  不在 Git 中。临时服务 127.0.0.1:8897 已停止；笔记本须重建自己的本地环境。
  不复制临时 browser.json 中的登录 cookie，不提交用户样例或数据库。
- 笔记本按 README 配好 DEBUG=True、SQLite 并确认解释器后，可用该解释器执行
  `manage.py test apps.pages.test_mechanical_csv apps.pages.test_bc_schema apps.pages.tests apps.pages.test_my_data_filters --noinput`
  及上述 Node 命令。不要照搬本机临时 qa_settings 路径。
- 本次只更新 HANDOFF，核对文档／Git 状态，不重复执行已完成的应用测试。
  Render 部署和线上下载尚未确认；用户实际样例在笔记本上仍可继续验收。

## Ronak 上传反馈：已做与待查

1. **进度不明确：已改。** 原来 100 个对象只显示第 1/1 个文件；现在分别显示实际传输字节、
   解析／对象校验进度和最终保存结果。只有文件事务提交后才显示已保存，不能把已校验当成已保存。
2. **上传两次没有结果：原因未确认，用户已暂缓。** 等 Ronak 的原始 JSON；截图文件名为
   `Data_Base_Cyclic.json`。截图中的 Waiting 只说明文件已选中，不能证明请求已经发出。
   本地合成的 100 个小对象能够保存，重复提交会报错，但不代表她的实际文件也正常。
   100 个对象低于每次合计 1,000 的限制；JSON 深度指 dict／list 的嵌套层数，不是对象数量。
3. **切换页面丢失上传：已实现站内继续处理和状态恢复。** 传输阶段保留发送页面，
   服务端收齐后由独立进程处理。刷新、关标签页、离站、服务重启有不同边界，见下一节。

以前同步保存路径存在逐对象数据库查询；旧线上日志显示一个 Gunicorn sync worker，
线上延迟或超时是排查方向，**不是已经证明的根因**。后续应结合实际文件、操作和请求结果定位。
不要为了继续工作要求用户重复翻找已无法滚动查看的旧日志。

用户已贴的 Render 日志包含许多 GET 200／304、少量 POST 200／302，没有明确 traceback、
worker timeout 或保存失败原因。当前访问日志格式是 `%(m)s %(s)s %(L)s %(b)s`，
只有方法、状态、耗时和响应字节数，没有 URL；无法据此识别哪个 POST 是上传。
HTTP 200 也不证明对象保存成功，响应中可能含校验错误。

已向用户解释：Render 运行 Django 网站并提供访问入口；Supabase PostgreSQL 保存账户、
对象和权限。当前没有连接可直接读取这两个平台后台的账户工具或凭据，未代查线上数据库。

## 9 月 23 日后台上传实现与边界

- 新增 `UploadJob`、`UploadWorkerInstance` 和迁移 `0013_upload_jobs`。
  `/upload/jobs/` 接收一次 multipart 并返回任务；`/upload/jobs/<uuid>/` 返回任务进度。
  接口仅当前所有者可读，保留 CSRF 校验和 `Cache-Control: no-store`。
- `gunicorn.conf.py` 由现有 Render 启动命令自动加载，使用 `gthread`、4 个线程，
  启动独立 `process_upload_jobs` 子进程并监督其存活；每次启动使用新的实例 UUID。
  没有新增收费服务、第三方依赖或独立 Render worker 服务，也没有修改 `render.yaml` 启动命令。
- 原始文件暂存于非公开的本地目录，服务器生成目录名，目录／文件权限为 0700／0600。
  后台保留全部批次预检、逐文件解析释放、整文件原子保存及最终 identifier／配额复查。
  文件成功结果与对象、通知在同一事务提交；确认成功的文件不会因后续中断被误标失败。
- 客户端以 submission UUID 防重复；任务不自动重试。后台阶段包含 parsing、validating、saving，
  校验进度来自实际完成的对象；失败或中断保留已确认结果，未确认文件标为 Unconfirmed。
- 传输中用临时同源 iframe 显示其他站内页面，保留原始发送文档；回 Upload 恢复原页面。
  收齐后其他页面可查询自己的后台任务。刷新、关标签页或离站发生在收齐之前仍可能中断传输。
  仅符合条件的已登录 HTML 页面允许同源嵌入，登录和管理等页面保留原有防嵌入限制。
- 普通表单回退和原有 `/upload/` NDJSON 路径保留；未启用后台 worker 的本地 `runserver`
  仍可用旧路径。不要移除这条回退，也不要对断线自动重新 POST。
- 当前后台设置：每账户 1 个活动任务，处理期限 30 分钟；每实例暂存预算 512 MiB，
  磁盘保留 64 MiB；worker 租约 90 秒、心跳 5 秒；未完成接收过期 1 小时，结果保留 7 天。
  处理期限在步骤之间和提交前检查，不是对正在运行的 SQL 的硬中断。
- **当前 Render 临时磁盘不持久，服务休眠／重启／重新部署可能中断未完成任务。**
  已提交结果保留，未确认文件不自动重传；不能承诺托管故障后断点续传。
  用户没有授权购买基础设施，这轮沿用现有服务。

关键代码：[upload_jobs.py](apps/pages/upload_jobs.py)、
[process_upload_jobs.py](apps/pages/management/commands/process_upload_jobs.py)、
[gunicorn.conf.py](gunicorn.conf.py)、[upload.js](static/assets/js/upload.js)、
[upload-host.js](static/assets/js/upload-host.js)、
[upload_navigation.py](apps/pages/upload_navigation.py)、
[upload_limits.py](apps/pages/templatetags/upload_limits.py)。
运行说明见 [部署文档](docs/deployment/public-pilot.md)，设计和实施记录见
[设计](docs/superpowers/specs/2026-09-23-upload-continuity-design.md)及
[实施计划](docs/superpowers/plans/2026-09-23-upload-continuity.md)。

### 最新上传限制区

`661f4a8` 仅精简 [upload.html](templates/pages/upload.html) 及相应显示测试，不改后台数值。
两列，每项一行 `Label: value`；没有下面的三段说明文字。数值仍从当前 settings 动态读取。
后台开启时显示 9 项；关闭时显示基础 7 项，不显示活动任务数和处理期限。
不要重新加入存储计算、失败计数、主机容量、切页边界等解释段；详细说明保留在 README。

### 本轮验证证据与局限

- `22a304b`：**652 项 Django 测试通过；98 项 JavaScript 测试通过，0 项跳过**。
  使用 `DEBUG=True`、独立本地 SQLite，Node 24.19.0 和真实 Chromium；迁移漂移检查通过。
- 实际本地 Gunicorn 验证了处理进程启动、停止和重启；真实 HTTP 上传 100 个合成对象，
  检查任务阶段、最终保存数、同 token 幂等、新提交重复数据报错和匿名访问拒绝。
- 真实浏览器在 1280／1440 桌面宽度、限速传输时切换 Search → My Data → Upload，
  上传继续、双击仅一次 POST、新页面恢复结果，未见 JavaScript 异常。
- `661f4a8`：4 项限制显示测试通过；8 组桌面布局检查覆盖 1280／1440、后台开／关、
  空文件列表／5 个长文件名。每项单行，无重叠或横向溢出。
- 本轮没有用 Ronak 原文件复现，没有真实 PostgreSQL 多连接并发测试，也没有线上容量验证。
  SQLite 功能／回滚测试和代码锁顺序审查不能替代 PostgreSQL 并发验证。
- 临时截图、脚本在本机 `/tmp/upload-continuity-*`、`/tmp/upload-limits-compact-qa` 等目录，
  不随 Git 同步；临时测试服务已停止。**Render 实际部署仍未确认。**
- 本次 HANDOFF 更新只核对文档和 Git 状态，不重复运行上述应用测试。

## ORCID 可选资料补全

`75e3b82`、`e3a0716` 已完成并推送。Account Settings 可编辑 Name、Email、Institution、
Department、Position、Website、Research keywords；这些资料可选，Name 与登录 Username 分开。
新增迁移 `0012_accountprofile_research_details`，桌面保持紧凑两列。

- ORCID 登录／连接时最多额外读取 `/person` 和 `/employments` 两个公开部分，
  只填本地空字段，不覆盖用户已填内容。不存在、私有、无效、超长或歧义资料留空可手填。
- Email 必须公开且 ORCID 标记已验证，优先 primary；Name 优先公开 credit name，否则 given／family。
  Website 仅有效 HTTP(S)，按公开链接顺序优先级选择。
- **Research keywords 是 ORCID 本人填写并公开的 Keywords**，去重后导入；不是从论文推断。
- Institution 来自明确的当前公开雇佣机构；已有 institution 时只匹配同机构，
  Department／Position 不混用无关岗位，歧义时不猜。
- 网络请求后在事务中重新检查身份和字段是否仍为空。令牌不持久保存；不按邮箱或姓名合并账户。
  获取可选资料失败不会阻止登录。

关键文件：[orcid_profile.py](apps/pages/orcid_profile.py)、[forms.py](apps/pages/forms.py)、
[models.py](apps/pages/models.py)、[settings.html](templates/accounts/settings.html)。
完成时 233 项相关测试通过，迁移检查通过；1280／1440 桌面空资料和长内容布局已检查。
后续上传的 652 项全量 Django 测试也包含这些回归测试。线上 ORCID 行为尚未验收。

## My Data 已完成内容（9 月 21 日）

用户希望管理自己上传的数据，倾向直观的下拉框，不要搜索框；没有采用 Upload time。
用户确认了 Access、Software、Phase、Creator 四项后才实施。Search 仍用于搜索和浏览可访问数据。

- 列表及选项仅来自当前用户自己的记录，最新上传优先；别人的公开或分享记录都不进入这里。
  Access 为 All、Public、Private；Private 包含用户自己已分享给别人的私有记录。
  Creator 指 JSON 中的创建者，不是上传者。
- Software、Phase、Creator 支持文本、列表和带名称的字典；去除首尾空白、忽略大小写，
  按完整名称精确匹配。各条件之间取 AND；同一个 object 只计数一次。
  Phase 名称优先于编号；9 月 24 日已适配 Ronak 当前的 `phase_name`，例如 Iron。
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

## 早期详情页曲线讨论记录（科学解释保留，展示以 9 月 24 日约定为准）

**本节主要记录早期解释和只读核对；其后已更新字段适配和 CSV，科学公式未修改。**
用户不熟悉材料学，希望用白话解释；用户把 epsilon 口述成“epsel blabla”。
截图最后两个选项是 ε_eq 和 ε_p,eq，不应仅根据口述误判为两个 elastic strain 字段。

| 页面符号 | 代码变量或来源 | 已解释的含义 |
| --- | --- | --- |
| ε_11、ε_22、ε_33 | `strain_11` 等，来自 `total_strain` | 各方向的总拉伸或压缩应变 |
| ε_12、ε_13、ε_23 | `strain_12` 等 | 各平面的剪切变形，可用正方形变成平行四边形解释 |
| ε_p,11 等 | `plastic_strain_11` 等，来自 `plastic_strain` | 对应方向或平面的塑性应变 |
| ε_eq | 当前为 `total_strain.equivalent_strain` | 将多个总应变分量合成为一个等效量 |
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

早期已只读核对 [views.py](apps/pages/views.py) 中 `_get_plot_display_label`、
`_calculate_equivalent_strain` 和 `_extract_equivalent_plot_variables`：
在缺失对应等效量而需要补算时，ε_eq 和 ε_p,eq 分别由 `total_strain`、`plastic_strain`
的六个分量计算，没有使用同一份应变数组；现在明确优先采用用户提供的等效曲线。
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

### CSV 讨论的历史状态

用户记得教授可能要求在 stress-strain 曲线旁增加 CSV 下载，但会议 TXT 不在手边，
随后明确说“咱先弄别的”。只解释过曲线的数值点可以导出 CSV，供 Excel、Origin 等读取。
这是早期的暂缓记录，**已经被 9 月 24 日的明确授权和 `0b2adcf` 实现取代**。
当前 CSV 功能和使用方法见上方“CSV 导出已完成”，不要继续当作未实施任务。

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
- 当前后台路径见上文；以下是仍保留的原有流式回退：一次发送整个 multipart 请求，
  保留全批预检。服务端用 NDJSON 依次发送
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
| 每用户活动后台上传 | 1，仅后台模式 |
| 每次后台处理期限 | 30 分钟，仅后台模式 |

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
9 月 21 日 My Data 验证为 584 项 Django 和 73 项 JavaScript；9 月 23 日的最新验证见上文。
本轮没有重做这些大文件容量实测，不应将历史数值当成新后台路径或线上的性能结果。

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

1. 阅读本交接和 AGENTS，检查当前 Git 状态；换电脑时安全拉取 main 并重新确认本地环境。
2. **用户将在新聊天继续贴 Ronak 试用反馈。** 按新反馈逐项核对当前代码，明确要求修改的直接落实；
   先讨论或询问含义时先回答，不将每条反馈自动扩大成整体重构。
3. 等用户拿到 Ronak 的原始 JSON，再复现“上传两次无结果”；记录实际步骤和响应，
   不用小合成文件成功、HTTP 200 或这次后台改动推定原问题已修复。
4. 如核对线上问题，先确认 Render 部署提交。Git push 成功不证明部署完成，也不证明迁移或线上行为成功。
5. 继续保持限制区两列、每项一行“名称：数值”，不要恢复大段解释。
6. CSV 已完成；笔记本可用实际样例核对下载内容和布局，再根据用户的新反馈修改。
   科学公式未获修改指令；扩容入口、索引搜索、收费基础设施、AI 和知识图谱不应未经请求展开。
   当前没有待完成的已授权代码任务，不要自行启动新功能。
