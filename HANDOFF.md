---
status: ready_for_laptop
branch: main
timestamp: 2026-11-02
application_commit: 6600de65f48cd92416c3050942505c0a9e196b56
next_topic: Continue the Aachen platform walkthrough and review the simplified Charts page
---

# 笔记本交接（2026-11-02）

## 先读这里

- 用户正在准备周一向 Aachen 人员演示平台，希望边操作、边用简单直接的中英文讲解。
  后期可能把数据放进 Aachen 的 Coscine，平台作为访问界面；**尚未实现 Coscine 对接或迁移**。
- 最近一轮是 Charts 精简文字、显示完整名称、合并 Abaqus 写法。功能提交
  **`6600de6` 已推送到 `origin/main`**，本次交接开始时工作区干净。
  本次仅更新交接文档；交接提交本身请以 `git log` 为准。
- `2026-11-02T00:40:56Z`，线上 `charts.css`、`charts.js` 与该版本逐字节一致，
  `/healthz/` 返回 HTTP 200 和 `{"status":"ok"}`。这是当时的线上资源核验，
  不是本次文档交接重新登录生产站做了功能测试，也不是以后每次 push 的部署保证。
- 没有正在实施、尚未收尾的代码任务。下一轮继续陪用户查看效果、回答概念问题，
  按新意见改动；不要把下面的待确认偏好自动变成开发任务。
- 本文取代旧交接作为当前入口。原 3001 行内容已完整保留在
  [历史交接](docs/handoffs/2026-10-29-archive.md)，其中旧方案、旧“下一步”和测试数目
  不代表现状。历史文件内的相对路径按仓库根目录理解。

## 笔记本恢复步骤

1. 进入笔记本上的项目目录，执行 `git status --short`，检查是否有本机未提交的工作。
   工作区干净时再执行：

   ```sh
   git switch main
   git pull --ff-only
   git log -6 --oneline
   ```

   如有本地修改或分叉，先检查并保留；不用强推、reset 或覆盖来解决。
2. 阅读 [AGENTS.md](AGENTS.md)、本文及 [README](README.md) 的 Charts 和 Local Setup。
   有 PyCharm 环境工具时，先解析笔记本自己的项目解释器再运行 Python。
   不照抄本台 Linux 电脑的绝对路径。
3. 本地开发和测试使用 `DEBUG=True`、SQLite；不要使用生产数据库凭据。
   不覆盖已有 `.env`，不提交凭据、数据库、私有上传文件或虚拟环境。
   README 推荐 Python 3.12，与 Render 一致；本次本机验证使用 Python 3.10.12、Django 5.2.16。
4. 线上站点：[FAIR Materials Data Platform](https://fair-materials-data-hub.onrender.com/)。
   查看这轮效果可刷新 Charts；不需要重新上传 JSON。本地账号、数据库和登录态不会随 Git 同步。

## 最近已完成的改动

| 提交 | 内容 | 证据／说明 |
| --- | --- | --- |
| `6600de6` | Charts 文字精简、完整标签、Abaqus 别名分组 | [本轮验证](docs/qa/2026-11-02-charts-cleanup.md) |
| `6662c59` | Constitutive models 完整换行显示 | [模型名称验证](docs/qa/2026-11-01-charts-model-labels.md)，随后由本轮继续精简 |
| `151333e` | Charts 曲线可用性检查提速 | [性能记录](docs/qa/2026-11-01-charts-performance.md) |
| `352f5a9` | 方向小写、面大写，例如 `xY` | [边界面板验证](docs/qa/2026-11-01-tensor-panel-cleanup.md) |
| `3eb1e47` | 删除张量面板底部说明和 Load details | 同上；原生回退详情保留 |
| `c476e39` | 搜索减少逐对象分享查询和重复 JSON 处理 | [搜索性能记录](docs/qa/2026-11-01-search-performance.md) |
| `ceb307a` | Forgot Password 邮件重置流程 | [实现及上线记录](docs/superpowers/plans/2026-11-01-password-reset.md) |
| `95580bd` | 直接访问 logout 不再报 HTTP 405 | 普通登出仍通过 POST；直接访问显示确认页 |

### Charts 当前行为

- 保留八张卡：Phase、Stress–strain coverage、Constitutive models、Loading types & modes、
  Temperature、Grain number、Texture types、Software。顶部四项总览不变。
- 删除卡片右上角重复的 With data / Total、coverage 的解释句、loading 的说明和颜色刻度、
  grain 的两段解释、texture 的 Larger circles 说明。标题悬停或键盘聚焦仍可读统计口径和
  分母；没有 JavaScript 时保留原生 title 和 SVG 图表。
- Phase、模型、Texture、Software 名称完整换行，展开的更多分类也一样；非常长的名称
  在有高度限制的图表区域内滚动，不再用省略号隐藏这些名称。
- Phase 图上只显示数量，百分比移到悬停。**材料名称本身的括号说明仍保留。**
- 模型保留具体名称，用 Elastic / Plastic 颜色图例区分；去掉每个名称后重复添加的
  `(Elastic)` / `(Plastic)`，悬停仍显示所属类别。
- Loading 的 Mode 位于列下方，与其他横轴一致；格子保留准确数量，取消单独的 0–最大值渐变条。
- Grain number 保留 Median 和 Min–max，统计方法未改；箱体、四分位数和每相观测数的解释移到提示。
- **仅 Charts 的分组及其旧软件筛选链接**把 Abaqus、Abaqus CAE、abaqus/cae 等明确写法
  （忽略大小写和分隔标点）归为 Abaqus。同一对象有多个这些写法也只计一次。
  其他名称如 Abaqus Explicit 不擅自合并；存储、导出、对象列表描述保留原写法。
  不要声称所有搜索、My Data 筛选或任意软件别名都实现了同样的归一化。
- 原权限口径不变：Public database 只统计公开对象；My data 默认仅自己的公开对象，
  Include private data 加入自己的私有对象，不包括别人分享给自己的私有对象。
  图表点击不筛选或跳转；View data 打开对象列表，旧列表书签继续支持。

### 两个尚未由用户最终选定的偏好

- 用户说 Phase “后面括号不行就别要了”。这里既可能指数量后的百分比，也可能指材料名
  中的说明。上一轮曾询问但未收到答案，按已告知的默认方案先去掉百分比括号。
  **不要把保留材料名括号写成用户明确确认过的决定。** 若用户继续指出名称过长，再确认
  是否把说明移到悬停；不要直接合并可能不同的材料或晶体结构。
- 用户问模型是否只分 Elastic / Plastic。助手建议保留具体模型，并按此精简了重复后缀；
  用户尚未明确要求只剩两个总数。若继续讨论，以“现有实现是两大类下的具体模型”为起点。

### 搜索和 Charts 性能边界

- 搜索仍是应用层扫描可访问 JSON。普通搜索和新文本筛选要求所有完整词都出现，
  不计顺序和大小写；不是子串匹配，也不是已建立数据库全文索引。
- 搜索提速来自减少逐对象分享查询、重复元数据转换和对纯数值数组的重复递归。
  本地 105 个合成曲线对象：关键词搜索中位耗时约 4.05 → 0.50 秒，捕获的 SQL 执行数 112 → 7。
- Charts 仍读取当前范围内对象，只把曲线样本有效性检查改为直接检查类型与有限值。
  同规模本地合成数据约 2.40 → 0.66 秒；温度和区间统计仍用 Decimal。
- 上述是本地测量，不是生产响应时间承诺。网络、远程 JSON 传输、数据库延迟和 Render
  冷启动仍可能影响速度；把文件放入 Coscine 并不会自动解决搜索索引和部署性能问题。

### 边界条件和账号功能的延续事实

- 边界显示用小写 `x/y/z` 表示方向，大写 `X/Y/Z` 表示面；`xY` 是沿 x 方向、作用于
  法向为 Y 的面。`+X` / `-X` 保留，用于区分相对两面。原 JSON 的 `xx/xy` 等键不改。
- 第一类是按方向显示的标量载荷／约束；第二类是整个 cube 的应力／应变张量。
  不把所有 load 笼统叫“力”，应根据实际 quantity 解释。
- 动画仍为固定幅度的受力示意，只跟随所选非零分量的符号／方向；**幅度不随数值变化**。
  小夹片是动作道具。保留原透明紫色 cube、边线、角点和手动播放／暂停／重置。
  Calculated strain、显示倍率及材料响应估算已删除，不要自行恢复。
- 用户已要求删除的底部 not-to-scale 文字和 Load details 不应按历史交接恢复。
  删除解释文字不意味着动画变成真实形变计算；无 JavaScript 的原生详情仍可查看。
- Forgot Password 代码与页面已上线，但最近核验时**真实邮件发送仍未配置**。
  需要后续确定正式发件服务、配置凭据，再用获授权的真实邮箱验证；本会话未补配或发送生产邮件。
  Aachen 正式部署时再选择合适的邮箱服务是待讨论事项，不是已经完成。

## 验证结果与限制

- 最新功能版 `6600de6`：**61 项 Charts 测试通过，零跳过**，包括真实 Chromium、
  1280 / 1440 / 1920 桌面宽度、完整文字边界、空数据、超长与中文名称、展开分类、
  标题悬停、键盘操作、禁用 JavaScript、权限与旧书签。已检查截图，系统检查和 diff 检查通过。
- 一次中间运行碰到既有的并发内存 SQLite `KeyError`，未改代码重跑后全过。
  若笔记本复发，先核对 Python、SQLite 和测试服务日志，不要删断言、跳过浏览器测试或当成生产已出错。
- 最近边界标签改动通过 137 项 Node 测试和 12 项相关 Django／浏览器测试。
  较早全量 Django 903 项仍有 15 条历史失败记录，主要是旧上传错误文案和旧 cube 源码字符串断言。
  **不要声称全仓库测试全绿**；明细见上面的边界验证文档。
- 本次交接只改文档，不重新运行应用测试；上述是前一轮已完成的验证结果。
  本机 `/tmp/charts-cleanup-browser/`、`/tmp/charts-cleanup-tests.log` 等日志与截图不随 Git 同步。
  笔记本需要时重新运行测试，设置 `CHARTS_SCREENSHOT_DIR` 到自己的临时目录。

在已确认本机解释器、`DEBUG=True` 和 SQLite 后，Charts 相关验证命令如下；Windows 使用
本机 `.venv\Scripts\python.exe` 及相应环境变量写法。Chromium 不在 PATH 时设置本机 `CHROMIUM_BIN`，
Node 必须支持全局 WebSocket；测试被跳过不能算通过。

```sh
DEBUG=True .venv/bin/python manage.py test apps.charts --noinput
```

## 继续修改时的文件入口

| 文件 | 用途 |
| --- | --- |
| `apps/charts/analytics.py` | 对象统计摘要、Abaqus 分组、曲线可用性、分布 |
| `apps/charts/views.py` | 权限范围、旧筛选、各图上下文、模型显示名 |
| `apps/charts/plots.py` | SVG 几何、标签换行、温度／晶粒统计图 |
| `templates/charts/index.html` 及同目录图表模板 | 八张卡片、标题提示、具体图形 |
| `static/assets/css/charts.css`、`static/assets/js/charts.js` | 布局、完整标签、即时提示 |
| `apps/charts/tests.py`、`apps/charts/test_browser.py`、`tests/browser/charts.cjs` | Charts 回归与桌面截图 |
| `apps/pages/views.py`、`apps/pages/advanced_search.py`、`apps/dyn_api/metadata_compat.py` | 搜索、权限及元数据兼容处理 |
| `templates/pages/data_detail.html`、`static/assets/js/mechanical-bc-*.js` | 边界面板、方向标签、原 cube 动作 |
| `apps/pages/password_reset.py`、`apps/pages/email_backend.py` | 密码重置与邮件发送 |

## 下一轮怎么接

1. Open. 在笔记本核对分支和本地修改，按上面步骤安全同步，再读当前 `AGENTS.md` 和 `HANDOFF.md`；本机已检查，笔记本状态未知。(path read)
2. Open. 继续用户的 Aachen 演示和页面意见，优先查看精简后的 Charts。没有新的修改指令时先解释，不自动扩展功能。
3. Open. 若用户仍觉得文字多，明确 Phase 是哪一种括号，以及模型是否真的只保留两大类；两项都是此前的暂定处理。
4. Open. 若讨论正式部署，再明确 Coscine 的存储、元数据检索、权限、接口及发件服务分工；当前没有集成工作已获新指令。

沟通用简短中文，UI 用英文；用户喜欢白话、直接回答，一个定义贯穿解释，避免反复换术语。
此前已解释：Random 是晶粒取向随机／没有明显择优取向；Median 343 与最大值 343 可以同时成立；
Loading 的 0–101 原本是颜色刻度而非总数据量。继续讲解时保持这些含义。
清楚要求的修改直接做，小范围实现；验证、检查 diff 后提交推送，不反复请求常规确认。
不要重新引入已删文字或大改布局，也不自动推进知识图谱、AI 或 Coscine 迁移。
