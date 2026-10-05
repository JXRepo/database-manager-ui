---
status: ready_for_continuation
branch: main
timestamp: 2026-10-05
code_base: see latest git commit (Remove record navigation from Charts filters)
next_topic: Continue reviewing Charts and detail-page usability
files_modified:
  - Charts filter actions and documentation
---

# Project handoff

## 当前状态

**Charts 负责了解数据覆盖并找到研究需要的对象；单条应力–应变曲线及下载保留在详情页。**

### 本轮：从筛选区移除记录入口

- 用户指出 View records 放在 Filters 中显得奇怪；已移除该链接和仅供它使用的
  objects_url 模板上下文。筛选操作只保留 Apply filters 与 Clear filters。
- 查看具体对象继续使用图表下方的 Source records；图表筛选跳转、应用条件后自动展开
  当前记录、分页和权限逻辑保持不变。README 已同步入口说明。
- 41 项 Charts 测试通过，无跳过；真实 Chromium 检查三个桌面宽度、长名称、空结果、
  筛选、记录跳转和无 JavaScript 操作，已查看首屏与零结果截图。
  日志 /tmp/charts-filter-actions.log，截图 /tmp/charts-filter-actions-qa；
  尚未确认 Render 部署完成。

### 上轮：明确的 Charts 筛选区

- 用户指出现有筛选隐藏在图表链接里，作为用户不知道在哪里筛选。
  在标题与统计之间常驻 Filters：Phase、Software、Stress–strain coverage 直接可选；
  More filters 包含 Texture、材料模型、加载类型／模式、输出、数字区间和统计备注。
  勾选后点 Apply filters，通过普通 GET 同时更新统计与记录，多个值继续按同一对象 AND。
- 已选菜单突出显示，Applied filters 集中展示已提交的条件及逐项移除入口；
  Clear filters 始终可用。空范围和零匹配也保留筛选区，选项来自完整的当前数据范围，
  避免筛完之后无从改选；他人私有数据和收到的私有分享不进入选项。
- 图内 Group by 改为 Chart category，明确它只是统计分类选择；原顶部
  View source records 移到筛选区，改为 View records，仍跳转并展开底部的当前记录。
  Apply 保留范围、私有开关和图表偏好，重置记录分页；既有图表快捷筛选保持可用。
- 选项用精简统计摘要生成，不保留原始 JSON 或数组。分类选项忽略大小写去重，
  功能枚举保持严格匹配；未知／无效书签值及旧参数继续保留，避免提交时静默放宽条件。
  数字区间沿用现有 Decimal 分箱与比较，保存和导出未改。
- 菜单支持键盘、Escape 返回及点击外部关闭；无 JavaScript 时依靠原生 details、
  checkbox 和 GET 正常筛选。长分类名称最多显示两行，完整标签和数值仍保留；
  数字区间完整显示。桌面不改公共标题位置，不做全页重设计。
- 41 项 Charts 测试通过，无跳过；Chromium 覆盖 18 种合成数据布局及 3 种样例布局，
  另外核对三个桌面宽度的菜单、公共标题对齐、多条件／重复条件、零结果、精确数字提交、
  私有范围和偏好保留、清除、键盘 Apply 与无 JavaScript 筛选。
  已查看首屏、菜单、应用条件和零结果截图；样例文件及隔离库 JSON 仍未改。
  日志 /tmp/charts-visible-filters.log，截图 /tmp/charts-visible-filters-qa；
  尚未确认 Render 部署完成。

### 上轮：删除 Charts 顶部说明，解释记录入口

- 用户逐项检查 Charts，认为 Explore statistical charts and tables, then open the records
  behind them. 多余；已删除这段说明及仅供它使用的 .charts-heading p 样式。
- View source records 是底部 Source records 的快捷入口：保留当前范围与筛选，
  通过 show=objects#objects 跳转并展开参与统计的具体记录，可点标题进入详情。
  用户本轮询问用途，尚未要求删除这个按钮。
- 38 项 Charts 测试通过，无跳过；三个桌面宽度的标题对比及既有真实浏览器检查通过。
  已查看删文案后的截图；日志 /tmp/charts-heading-copy.log，
  截图 /tmp/charts-heading-copy-qa；尚未确认 Render 部署完成。

### 上轮：Charts 标题位置与公共页面对齐

- 用户指出前次调整后 Charts 标题的位置和大小仍不一致。真实浏览器对比发现：
  1280px 下比 My Data 向左偏 18px、向下偏 6px，字号和字重本身已相同。
- 移除 charts.css 对内容宽度和边距的独立覆盖，复用公共 pc-content 的
  顶部 20px、左右 40px；标题补齐与 My Data／Share 相同的 row／col 结构，
  breadcrumb 复用公共正文颜色。保留语义 h1 和公共 h5 外观。
- 内容宽度收紧后，1280px 桌面的直方图区间刻度略小于既有可读性下限，
  将该桌面区间的刻度字号从 15px 调整为 16px，其他宽度保持原样。
- 38 项 Charts 测试通过，无跳过；Chromium 直接比较 My Data、Share 与 Charts 在
  1280／1440／1920 下的标题位置、高度、字体和导航间距、颜色，全部一致。
  标题实际坐标均为 (304, 102.25)，字号 18px；既有 15 种 Charts 桌面布局、
  统计跳转、私有范围、空数据、长内容、无 JavaScript 和本地样例检查通过。
  已查看三个页面的实际截图；日志 /tmp/charts-heading-consistency.log，
  截图 /tmp/charts-heading-consistency-qa；尚未确认 Render 部署完成。

### 上轮：详情曲线固定尺寸

- 用户转述 Ronak 认为详情曲线横向太长，要求选择合适的固定尺寸。
  将 .plot-canvas-wrap 设为宽 720px、max-width:100%，.plot-canvas-box 高 480px，
  桌面按 3:2 居中显示；可用空间不足时仅收缩宽度，避免横向溢出。
- 仍由 Chart.js 按实际容器尺寸绘制；状态文字保持在独立画布父容器之外。
  保留既有坐标范围、顺序、悬停、选轴和导出逻辑，原始 JSON 未修改。
- 14 项相关 Django 测试通过，包含真实 Chromium 的 19 类曲线、三个桌面宽度和用户样例。
  浏览器确认实际绘图尺寸为 720×480、显示与鼠标坐标一致，轴标题／刻度未裁切，
  循环、微小值、悬停提示、原值查看、PNG 和 CSV 下载正常。
  已查看样例、悬停和 PNG 实际截图；日志 /tmp/detail-fixed-size-tests.log，
  截图 /tmp/detail-fixed-size-qa；尚未确认 Render 部署完成。
- 此前已完成两项 Charts 小调整：删除 Select a bar… 说明；标题复用 My Data／Share
  的公共大小与字重，添加 Home › Charts 导航，保留右侧范围选择。

### 上轮：Charts 标准统计图、汇总表与简化范围

- Charts 的中文意思是图表；用户要求看得懂的饼图、直方图和真正的汇总表，并指出
  Data notes／Data objects 的含义不清楚。用户的新范围要求取代以前的四种 accessible scopes。
- 默认 Public database，查询全库 access_type="all"；My data 只查询当前 owner 的公开上传，
  勾选 Include private data（include_private=1）才加入自己的私有上传。
  他人分享的私有对象不纳入这两个范围，普通 Search 和详情权限不变。
  include_private 严格接受单个 0／1，错误参数返回零记录；旧 all／shared 范围链接
  显式跳转到 Public database，保留有效图表条件和偏好，不继续统计原先的私有对象。
- 首屏 Materials & microstructure 条形图与 Results coverage 饼图并列；第二行
  Simulation setup 条形图与 Simulation conditions 直方图并列。
  饼图仅将对象划分为“有／无匹配应力–应变分量”两类，互斥且总和等于当前对象数；
  切片和表格使用 coverage=matching／without_matching 继续按同一对象做 AND 筛选。
  多相、多软件、模型和输出类别可能重叠，不能拿它们冒充总和为 100% 的饼图。
- 每个类别图直接显示真实 HTML 统计表：类别、Objects、% of selection，前六行可见，
  其余可展开；输出表区分 supplied／calculated equivalents。
  非恒定数值使用最多八个等宽 Decimal 区间，空箱保留，末箱包含最大值；恒定值
  只画一个真实频数柱。数值表分别标出 Observations 和不同对象数量，不混淆多相观测。
  相邻大整数与窄范围保留精确极值、中位数和筛选边界，SVG 用短的相对刻度并明确标出
  Interval offset，表格仍显示绝对区间；避免 Decimal 默认精度抹掉大整数末位及半步中位数。
- Statistics notes 说明单位缺失、排除值、数组差异，明确不等于验证结论；
  Source records 是当前统计背后的具体记录列表，点标题进入详情看曲线、下载。
  scope／私有开关改动清掉筛选和分页，保留三个图表显示偏好；图表链接、移除条件、
  清空、分页保留有效的私有开关，JavaScript 禁用时仍可用普通 GET 表单。
- 原始 JSON、详情曲线与完整导出保持不变；没有新依赖、迁移或外部数据发送。
- 验证：77 项相关 Django 测试、127 项 JavaScript 测试通过，0 跳过。
  Chromium 覆盖 1280／1440／1920 的多记录、长名称、空范围、相邻大整数和本地样例，
  共 15 种 Charts 桌面布局；核对范围权限、私有开关、饼图互斥数量、真实统计表、
  键盘链接、组合筛选、分页、旧范围跳转与无 JavaScript 的普通 GET。
  样例 Copper／Abaqus CAE／Goss、298 K、343 grains、2744 cells 及详情入口一致，
  断言样例文件字节与隔离 SQLite 的 JSON 未变；详情 19 种曲线场景、悬停与下载回归通过。
  已查看多记录、长名称、样例与相邻大整数的实际截图。
  日志 /tmp/charts-statistics-final.log、/tmp/charts-statistics-js.log；截图 /tmp/charts-statistics-qa。
  推送成功不代表 Render 已完成部署，尚未确认部署完成。

### 上轮：Charts 数据覆盖与发现

- 用户明确批评 Charts 重复详情页的单条曲线，要求重新考虑真正有用的内容。
  本轮围绕研究人员的“库里有什么、条件覆盖在哪里、哪批数据可以进一步查看”调整现有页，
  不再把随机一个对象的应力–应变预览作为首屏主图。
- 首屏并列 Materials & microstructure（Phase／Texture）和 Simulation setup
  （Software／Elastic model／Plastic model／Loading type／Loading mode），
  下面保留 Simulation conditions（温度、晶粒数、离散数）和 Available results。
  每个图的对象数、覆盖分母或观测单位可见；柱形、区间与结果数可点击，打开匹配对象列表。
- 类别、范围、结果与备注条件继续在同一对象上逐项收紧；三种图表选择器独立保留偏好及
  全部活跃条件。旧 group=phase／texture 书签映射到材料图；旧 curve/component 参数只做
  既有输入检查，不读出单对象曲线，也不会绕过权限或已选过滤。
- 新增 result=matching_response，仅计应力与总应变的同一分量可用的对象，
  包括供应的或符合既有规则的可计算等效量。顶部对应计数可点击；
  旧 result=paired 的“两组都有数据”语义保留，不把它冒称为匹配曲线。
  Phases 标签改为 Distinct phase names，避免与多相晶粒观测数量混淆。
- templates/charts/index.html、charts.css、charts.js 和 apps/charts/views.py 移除单对象曲线
  控件、交互及额外读取；删除只供该预览使用的 curve.html 和 plots.py 函数。
  详情绘图、原始 JSON、完整导出、访问控制、数据库和依赖不变。
- 助手 charts.overview／charts.curves／charts.save 保留主题 ID，答案改为
  通过 Charts 查找对象，再到详情查看曲线或下载 PNG／CSV／JSON；不再宣传 Charts Save SVG。
- 70 项相关 Django 测试、127 项 JavaScript 测试通过，0 跳过；最后调整数字字号及标签位置后，
  再通过全部 31 项 Charts 测试。浏览器覆盖 1280／1440／1920 桌面宽度的多记录、长名称、
  空状态，以及真实样例共 12 种布局；核对四幅聚合图、数字可读且未裁切、键盘链接、
  选择器互相保留、连续组合筛选、数量一致、权限、分页、无 JavaScript 普通表单与详情入口。
  样例只写入隔离 SQLite：Copper／Abaqus CAE／Goss、298 K、343 grains、2744 cells
  与五项叠加筛选均核对一致；测试断言原文件及存储 JSON 未变。
  已查看真实样例、多记录和长名称桌面截图，详情页原有曲线、悬停与下载回归也全部通过。
  日志 /tmp/charts-discovery-final.log、/tmp/charts-discovery-browser-final.log、/tmp/charts-discovery-js.log；
  桌面截图位于 /tmp/charts-discovery-qa。
  临时文件不随 Git 同步；推送成功不代表 Render 已完成部署。

### 上轮：稳定的曲线悬停和明显的选中点

- 用户反馈鼠标在蓝线上有时显示提示、有时不显示，要求突出显示一个大点并展示信息。
  根因是 Chart.js 默认 nearest + intersect=true，仅命中不可见采样点的 10px 范围，
  稀疏采样点之间的长线段不能稳定触发。
- 真实鼠标检查还发现原画布父容器包含状态文字：Chart.js 内部高度 451.2px，而 CSS 强制
  显示为 420px，造成鼠标位置偏差。新增独立的 420px plot-canvas-box，仅包含画布，
  状态文字仍在其下方；浏览器核对内部尺寸和显示尺寸一致。
- templates/pages/data_detail.html：findCurveHoverIndex 按屏幕像素检测完整折线的 16px 邻域，
  mechanicalCurve interaction mode 供悬停和提示共用，命中后选择最近线段上的真实端点。
  保留原始顺序；交叉处按原顺序稳定选择，重复点不除零，跳过点和无效点之间不连假线。
- 活动点半径 8px、白边 2.5px，平时仍无固定端点圆圈。提示显示 Sample index（从零起）、
  当前变量和单位，以及真实 X/Y 数值，不用默认数值格式把微小值舍入，也不生成插值数据。
  活动点和提示即时更新；移出蓝线邻域、进入画布留白或离开画布时清除两者。
- JavaScript 回归新增稀疏线段、循环交叉、单点、重复点与无效断点。
  浏览器检查使用真实鼠标事件，覆盖三个桌面宽度的线段连续移动、离线、重新进入、
  画布边缘和离开，以及回折曲线、微小值和单点；同时核对大点像素、白边、真实值和单位。
- 30 项相关 Django 测试、127 项 JavaScript 测试通过，0 跳过；真实 Chromium 检查
  19 种曲线 × 3 个桌面宽度以及新增悬停行为，已查看悬停截图和导出的 PNG。
  日志 /tmp/detail-hover-final.log、/tmp/detail-hover-js.log；截图和实际 PNG 位于 /tmp/detail-hover-qa。
  临时文件不随 Git 同步；Render 部署状态需要另外核实。

### 上轮：两条坐标轴、箭头和原点零标签

- 用户要求删除象限矩形框，只保留正常 X/Y 轴，在末端加箭头，并分别标出两轴原点的 0。
  为显示真实原点，本轮范围覆盖当前配对样本的极值和 0，取代上轮严格只取极值的规则；
  已向用户说明这一必要调整，正负范围仍不对称扩展，极小反号值保持真实比例。
- templates/pages/data_detail.html：删除左下框架和额外零参考线，仅画 y=0 横轴、x=0 纵轴。
  X 轴正方向向右、Y 轴正方向向上，各有箭头；绘图区之外预留箭头空间。
  常规刻度跳过零，交点附近单独绘制两个 0，略错开以避免重叠。
- 刻度数字贴近实际轴线，朝原点较近的外侧放置；标题保留在图外，Y 标题继续竖排。
  负 X 为主时文字放右侧，负 Y 为主时放上侧；文字在曲线之前绘制，没有遮挡白底，
  曲线像素仍完整可见。四象限的刻度数字不会留在无轴的图边缘。
- 保留原始样本顺序、微小数值、选轴联动、原值查看和 PNG／CSV 下载。
  大数值窄范围在包含真实原点的线性坐标中会被压缩，刻度重新按最终范围计算，
  不把偏移刻度冒充真实的 0；全零坐标使用正向范围避免退化。
- 浏览器仍检查 19 种情况 × 3 个桌面宽度，新增两条零轴、正向箭头、两个独立零标签、
  无额外边框的像素检查，并保留曲线连续性、样本、字体、下载和空状态回归。
- 30 项相关 Django 测试、124 项 JavaScript 测试通过，0 跳过；最后调整边界零标签后，
  重新通过全部浏览器检查，样例 22 的零标签已移到曲线外侧。
  日志 /tmp/detail-cartesian-final.log、/tmp/detail-cartesian-js.log、/tmp/detail-cartesian-browser.log；
  截图及实际 PNG 位于 /tmp/detail-cartesian-qa。
  临时文件不随 Git 同步；Render 部署状态需要另外核实。

### 上轮：按数据范围绘图，修正刻度遮挡（范围和外框已由本轮取代）

- 用户指出强制原点和对称范围会扩出多余象限，明确要求使用横纵坐标真实最小、最大值，
  去掉起终点圆圈，纵轴标题竖放，并让被刻度挡住的曲线完整显示。
  本轮要求取代下方历史记录中的“包含零、以零为中心、端点圆圈、刻度白底”。
- templates/pages/data_detail.html：范围直接取当前配对采样点的最小和最大值，不强制包含零，
  不对称扩展。只有恒定坐标额外扩展以免坐标轴退化；极小反号值保持原值及其实际比例，
  不把数值误差猜成零，也不放大为半幅图。
- 左侧和底部坐标轴保留，零参考线只在相应范围跨零时出现；数值刻度在绘图区外，
  删除遮挡曲线的白底，纵轴标题旋转为竖排，无网格或固定端点圆圈。
  大数值、小范围的刻度使用明确的 Offset 标注；σ、ε、单位和下标的字体规则保持不变。
- 像素检查发现 parsing: false 让 Chart.js 假定横坐标有序，在精确范围下漏画循环曲线末段。
  移除此设置，由绘图库识别原始顺序；没有排序、插值、改变坐标值或重算已有等效量。
- 保留选轴联动、原值查看和 PNG／CSV 下载；Charts、权限、数据库和原始 JSON 不变。
  本机 a46fde6c.json 只在隔离测试库中读取，未修改或发送到外部。
- 浏览器覆盖 19 种情况 × 1280／1440／1920 桌面宽度：加入远离零点、极小反号值、
  大数值窄范围和恒定坐标；检查真实范围、旋转文字边界、连续线段像素及零端点标记。
  另核样例 33、22、13、23 分量、空数据、选轴、原值与下载；23 分量仍配对 242 点。
- 90 项相关 Django 测试、124 项 JavaScript 测试通过，0 跳过；已查看桌面截图和导出的 PNG。
- 验证日志 /tmp/detail-extrema-final.log、/tmp/detail-extrema-js.log，桌面截图及实际 PNG
  位于 /tmp/detail-extrema-qa。临时文件不随 Git 同步；Render 部署状态需另外核实。

### 上轮：详情曲线外观与象限（范围和标记规则已由本轮取代）

- 用户明确要求保留详情页整体逻辑，只调整曲线外观：参考 Charts 风格，加上纵轴，
  去掉象限内部的横线；一个象限显示一个，相邻两个显示两个，对角两个或更多显示四个。
- templates/pages/data_detail.html：坐标范围包含零；单一符号以零为边界，两种符号以零为中心。
  横纵零轴随象限移动，保留微小数值的符号；只有零的坐标使用正向范围，不产生退化坐标轴。
  蓝色折线按原始顺序连接，起点空心、终点实心；细轴线、刻度、单位与留白采用 Charts 配色。
  图内没有网格线，刻度文字有白底避免被曲线穿过；σ、ε 保持斜体，单位与下标保持正体。
- 保留原 X/Y 选项及联动、总应变／塑性应变、等效量来源、原值查看、PNG 与 CSV 下载逻辑。
  Charts 页面、原始数据、权限和数据库未改；example_json_files/a46fde6c.json 未修改或发送到外部。
- 新增 apps/pages/test_plot_browser.py 与 tests/browser/mechanical-plot.cjs：使用真实 Chart.js
  和 Chromium 验证 14 种情况 × 3 个桌面宽度，包含四种单象限、四种相邻组合、两种对角组合、
  三象限、循环顺序、全零与微小正负值。另测空数据、轴线像素、文字边界、字体、选轴联动与下载。
  本机样例额外核对 33、22、13、23 分量，23 分量仍按原逻辑配对 242 点，CSV 保留完整数组。
- 90 项相关 Django 测试、121 项 JavaScript 测试通过，0 跳过；已查看桌面截图和实际 PNG。
  原来检查旧坐标样式源码常量的测试由浏览器真实绘图检查替代。扩展回归还发现一条上传提示
  断言仍期待旧的 “Object 2 in this file”，在 f31b868 临时副本复现后更新为当前对象编号及标识符；
  上传实现未改。
- 浏览器检查需要 Chromium、支持全局 WebSocket 的 Node 及现有 CDN Chart.js；可用
  CHARTJS_TEST_BUNDLE 指定缓存库进行离线检查，本轮实际使用 Chart.js 4.5.1，未新增运行依赖。
  日志 /tmp/detail-quadrants-final.log、/tmp/detail-quadrants-js.log；截图与 PNG 在
  /tmp/detail-quadrants-qa。临时文件不随 Git 同步，Render 部署完成状态未核实。

### 助手既有背景

右下角 FAIR Data Assistant 保留 82 个主题的初版平台助手，继续使用本地语义匹配、维护好的答案和简短追问。

- 用户试用旧版后指出 data form 都无法理解，随后同意推荐的改进方案。
  不要继续把这轮当成纯讨论，也不要回退为只补关键词。
- 小模型在本项目 Django 进程内运行，理解问法后选择维护好的答案；不是生成式 ChatGPT。
  无需模型账户、API Key、额外模型训练或按次付费 API，不提供转人工。
- 用户不熟悉开发，希望用中文白话解释；应用 UI、代码注释与 docstring 保持英文。
- Charts、上传处理、权限和原始 JSON 未改。样例 example_json_files/a46fde6c.json 未修改、未发送到外部。
- 用户要求完成后验证、提交、推送。Git 推送成功与 Render 部署完成必须分别说明。

### 上轮：回车发送与底部帮助入口

- templates/includes/fair_assistant.html：输入框按 Enter 走原有表单发送，Shift+Enter 换行。
  输入法组合确认与按键重复不会发送；保留空白内容和请求进行中的防重复检查。
- Browse help topics 从聊天框顶部移到输入框下方、Send 左侧；加入简短键盘提示。
  分类导航、会话上下文和回答逻辑不变。
- 5 项 Django 界面测试通过，其中真实 Chromium 检查原生 Enter／Shift+Enter、
  模拟输入法组合与重复按键事件，以及长内容、空列表等 18 种桌面布局。
  新增的回车回归先在旧实现上失败，再在修改后通过；117 项 JavaScript 测试通过，0 跳过。
- 日志 /tmp/assistant-enter-ui.log、/tmp/assistant-enter-js.log；截图 /tmp/assistant-enter-qa。
  已查看分类菜单与长答案的桌面截图；未检查 Render 是否完成本轮部署。

### 上轮：按用户任务扩充初版帮助

- 用户确认当前答案是预设知识后，要求尽量想全，按问题大类扩充为真正可用的初版。
  这是明确的实现请求，不再停在方案讨论；也没有要求训练或接入生成式模型。
- 从 25 个主题扩到 82 个：9 类通用帮助共 76 条，另有当前授权对象的 6 种摘要。
  分类是 Getting started、Prepare data、Upload、Search、Access and sharing、My Data、
  Reading data and plots、Charts、Account；详情页额外显示 Current object。
- 新增注册／密码／ORCID／通知、撤权和共享历史、上传语法／进度／配额、搜索范围和空结果、
  导出格式／CSV 空尾／计算来源、修改及恢复限制、张量图和统计口径等具体步骤。
  来源与维护方式见 docs/assistant-coverage.md。条目仍位于 assistant_knowledge.py。
- assistant.py 按 category 分页，每页最多 6 个问题；页码按钮不依赖会话或语义模型。
  more/back、下一页/上一页、第一至第六项可使用签名上下文；回答推荐后续任务。
  password、ORCID 单词先澄清具体需求；常见 pasword/ORICD/xslx 拼写可修正。
  新增忘记旧密码、解绑后登录和删除后恢复的短追问；撤权后的 how 不再误答成添加共享。
- 答案明确当前没有邮件验证码／邮件找回密码、现有对象公开私有切换、在线 JSON 编辑、
  回收站和自助销号。JSON 批量下载可跳过失效对象，CSV 必须整个选择都可导出，不能混淆。
  原来的界面风格、模型、依赖、数据库和权限实现未改；不执行用户请求的数据操作。

### 上轮扩充验证

- 47 项相关 Django 测试通过，包含完整 assistant 模块、原有权限／输入检查和 phase 回归。
  117 项 JavaScript / Chromium 测试通过，0 跳过。真实 Chromium 验证 18 种桌面布局，
  包括分页、序号选择、长内容、空数据、连接失败重试和账户帮助；未做专门移动端改版。
- 浏览器夹具使用顺序 HTTP 服务器，避免 Python 3.10 下后台轮询与请求并发使用同一个
  内存 SQLite 连接时的 statement-cache KeyError；生产服务器未改，这不是并发负载测试。
- 原 52 轮回归现为 27 直接答对、21 相关澄清、3 正确范围提示、1 正确权限拒绝。
  新增独立编写的 40 场景／43 轮原样保存在 fixtures/assistant_expanded_questions.json。
  首轮发现 16 个误选或回答不完整，修正后自动回归为 29 直接答复、14 相关澄清。
  自动回归检查能否得到正确答案或入口，不等于每个答案满足全部细节；独立评估另核内容。
  这些题已用于迭代，是回归集，不能宣称泛化准确率 100%。
- 又单独固定了 10 条新问题（fixtures/assistant_followup_questions.json），首轮 4 直接、
  2 相关澄清、4 失败。修正了曲线 CSV 选列、已下载副本不能追回及站外邮箱／云盘范围问题。
  全部 105 轮现已纳入回归，不能把已见题通过率称为新问题理解率。
- 最终独立真实 HTTP 复核：新增 43 轮为 29 直接、14 澄清；后加 10 轮为 5 直接、3 澄清、
  2 正确站外范围提示，均无核心问题失败。严格原要求为 52/53：唯一差异是“Which download
  do I need?” 给出了正确 JSON/CSV 概览，而原题期待先澄清。所有请求 HTTP 200，数据未改。
- 日志 /tmp/assistant-expanded-final-backend.log、/tmp/assistant-expanded-js.log；
  截图 /tmp/assistant-expanded-qa。首轮独立评估在
  /tmp/assistant-expanded-independent-results-draft1-reviewed.json。临时文件不随 Git 同步。

### 助手语义基础（继续保留）

- apps/pages/assistant_knowledge.py：平台答案、导航分类、明确别名和中英文代表问法。
  增加 JSON 格式、模板准备、实际 24 个顶层必填字段和科学分析能力边界。
  数据规则以 README、当前代码、bundled MiMeDat profile 为准，额度仍读取 settings。
- apps/pages/assistant.py：精确按钮、有限拼写纠正、语义匹配、置信度和候选差距判断。
  data form（包括完整句中的这个词组）先区分 JSON format / Upload form；
  format → which fields? → how big? 可连续追问，the second one 按上次候选顺序选择。
  完整新问题能换话题；未知短词不直接猜答案；访问范围与分享设置不确定时一并询问。
  不保证理解任意表达；低置信度仍可能展示一至三个选项，其中有时有不相关候选。
- apps/pages/assistant_semantics.py：multilingual MiniLM 的量化 ONNX 编码器，
  不是大型生成模型，不根据用户数据训练。只缓存公开知识问题的向量，不缓存用户问题或对象值。
  单 CPU 推理线程、每问最多 128 tokens、推理锁等待最多 2 秒；逐句建立索引，避免量化批次干扰。
- apps/pages/views.py：保留登录、POST、CSRF 和逐次对象权限检查。
  新增 30 分钟过期、绑定用户及对象的签名 topic/choices token；不含问题或对象内容。
- templates/includes/fair_assistant.html：只在当前页面内存保留对话和 token。
  切页或刷新清空，Browse help topics 重置话题；连接失败保留问题与上一 token 供手动重试。
  所有文本继续 textContent 展示，链接保持站内；助手不执行删除、分享、搜索、上传或拟合。
- 缺模型、加载或推理失败、推理繁忙时明确提示，并保留可点击的固定问答与授权对象摘要。

### 安装与部署

- 新增 NumPy 2.2.6、ONNX Runtime 1.23.2、SentencePiece 0.2.1 的明确依赖。
  本机 Python 3.10.12，Render 配置仍是 Python 3.12.13，未改套餐或 worker 数。
- 安装依赖后运行 manage.py prepare_assistant_model；build.sh 已加入此步骤。
  只在 setup/build 从 Hugging Face 下载约 118 MiB 的公开权重及词表，无需账号。
  模型 snapshot 固定为 e8f8c211226b894fcb81acc59f3b34ba3efd5f42；两文件均校验大小和 SHA-256。
  下载临时文件验证后原子替换，失败会停止新 build，已有正确文件可复用。
- 文件位于被 Git 忽略的 .assistant-models/；不提交权重，不在问答请求中联网补下载。
  新电脑不能只拉代码就假定模型已存在，README 和 docs/deployment/public-pilot.md 已更新。
- 完整本地 HTTP 进程约 279 MiB RSS、357 MiB 峰值；首次语义问题约 1.06 秒，
  后续串行请求中位 6.55 ms。测试包含菜单及语义问题，不是 Render 并发或大文件上传容量证明。
  上传进程另有内存开销；线上部署后应观察内存和重启记录，不擅自升级付费套餐。

### 上轮语义升级的验证记录

- 38 项相关 Django 测试通过；包含真实 Chromium 的 12 种桌面布局、上下文重试、长内容和空数据。
  117 项 JavaScript / Chromium 测试通过，0 跳过。pip check 和模型 setup 命令通过。
- 保留原 35 场景 / 42 轮及另行编写的 10 条新问题在 apps/pages/fixtures/assistant_questions.json。
  真实 HTTP 最终 52 轮：33 直接答对、15 给出正确候选、3 正确范围提示、1 正确拒绝撤回权限。
  严格按原先要求的回答类型和候选组合为 42/52；不能宣称 52 条都直接答对或泛化准确率 100%。
  题库已用于迭代，后续作为回归集；继续改时应另补真实用户或新编问题。
- apps/pages/test_assistant_acceptance.py 明确检查“答对或能选到正确入口”；其余测试验证
  模型真实语义、离线请求、参考 token IDs、长度限制、下载完整性、过期/伪造/跨用户/跨对象 token、
  缺模型及推理故障、权限撤回。原有助手、phase 和权限测试保持通过。
- 独立审查未发现剩余阻断项；修复了误选删除、完整句 data form 遗漏、中断/边界条件候选遗漏、
  分享歧义候选不完整，以及量化索引受同批其他文本影响的问题。
- 日志 /tmp/assistant-semantic-backend.log、/tmp/assistant-semantic-js.log；
  桌面截图 /tmp/assistant-semantic-qa；最终 HTTP 报告 /tmp/assistant-independent-results-reviewed.json。
  这些临时文件不随 Git 同步。规格与计划在 docs/superpowers/ 的 2026-09-29-assistant-understanding 文件。
- Python 命令前用 PyCharm 环境工具解析本机解释器；DEBUG=True、隔离 SQLite；不使用生产凭证。
  后续助手检查需先 prepare_assistant_model，浏览器需 Chromium 与支持 WebSocket 的 Node，不能跳过。

### Charts 上一版实现与统计口径（单对象预览和首屏布局已由本轮替代）

- `/charts/` 仍用现有路由；`apps/charts/views.py` 管权限、筛选和分页，
  `apps/charts/analytics.py` 从共享 metadata compatibility view 提取精简统计。
  新增 `apps/charts/plots.py` 计算 SVG 几何。逐个读取 JSON，不把原曲线保留在汇总记录中；
  只再次读取当前所选对象作图，没有新依赖、模型或迁移。
- Data scope 有 All accessible、My uploads、Public、Shared with me。
  默认包含自己、公开、明确分享给自己的对象，统计与列表采用相同权限；公开仍需登录。
- 顶部是一行精简计数；首屏左侧为真实 Stress–strain response，右侧是一个可切换的
  Data composition 图，不再平铺多个分类面板。第二行是条件分布和 Available results。
  Data notes 与 Data objects 默认收起，点统计项后展开匹配对象；标题仍为 Charts。
- 主曲线每次只画一个可访问对象的同分量应力／总应变，默认优先等效曲线；对象与分量可切换。
  复用详情页等效计算，用户提供的数组优先，空等效字段不触发计算。保持原始点序，支持循环路径。
  默认选择须有实际匹配的分量，不让 stress_11 / strain_33 这样的不可配对新对象挡住可用曲线。
  顶部 With stress & strain 计数仍只表示两组均有数据，不作物理可比性保证。
- 曲线带单位、点数、Supplied results／Calculated equivalent 来源；鼠标与键盘可看精确点值。
  不同长度按索引配到较短序列，同时显示两侧原始长度。超过 2,400 点的预览保留端点与局部极值，
  明确标注显示点数；Save SVG 下载保留来源、长度和抽样说明，完整原数组与 CSV 导出不变。
  刻度使用自适应 Decimal 精度，极窄范围使用 Offset 注记，有限大整数不会使整个页面报错。
- 分类可切换 Phase、Software、本构模型（Plastic/Elastic）、Loading（Mode/Type）和 Texture。
  每对象在每个类别只计一次，大小写和首尾空白合并，多相／多模型可进入多个类别。
- Simulation conditions 提供温度、晶粒数、离散单元数的分布、中位数、范围和覆盖数量。
  显式 K/Celsius/Fahrenheit 才换算为 K；无效值不当作零。
  晶粒数以 phase 为观测单位，链接去重到对象；单值也显示带计数坐标轴的真实柱形。
- Available results 识别所有现有支持的分量与用户提供的等效曲线，不再只看 11 分量。
  等效字段缺席且六个分量齐全才算可计算，遵循详情页现有规则。
  另有 Data notes 提示曲线长度不同、单位缺失、无效温度／曲线和字段冲突。
- 删除了旧的自动 Comparable 分组和混单位力学极值；可用曲线不等于科学可比或校验通过。
  原始 JSON、详情图和导出未改，样例也没有修改或上传到外部。
- 点任意条形／分箱／结果数量，会保留已有条件并继续筛选同一对象。
  分类和 result/note 可用重复 GET 参数；数字范围用可重复
  `range=measure:low:high:inclusive`，兼容单个旧式 measure/lo/hi。
  全部条件 AND，支持逐个移除、清空和每页 10 条的对象列表。
  无效条件显示错误且结果为零；范围删除保留原参数索引，不误删别的条件。
- 分箱保留 Decimal 原始极值，使用同一边界进行计数与跳转；已修复 Fahrenheit
  循环小数导致最小值漏计的问题。接近的数值会增加显示精度，避免所有箱都显示相同范围。
  grain_number 的等价拼写和单值包装明确处理；别名冲突排除受影响的 phase 并提示。
- 模板在 `templates/charts/`，样式／脚本在 `static/assets/css/charts.css` 和
  `static/assets/js/charts.js`，不依赖外部图表库。四幅图均为服务器输出的 SVG，
  关闭 JavaScript 后仍有图、普通 GET 控件和 Apply 按钮。
  主题 loader 保留隐藏的清理节点，避免无 JS 遮挡图表或 pcoded.js 清理不存在节点报错。
- 桌面布局用 `.charts-page` 的 padding-top 给导航留空间，不用会塌陷到 body 的 margin-top；
  浏览器验证还检查标题实际未被导航遮挡。

### Charts 上一版验证

- 83 项相关 Django 测试通过，覆盖 Charts、共享字段兼容、上传兼容、详情曲线、CSV 和导航。
  其中包括真实 Chromium 连接隔离 SQLite 的浏览器测试；日志 `/tmp/charts-refined-backend.log`。
- 117 项 JavaScript／Chromium 测试通过，0 跳过；日志 `/tmp/charts-refined-js.log`。
- 1280／1440／1920 桌面宽度验证多记录、长内容、空数据共 9 种布局，检查四图可见、首屏主曲线、
  键盘点值、普通／抽样 SVG 实际下载、对象／分量／分类／条件切换、条形／分箱筛选、清空、
  scope、分页、无 JavaScript 回退和私有记录排除。
  截图在 `/tmp/charts-refined-qa/`。完整截图改用临时加高的真实 viewport，避免
  CDP captureBeyondViewport 截图触发主题边距过渡造成假重叠。
- 用户样例只放入隔离内存库核对：Copper、Abaqus CAE、Goss、298 K、343 grains、
  2744 discretization，曲线 242–250 点并有 Different curve lengths 提示；
  等效曲线为可计算，无用户提供的等效数组。所有图表链接数量与对象列表一致。
  原样例及多相副本另做 6 种桌面布局；无 JS 异常，原文件 SHA-256 未变。
  临时记录与截图在 `/tmp/charts-refined-sample/`，不纳入 Git。
- 独立审查发现的有限大整数轴崩溃、相近刻度重复、不可配对默认对象和 SVG 遗漏抽样说明，
  均已补回归并修复。上一轮的精确筛选与分箱回归也保留。
  计划记录在 `docs/superpowers/plans/2026-09-28-charts-statistics.md`。
- 继续改这里时先跑 `DEBUG=True ... manage.py test apps.charts`；真实浏览器需要
  Chromium 与有全局 WebSocket 的 Node。跳过不能算通过，仍不主动做移动端改版。

### 上传部分交接补充

- 一次最多 5 个文件。批次文件数、总大小、总对象数先检查；通过后按文件顺序处理。
  文件旁的状态逐个更新，具体错误在整批处理结束后按文件顺序统一显示。
- 每个文件独立保存：文件内任何对象有错，该文件整个不保存；其他合格文件照常保存。
  例如整批未超限时，5 个文件中 2 个合格，则保存这 2 个，失败的 3 个修好后单独重传。
- 报告当前有 19 类问题，定义在 `apps/pages/views.py` 的 `UPLOAD_ISSUE_CATEGORIES`。
  登录、网络、批次超限等是额外操作提示；未知服务异常有通用中断提示，
  结果未确认时提示先查看 My Data。不能承诺未写入校验规则的问题都会自动被发现。
- 当前 `Data_Base_Cyclic.json` 的 100 个对象只报缺根 system、phase、units，以及空 total_strain；
  `a46fde6c.json` 的 1 个对象已通过上一轮字段检查。不要修改用户原样例来凑齐要求。
  附件位于本机 `example_json_files/`，被 Git 忽略；新电脑不会随拉取自动获得。

### 最新完成：上传框与提示收紧

**9 月 28 日最新：缩小上传框，去掉重复提示。**

- 上传框最小高度从 300px 调整到 200px，选中多个文件时继续自动撑开。
- 错误报告删除 `Not uploaded. No data from this file was saved.`，文件名后直接显示修改要求。
- Checking n / total 只显示在文件旁边，Upload 按钮下面不再重复；后台任务与 NDJSON 均适用。
  其他页面的顶部进度和网络异常提示仍保留，保存阶段继续说明成功提交后才算 Uploaded。
- 涉及 `static/assets/css/custom.css`、`static/assets/js/upload.js`、
  `static/assets/js/upload-host.js`、`templates/includes/upload_issue_report.html` 和现有浏览器测试。
- 52 项相关 Django 测试通过；117 项 JavaScript／Chromium 测试通过，0 跳过。
  日志为 `/tmp/upload-trim-backend.log` 和 `/tmp/upload-trim-js.log`。
- 另有 1 项真实 HTTP 浏览器检查通过：1280／1440／1920 桌面宽度下的空框、单文件、
  5 个长文件名、100 对象错误、展开明细、长内容及空文件均无横向溢出或 JavaScript 异常。
  截图与临时检查在 `/tmp/upload-trim-qa/`，日志为 `/tmp/upload-trim-browser.log`。

### 9 月 28 日上一轮：简化错误报告

用户要求报错更短，直接告诉用户该改哪里。

- 多对象的同类同字段同原因错误合并显示，并标明 All 100 objects 或确切位置，例如 Objects 1, 4–5。
  不把只涉及部分对象的问题说成所有对象都有；缺字段与空值保持分开。
  Ronak 的当前文件默认只需两行操作：Add system / phase / units；Fill in total_strain。
- View individual objects 展开全部有问题的对象，顺序与原文件一致；每条对象还可单独展开。
  只有一条错误对象时直接展开。保留标题、有效 identifier、位置和所有字段错误；
  Location 与 identifier 完全相同则不重复显示，对象序号也不重复写两遍。
- 具体字段与修改动作直接显示，重复字段路径的技术原因放在 Show reason 中。
  文件级 JSON 语法、空文件、共享、编号等仍有各自简短指引；全部上传内容继续转义。
- 结束时只显示一份最终结果，不再在按钮下方和错误框各重复一遍 Upload finished。
  同步表单、NDJSON 与后台上传共用服务器报告模板；进度和整文件保存规则未改。
  已存储的旧后台任务报告仍是当时生成的 HTML，新上传使用本轮展示。
- 主要文件：`apps/pages/views.py`、`templates/includes/upload_issue_report.html`、
  `templates/includes/upload_issue_groups.html`、`templates/pages/upload.html`、
  `static/assets/js/upload.js`。未改必填规则、编号算法、权限、用户原文件或数据库结构。

验证：

- 聚合、部分对象范围、单条对象直接展示与完成提示去重先验证旧实现失败，再修改通过。
  236 项相关 Django 测试通过；117 项 JavaScript／Chromium 测试通过，0 跳过。
- 真实 Chromium 连接隔离的本地 Django 测试库，上传原始 Data_Base_Cyclic.json，
  默认报告只有 213 个可见字符、两组修正；100 条对象明细保留，实际保存 0 条。
  同时测试展开明细、超长标题／identifier／位置、非法值原因和空文件。
  1280／1440／1920 桌面宽度均无横向溢出，无 JavaScript 异常；原附件没有修改或外传。
- 浏览器测试中发现公共 code 样式使超长位置撑宽，已在上传报告内限定宽度并允许换行，复测通过。
  截图与临时测试在本机 `/tmp/compact-upload-qa/`；日志为
  `/tmp/compact-upload-backend.log`、`/tmp/compact-upload-js-all.log`、`/tmp/compact-upload-browser.log`。
- 最后去除重复对象序号后，再跑 25 项报错／拆分测试及 1 项真实 HTTP 浏览器测试，26 项通过，
  见 `/tmp/compact-upload-final.log`；git diff 空白检查通过。
- 未扩大到无关搜索测试；上一轮确认的旧搜索样例测试问题仍见下方记录。
  Git 推送与 Render 完成部署必须区分。

### 9 月 28 日上一轮：描述字段按关键词识别并保留多值

- `processor_specification`、`processor_specification_of`、`Specifications of Processor`、
  `processorSpecificationOf` 等可满足处理器必填项；同时支持 CPU 的单数／复数别名。
  忽略大小写、分隔符、词序和简单复数 s；关键词须在同一个字段名、同一个父级。
- 描述类范围在 `apps/dyn_api/metadata_compat.py` 的 `DESCRIPTIVE_FIELDS` 明确列出：
  title、creator、creator_affiliation、date、rights、rights_holder、software、
  software_version、system、system_version、processor_specifications、input_path、
  results_path，以及各自 Schema 路径下的 phase_name、texture_type。
- 同一描述有 A、B 等多个字段时，只要至少一个有内容就满足必填；全部为空仍报错。
  不选一个值覆盖其他值。内部检索视图汇总不同内容，原字段名、值、列表顺序完整存储与导出。
  详情页所有原字段仍独立展示，匹配项放在对应 Schema 顺序位置，保持相对顺序。
  多标题、多材料名称在列表、详情标题及分享记录中正常显示，不露出 Python 列表写法。
- 完整标准字段名优先，较具体的已知名字优先：system_version 不算 system，
  creator_affiliation 不算 creator。一个名字同时指向两个不同要求时不替用户猜测。
  这与“同一要求有多个匹配字段全部接受”是两回事。
- 权限、单位、编号、结构、数值、载荷分量和曲线保持原识别／冲突校验；
  不把 origin.system 借给根 system，不把 Material 猜成 phase。
  对象拆分、上传反馈、搜索和 My Data 使用一致的描述识别规则。
- Ronak 原始 MD5 编号算法没有更改：仍按原字段名计算，不用新识别视图；
  新别名不擅自参与模板未指定的哈希项。合法自带编号、事务查重和整文件保存规则不变。
- 本地只读验证：a46fde6c.json 的 1 条对象通过；Data_Base_Cyclic.json 的 100 条均已识别
  processor_specification，仍各缺根 system、phase、units，且 total_strain 为空。
  原附件未修改，也没有为测试上传到线上。

测试与交接：

- 新测试先验证旧实现失败，再实现关键词匹配、多值、空值、同父级边界、权限／单位冲突、
  原样下载与搜索／展示。增加 100 条后台上传保留原值与真实计数的测试。
- 最终运行 461 项 Django 测试：459 项通过，剩余 2 项是下一条说明的旧搜索样例测试，
  本轮新增与受影响测试均通过。覆盖上传、后台任务、进度、整文件回滚、编号、权限、
  搜索、详情、图表与 CSV；日志 `/tmp/metadata-keywords-verified.log`。
  数据库迁移检查无变化，git diff 空白检查通过。
- 扩展回归发现两项已有搜索样例测试失败（共 10 个子例）：
  ExamplePresetSearchTests 把所有本机 example_json_files 文件当成相同的 GOSS 等固定样例，
  与后来放入的 Data_Base_Cyclic.json 内容不符。已在 HEAD 8a399ff 的独立临时副本复现相同失败，
  未为通过测试改动用户数据或搜索行为。基线日志 `/tmp/metadata-keywords-baseline.log`。
- 本轮不改 JavaScript、布局、数据库字段或依赖；Render 部署状态仍需与 Git 推送区分。

### 9 月 28 日上一轮：完全按 Ronak 原代码生成 identifier

- 已对照当日 MiMeDat `metadata_template.py`：先对副本执行相同的
  `remove_empty_entries`，按原 24 项 `mandatory_fields` 顺序拼接
  `json.dumps(value, sort_keys=True)`，再用 MD5 取前 8 位小写十六进制字符。
- 删除 SHA-256 内容指纹生成、base36 转换、编号逐位延长及旧指纹复用逻辑。
  编号完全由输入决定；碰到重复编号按原查重规则整文件拒绝，绝不覆盖已有记录。
  事务内全库复查、配额、通知回滚、逐对象进度和后台上传继续保留。
- 按用户“直接照搬”的要求，计算使用原始字段和值，不套兼容视图。
  大小写、CPU 别名、数值字符串和单项列表仍能通过上传识别，但计算编号时
  严格按 Ronak 原代码取字段、序列化，格式不同可能得到不同编号。
  模板 mandatory_fields 仍写 processor_specifications，CPU_specifications 不参与该项哈希；
  若所有必填字段都使用非标准名字，原算法会得到空输入的 MD5 前缀 d41d8cd9。
  未私自修正这些参考代码行为。
- Ronak 的清理代码会过滤列表中的 0、false、空字符串，已同样用于计算副本；
  原始 JSON、曲线零点和空可选项仍完整保存及导出。原文件不改动。
- 合法自带 identifier 继续保留；旧记录及 identifier_fingerprint 历史列保持原状，
  新上传该历史列为空且不读取它。旧数据去掉原编号再上传可能得到新的 MD5 编号，
  不再按旧 SHA-256 内容指纹去重。无新增数据库迁移或依赖。
- 主要代码：`apps/pages/upload_services.py`、`apps/pages/views.py`。
  README、AGENTS 和编号、原子保存、兼容上传测试同步更新。

本次验证：

- 先运行 Ronak 原代码取得固定预期值，再确认旧实现失败，修改后通过。
  合成标准样例的预期为 49793b40；另有 Unicode、数字字符串、包装和清理边界样例。
- 218 项上传、识别、校验、编号、原子保存、进度及后台任务相关测试通过。
  使用真实 MD5 前缀冲突的两组不同数据验证整文件拒绝、跨文件保留先前成功结果。
- 只读对照原代码与新实现：100 个合成对象全部一致，原对象均未被修改。
  附件 a46fde6c.json 两边重新计算均为 e40094c3；文件原有编号 a46fde6c 按规则保留。
  这个对照没有写数据库、改原文件或把私有文件上传到外部。
- 本轮只改后端编号计算，未改 JavaScript 或布局；未重跑无关前端测试。
  迁移检查无变化，git diff 空白检查通过；最终测试日志位于本机
  `/tmp/ronak-identifiers-verified.log`。本次推送后 Render 是否部署完成仍需另行确认。

### 9 月 28 日上一轮：CPU 别名和上传计数

**兼容两个处理器字段名，补齐旧上传通道的对象进度。**

- `processor_specifications` 和 `CPU_specifications` 都满足同一项必填要求，
  继续兼容大小写、分隔符和单项列表；原始字段名及值保存、导出不改写。
  两个名字同时提供且值不同仍报冲突，空值仍报错，不从其他父级借值。
  当时自动编号指纹也按同一字段处理（已由上方 Ronak 原算法替代）；
  详情页仍把 CPU 别名放到处理器字段位置、保留原名。
- 用户报告 `Sending files` → `Processing file 1 of 1` → 报错。
  已追踪到 NDJSON 回退通道：之前只发文件开始／结果事件，没有接入逐对象回调。
  此前只有后台任务路径有对象计数。用户使用本机还是线上尚未明确，修复覆盖两条路径。
- 现在 NDJSON 从实际检查和保存操作中直接发送 `file_progress`，显示
  `Checking n / total`、`Saving n / total`；总提示明确写 `Checking data objects`。
  后台任务继续用同一处理逻辑。最终行保留 `Checked n / total`，检查太快或有错误时也能看到总数。
  不加假动画、不回放计数、不故意拖慢；检查失败的文件不进入保存阶段。
- 检查和保存改成可迭代进度，原同步／后台接口通过同一消费函数执行。
  保存数只表示事务内进度，提交后才发 Uploaded；流中途关闭会立即关闭迭代器，
  回滚正在保存的文件及其通知，保留此前文件提交，所有批次预检、查重与配额复查不变。
- 新网页请求头带 `X-Upload-Progress: objects` 才收到对象事件；
  已经打开的旧网页继续收到旧文件事件，避免部署后把新事件误认成连接异常。
  无 JavaScript 的普通表单仍返回最终结果。NDJSON 仍不是后台任务，原有跨页后台机制未改。
- 主要文件：`apps/dyn_api/metadata_compat.py`、`apps/pages/views.py`、
  `apps/pages/upload_services.py`、`static/assets/js/upload.js`。
  无新增依赖、数据库迁移或用户数据修改。线上部署是否完成仍须另行确认。

本次验证：

- 430 项相关后端测试全部通过；117 项 JavaScript／Chromium 测试通过，0 跳过。
  另有 1 项临时真实 HTTP 浏览器测试通过，上述后端与临时测试合并运行共 431 项。
- Chromium 连接隔离的本地 Django，用 Ronak 原始 100 条文件上传：
  实际观察到 `Checking 0 / 100` 到 `Checking 100 / 100`，最终保留
  `Checked 100 / 100 · Not uploaded`；原有必填错误仍完整展示，数据库保存 0 条。
  1280／1440／1920 桌面宽度均无横向溢出，错误摘要在首屏，无 JavaScript 异常。
  临时脚本和截图仅位于本机 `/tmp/ronak-upload-diagnosis/`，未提交用户原文件。
- 验证了真实保存计数、整文件回滚、流关闭时通知回滚、旧客户端协议兼容、
  原始导出与 CPU 别名的自动编号去重；迁移检查无变化，diff 空白检查通过。

### 9 月 28 日上一轮：单项列表识别

**9 月 28 日后续：用户要求继续识别单项列表里的实际值，已实现。**

- 已知字段需要一个数值、字符串、布尔值或对象时，去掉外面一层或多层单项列表。
  例如 magnitude 的 `1.5`、`"1.5"`、`["1.5"]`、`[["1.5"]]` 都能读成同一个数值。
  数组中明确需要一个值或对象的条目也适用，units、张量和条件必填继续使用同一识别视图。
- 真正的曲线、尺寸、作者等数组保留数组含义；单点曲线仍是一个数组。
  多个值不会随便取第一个，未定义字段不擅自改结构。拆开后为空的必填值仍然报错。
- 包在单项列表里的 identifier 仍作为用户自带编号；普通上传、后台上传和最终事务
  都按同一个文本查重。自动补齐空编号时保留原有包装层数，并按最终 JSON 大小记账。
- 显式分享标记和用户名也支持包装；仍按完整权限词和实际用户名判断，不扩大权限。
  温度预设搜索能读取包装后的单位，同时保留最近上级单位和歧义拒绝规则。
- 原始 JSON 字段和值保留，JSON 下载不拆包装；内部识别供校验、搜索、绘图及 CSV 使用。
  实现在 `apps/dyn_api/metadata_compat.py` 和 `apps/pages/advanced_search.py`。
- 本次相关后端回归 **423 项全部通过**，包括后台 100 条混合包装对象、原子保存、
  查重、权限、空值、条件字段、张量方向、搜索、详情和导出。迁移检查无变化。
  本轮未改 JavaScript 或布局，未重复前端或全量后端测试；旧全量失败记录见下一节。
- 只读验证 a46fde6c 原件通过；在内存副本中给已知字段加多层包装也通过，
  识别后的值与原件一致，副本未被校验修改；未定义字段保持原结构。
  Data_Base_Cyclic 的 100 条仍因真实缺失／空值被拒绝。
  两份用户文件未修改、未提交、未上传外部网站。Render 部署尚未确认。

### 9 月 28 日上一轮：字段拼写及数值字符串

**9 月 28 日用户明确要求放宽格式识别，本次提交实现以下兼容规则。**
下面 9 月 27 日记录是上一轮实现，涉及严格字段拼写的描述以本节为准。

- 已知 Schema 字段在各自父级内忽略大小写和分隔符。例如 `Date`、`DATE`、`date`，
  `input_path`、`Input Path`、`input-path` 都能识别。记录拆分也使用同一规则。
- 已知数值位置接受有限数值字符串，包括 magnitude、张量分量和曲线数组。
  空格、换行、正负号和科学计数法可以识别；文字、带单位的数值、NaN、Infinity 等不会当作载荷数值。
  Schema 中明确列举的值也兼容大小写和首尾空白。
- shared_with 支持 `"all"`、`["all"]`、`"c"`、`["c"]`、原有权限对象，
  以及独立的 `{"all": true}` 标记。仅 username 的对象按私有分享处理。
  权限按完整值匹配；`not all`、说明里的 all、用户名中的 all 不会把数据公开。
  同名用户 all 仍可作为私有分享对象。既有权限限制和用户名检查不变。
- 原始字段名、值和数组顺序仍保存于 JSON，JSON 下载也保留原样；新增的是内部识别视图。
  搜索摘要、My Data 筛选、详情曲线、边界载荷、CSV、分享通知都使用识别结果。
  元数据标签仍显示原字段名。已有明确路径的高级搜索仍读取原始路径。
- 不猜同义词、不挪动不同父级的字段，不把 Material 自动当成 phase，
  也不把 processor_specification 自动补成 processor_specifications。
  真正缺失或为空的必填字段仍报错。同一字段的两种拼写若值冲突，整份文件拒绝保存。
  冲突字段含非法 Unicode 时也能正常返回错误，不会让报错页面本身失败。
- 主要实现：`apps/dyn_api/metadata_compat.py`、`helpers.py`，以及 upload_unwrap、
  upload_services、views、详情排序与模板。没有新增依赖，也没有启用完整 Schema 校验。
- 新增迁移 `0014_jsondata_identifier_lookup`，用内部摘要匹配不同拼写的 identifier 字段。
  原编号文本和 JSON 不变，编号值仍区分大小写；重复编号及最终事务复查保留。
  旧记录的标准 identifier 字段有 JSON 查询回退，不需要改写历史 JSON。
  本机 DEBUG=True 的 SQLite 已应用迁移，其他电脑须按 README 运行 migrate。

验证结果：

- 上传、必填、编号、权限和详情相关后端回归 **297 项通过**；
  搜索及兼容流程回归 **123 项通过**（与上一组有部分重复）；前端 **114 项通过、0 跳过**。
- 全量后端 **731 项**仅剩已知的 **11 个旧失败子案例**：一个旧 logout 预期，
  两个搜索样例方法对本地 cyclic 文件的假定。追加的非法 Unicode 回归包含在最终 297 项通过中，
  预设搜索对点号等分隔符的匹配回归包含在最终 123 项通过中。
  本轮未改动登录流程，也未为旧样例测试修改搜索行为。
- 后台 100 条不同拼写的合成对象全部检查、保存成功，原始 JSON 保持不变。
  已验证普通上传、CSV、JSON 下载、My Data、搜索、跨用户权限、冲突字段及最终重复编号检查。
- 只读检查用户原文件：a46fde6c.json 识别 1 条并通过；Data_Base_Cyclic.json 识别 100 条，
  数字字符串、Date、input-path、results-path 和共享简写问题消失。
  仍有 system、processor_specifications、phase、units 缺失，以及 total_strain 为空；全部不保存。
  两份用户文件均未修改、未提交、未上传到外部网站。
- makemigrations 检查无遗漏，git diff 空白检查通过。Render 部署及线上效果尚未确认。

### 9 月 27 日上一轮实现

**9 月 27 日用户已明确授权“改上传这部分”，本次提交实现下方新规则。**
此前首页账户菜单、助手范围、图表和详情页、CSV／ZIP 导出继续保留。
下文 9 月 25 日“尚未授权／尚未修改”属于历史排查记录，以本节的新状态为准。

Ronak 原始 `Data_Base_Cyclic.json` 现在能拆成 100 条对象，逐条返回字段错误，保存 0 条。
她的旧字段名、缺失字段、空 total_strain 等仍需由数据提供者修正；本轮没有改动原文件，
没有猜测单位、自动改名、把 plastic_strain 代替 total_strain 或将文件发送到线上／外部校验网站。
当时线上为何没看到报错仍未证明，不能把这轮修复说成找到了旧线上故障的唯一原因。

### 9 月 27 日上传规则与实现

- `apps/pages/upload_unwrap.py` 根据字段和结构寻找记录边界，支持单条、列表、编号字典和多层集合。
  已认出的记录停止拆分，内部 data、phase 等保持原样；不完整和标量集合成员保留报错。
  预检仅保留路径，仍逐文件释放解析数据，并在任何保存前检查批次数量。
- `apps/dyn_api/required_schema.py` 使用 `jsonschema==4.26.0` 执行**必填字段规则**，
  包括子字段、条件必填和到达这些字段所需的容器类型，**不是启用完整 Schema 的所有类型、枚举、数值约束**。
  三份可信 Schema 位于 `apps/dyn_api/schemas/`，来源的固定提交与 SHA-256 见 `sources.json`。
  主 Schema 是 MiMeDat 1.2.0；不访问上传内容中的 `$schema` URL，额外字段仍允许。
- 24 个顶层必填字段不变，沿用原 identifier 指纹输入。所有实际必填字段都不能为 null、
  空字符串、纯空格、空列表或空对象；0 和 false 不算空。可选空值保留，不因空值拒绝上传。
  可选父字段有内容时检查子项；条件字段存在且匹配时启用条件必填。
  mechanical_BC.applied_load 仍可不提供，但提供的每条载荷必须有非空 magnitude。
  thermal_BC 的 loaded 条件要求 loading_mode 和 applied_load；张量分支要求六个分量。
  不额外强制 equivalent_strain；total_strain 本身不能是空对象。
- 整文件原子保存不变：100 条里 30 条有错，100 条都不入库。全部对象检查完后集中报错。
  其他文件独立处理；identifier 生成、防重复、权限和配额最终复查继续保留。
  没有新增 u／g 分享功能，原有 all／c 与 username 权限规则保持不变。
- 后台 UI 显示真实 `Checking n / total`、`Saving n / total`，这两步不转圈，不人为拖慢。
  保存回调记录已处理数量，但只有整文件事务提交才显示 Uploaded。
  私有暂存目录中的 `save-progress.json` 让其他页面能在事务提交前读到进度；
  其中没有用户数据，读取检查 claim token 和文件状态，失败／中断后的数据库结果优先。
  普通表单和 NDJSON 回退保留，回退仍按文件显示 Processing，未伪造逐对象数字。
- 错误结果移到按钮下方、额度上方。多条错误默认折叠，展开后按原顺序显示所有字段、位置和来源路径。
  路径与标题等都转义，非法 Unicode 的包装键也能正常返回错误。
- 上传测试改用 `upload_test_data.py` 的合成数据，identifier 测试不再依赖未同步的私人样例文件。
  指纹和 base36 预期值随合成样例更新，算法未改；预期 SHA-256 另用 Node 独立计算核对。

### 本次验证与已知旧测试问题

- 上传、必填、identifier、配额、原子保存、共享、切页相关后端测试：246 项通过；
  `node --test tests/js/*.test.cjs`：114 项通过，0 项跳过。
- 原始 Ronak 文件的后台、普通表单、NDJSON 路径及内部检查共 4 项临时测试通过；
  原文件后台准确显示 checked 100／100、失败对象 100、saved 0，单次本地约 0.6 秒。
- Chromium 连接真实本地 Django 上传原文件，1280／1440／1920 桌面宽度检查通过：
  无横向溢出，错误摘要在首屏可见，展开包含 100 条错误，无 JS 异常。
  图片和临时脚本位于 `/tmp/ronak-upload-diagnosis/`，不会通过 Git 同步。
- 迁移检查无变化。这次有新增 Python 依赖，另一台电脑请更新 requirements.txt 中依赖。
- 全量 714 项运行仍有 11 个失败子案例，来自 3 个旧测试方法：
  ORCID onboarding 对 `/logout/` 的旧退出预期；两个搜索样例测试假定全部本地文件都具有旧样例的相同值。
  加入 Ronak cyclic 文件后该假定不成立。已在原 HEAD `f577399` 的独立临时副本复现完全相同的 11 个失败。
  未为本次上传修改无关的登录／搜索行为，也不要宣称全量全绿。

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
   9 月 25 日工作目录为 `/home/users/xuejungs/Projects/database-manager-ui`，
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
   用户提供的 `example_json_files/Data_Base_Cyclic.json`、`a46fde6c.json` 及 `a46fde6c1_public.json`
   属于被 Git 忽略的本地样例；笔记本没有时需另行复制，不能认为拉取仓库就会出现。
   当前最重要的是 `Data_Base_Cyclic.json`，请用户带上这份附件或另行复制；不要为同步而提交私人样例。
   原样例路径不可读而跳过，表示那次测试没有读取成功，不代表样例已验证。
6. 用户偏好中文简短直接沟通，UI、代码注释和 docstring 保持英文。
   明确的小修改直接完成、验证、检查 diff，然后 `git add .`、commit、push；
   不反复索要常规确认，不提交凭据或无关修改。不要把推送状态说成部署状态。
   **提问、讨论和“先看看”不等于授权改代码。** 用户明确反对尚未说明需求就开始修改；
   已经明确要求做的改动再直接完成，不要把这个偏好解释为每一步都要审批。

## 最近完成的提交

| 提交 | 内容 |
| --- | --- |
| `ca10ba7` | 上传框缩到 200px 最小高度；Checking 只留文件旁边；删除重复失败句 |
| `c3c9be4` | 同类错误合并为修改清单，完整对象细节可展开，最终结果不重复 |
| `8ad5a4b` | 描述字段按同字段内关键词识别，多候选有内容即满足，原值全部保留 |
| `8a399ff` | identifier 生成完全采用 Ronak 模板的 MD5 前 8 位算法 |
| `e3a40d9` | CPU 别名和真实对象 Checking / Saving / Checked 计数 |
| `052a04d` | 在已知字段位置识别单项列表包装，保持原始 JSON |
| `4afb994` | 首页页头／页脚头像菜单：Account details、Enter platform、Log out；POST 退出回首页 |
| `b947e46` | 助手只出现在登录后的平台内部；首页、登录和注册页不显示 |
| `18d573b` / `2d9e33e` | 首页登录后显示头像；未登录页头及页脚显示 Register / Login，页脚入口居中 |
| `18eeff7` / `5fecdec` | 首页专注平台介绍，主按钮 Get started；保留最终登录状态规则，勿恢复中间方案 |
| `cf906d0` / `27cdf41` | 登录后也能回首页；侧栏 logo 可回首页，不增加 Home 菜单 |
| `0467007` / `41865f1` | 详情页字段宽度和嵌套间距；展开的数值数组横排并自然换行 |
| `75b43c5` | 整块 RVE 的 stress/strain 张量载荷，按分量／步骤展示，不猜方向箭头 |
| `10d2dc6` / `960cb80` | 图表及 PNG 去标题；放大坐标标题，从 units 取单位，无量纲应变显示 (-) |
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

## 9 月 25 日历史排查：实际文件与 Schema 校验

### 用户最近的问题和已解释的区别

用户先问失败原因，随后问应该自动识别旧格式还是提示用户按模板调整、平台是否用 JSON validator、
外部 validator 检查什么，最后问之前详情页是不是已整理了所有必填字段和子字段。
用户明确提供的参考是 MiMeDat `main` 中的这两个文件：

- [metadata_template.py](https://github.com/Ronakshoghi/MiMeDat/blob/main/metadata_template.py)
- [microstructure_sensitive_mechanical_metadata_schema.json](https://github.com/Ronakshoghi/MiMeDat/blob/main/microstructure_sensitive_mechanical_metadata_schema.json)

已向用户说明：文件能解析、满足 Schema、满足平台权限和重复检查、科学数据正确，是不同的事。
当前上传使用自写的顶层字段校验，并未调用完整 JSON Schema validator，也没有向外部校验网站发送文件。
完整校验可以在服务器内部完成，无须用户手工去外部网站，也无须上传私人数据给外部网站。
本机项目环境检查发现没有 `jsonschema` 包，`requirements.txt` 也未添加它；本轮未安装或接入。

建议过的方向是：明确能拆分的打包形式可支持；字段和实值按统一规则检查，对旧写法给修改建议，
不要静默改字段、猜单位或编造数据。**这只是建议，用户尚未确认实施范围。**
用户说“现在不知道该做什么”，后续交流应白话、直接、少给分叉选项，先沿用已有整理核对规则。

### 原文件的可重复结论

原文件目前在本机两个位置，SHA-256 相同：

- `/home/users/xuejungs/Projects/database-manager-ui/example_json_files/Data_Base_Cyclic.json`
- `/home/users/xuejungs/Desktop/Data_Base_Cyclic.json`
- SHA-256：`383720d09b0732e81cc352f9464c6d5310e40a0d3cd50b27bbddc4ec5dc86604`

文件共 7,931,670 字节（7.56 MiB），JSON 语法可解析，100 条对象全放在一个顶层字典中，
形如 `{ "编号": {对象}, ... }`；每个外层编号与其内部 identifier 一致。
文件没有换行，约 793 万字符在一行；编辑器可能卡顿，本机也未查到 JSON 默认打开程序。
这解释了双击不便的可能因素，不能说文件因为 100 条就过大或损坏。

当前 `_inspect_upload_file` 只拆列表或 `{"data": [...]}`，普通字典视为单条对象。
因此原文件会被当成 1 条，报告缺少全部 24 个顶层必填字段，保存 0 条。
即使在临时测试中只拆成 100 条、不改内部内容，全部对象仍有以下平台校验问题：

| 问题 | 原文件情况 |
| --- | --- |
| 7 个顶层必填字段未按当前名称／位置提供 | `date`、`system`、`processor_specifications`、`input_path`、`results_path`、`phase`、`units` |
| 旧字段写法 | `Date`、`processor_specification`、`input-path`、`results-path`、`Material` |
| system 的位置 | 在 `origin.system` 中有 Linux，顶层没有；不能未经确认把来源机器等同于当前计算机器 |
| 单位的位置 | 在 `Material.constituitve_model.units` 中有 Stress/Stiffness MPa，顶层 units 没有；不是完全没单位，但不能据此补齐所有单位 |
| 空值 | 100 条的 `total_strain` 全是 `{}`；有 `plastic_strain`，不能拿它冒充总应变 |
| 共享结构 | 100 条都是 `shared_with: ["all"]`，当前平台和所查 Schema 要求列表项为对象 |

当前规则下，整文件原子失败是预期；这些结论不是完整 Schema 校验的全部错误清单。
源文件的某些载荷值还是字符串／数组，Schema 对应字段要求数字，完整校验会进一步发现此类差异。
本轮没有转换、补齐或修改这份原文件，也没有把它上传到线上或外部校验网站。

### 9 月 25 日实际验证证据

在 DEBUG=True、隔离 SQLite 测试库和临时上传目录中验证，未使用生产数据库：

- 原文件普通表单与 NDJSON 上传均返回明确失败，保存 0 条，单次约 0.32 秒。
- 后台任务路径原文件计数为 1，拆包临时版本计数为 100；均返回文件失败及错误报告，约 0.35 秒。
  任务 `completed` 只表示处理结束，不等于其文件 `uploaded`。
- 逐条检查确认上述 7 个缺字段、空应变和共享格式错误均涉及全部 100 条。
- 现有合成数据的 100 对象后台成功保存测试也通过；不能据此声称原文件可以成功上传。
- 以上 4 个临时诊断测试及 1 个现有控制测试共 5 项通过。
- 另用真实 Chromium 连接 Django 临时 LiveServer 上传原文件，1 项通过：
  Waiting / Upload → Uploading… → Failed，页面显示保存 0 条及缺字段报告，无 JS 异常。
  在 1440×1000 下结果提示位于页面偏下；提示不够醒目，但不能据此证明她旧截图的具体故障。
- 她的旧截图只有 Waiting，不能证明请求已发出或服务器已收到；当时“没有任何错误”的线上原因仍未确认。
  不要让用户再次寻找此前已无法翻出的旧日志，也不要直接断言 Render 超时或文件太大。

临时测试、报告和截图在 `/tmp/ronak-upload-diagnosis/`，不会随 Git 同步。
其中 `ronak_upload_diagnosis.py`、`ronak_upload_browser.py` 是临时测试，不是项目测试模块。
新电脑可按上述步骤重建诊断，不要直接执行依赖本机 `/tmp` 或 cookie 的路径。

### Schema 与模板本身的差异：需要明确，不应擅自决定

9 月 25 日读取 MiMeDat main 原文，Schema 标注 version 1.2.0；仅下载、解析源码，未执行远程 Python。
发现：

1. `Dict_Test` 使用 `CPU_specifications`，但同脚本 `mandatory_fields` 和 Schema `required`
   使用 `processor_specifications`。模板中的这处名称没有统一。
2. Schema 根级要求存在 `total_strain`，但该对象内部 `required: []`、没有 `minProperties`，
   所以 `{}` 符合这部分机器规则；文字 description 又称必须含等效应变。`stress` 也有相似矛盾。
   当前平台拒绝空的必填容器，比这部分 Schema 机器规则更严格。
   **已向用户纠正：空应变会被当前平台拒绝，不代表一定过不了她的 Schema。**
3. Schema 的顶层 units 要求 Stress、Strain、Length、Force、Angle、Temperature 六项；
   default 是文档默认值，不是有权自动补全用户物理单位的依据。
4. Schema 共享支持 c/u/g/all 与 access_list；当前平台是 all/c 加 username，未实现组共享。
   接入完整校验时需要单独核对平台权限语义，不能为了“符合 Schema”把私有数据自动变成公开。
5. 模板清理函数会删除空容器；模板是填写辅助，并不能保证填写／清理后的内容通过 Schema。

本轮只做源码对照，没有实际运行完整 JSON Schema validator。原始下载在
`/tmp/mimedat-schema-review/`，未加入仓库。继续时若需完整校验，应固定可信 Schema 版本并处理其引用，
不要自动请求用户 JSON 内任意 `$schema` URL；展示排序清单中的版本是已固定的旧快照。

### 用户最后问：之前详情页是不是已经统计好了

已检查当前代码、Git 历史和交接：

- `apps/pages/detail_metadata.py` 的 `DETAIL_FIELD_ORDERS` 整理了顶层／子字段和展示顺序，
  包含必填及可选字段，**不是嵌套必填规则表**。文件注释明确仅用于展示、不校验数据。
- `apps/dyn_api/helpers.py` 的 `REQUIRED_TOP_LEVEL_FIELDS` 是 24 个顶层必填字段，已用于上传；
  identifier 可由平台生成。它与当前 Schema 根级 required 去掉 identifier 后的字段一致。
- 历史 `2803c41` 曾按 mandatory_fields 排序；最终已改为 Schema properties 顺序，
  不应恢复“必填都在前／其他放 Additional”，也不能把展示表所有子字段都判为必填。
- 未找到已接入上传的“所有层级必填及条件规则表”。必填子项常只在其父对象存在时才适用。
- 已回复用户：**不用从零整理字段；已有展示与顶层检查，缺的是完整子字段和条件规则的上传校验。**

接下来先接住用户的进一步决定。若授权实施，建议先定上述矛盾的处理、采用的 Schema 版本和共享范围，
再加入按对象的 Schema 校验、准确报错、需要的明确拆包支持及实文件测试。
不要把“用户让看两个参考文件／让写交接”当成已授权更改所有上传规则。

## 9 月 25 日界面改动的最终状态

- 首页对登录和未登录用户都可访问，回首页保留登录；侧栏 logo 回首页，无额外 Home 菜单。
- 未登录时：首页页头及页脚明确显示 Register、Login 两个按钮。
- 登录时：这两处改成单个头像，点击展开用户名及 Account details、Enter platform、Log out。
  菜单支持点外面关闭、Esc 关闭并回焦点、键盘进入；页脚向上展开。
- 首页退出用带 CSRF 的 POST，回首页并显示 Register/Login。`home_logout` 对应 `/logout/`；
  避开 admin_datta 同名 logout 的反向解析冲突，现有平台内部退出链接未在本轮改造。
- 页脚账户入口居于品牌介绍和右侧 PLATFORM 栏之间。首页中部 Get started：游客去注册，登录用户去搜索。
  不恢复独立 Enter platform 顶部按钮，不在介绍首页增加上传等业务操作。
- 助手只在已登录的平台内部显示，首页（无论是否登录）、登录和注册页均不显示。
- 详情页字段宽度／嵌套间距已改善；数值数组展开后横排并自然换行。
- 曲线无图标题（PNG 也无）；轴标题放大，从 units 取单位，Strain 的 1 显示为 (-)。
- 整块 RVE tensor loads 按步骤和分量展示，保留传统节点载荷；不把张量猜成方向箭头。

首页菜单关键文件：`templates/includes/landing_account_actions.html`、`templates/pages/index.html`、
`static/assets/js/landing-account-menu.js`、`apps/pages/urls.py`、`apps/pages/tests.py`。
助手关键文件：`templates/includes/footer.html`、`scripts.html`、`layouts/base-public.html`、
`apps/pages/test_assistant_widget.py`。

最近菜单改动验证：8 项 Django 测试（含临时页面生成）、113 项现有 Node 测试全部通过且无跳过；
另有真实 Chromium 在 1280/1440/1920 下 82 项检查，包含页头／页脚、游客状态、长用户名、键盘关闭和无助手。
退出测试验证 CSRF、GET 405、会话清除、返回首页及退出后数据页要求登录。
临时界面测试位于 `/tmp/assistant-global-qa-DHmXrj/`，不在仓库；不要把历史检查说成当前新修改的验证。
本次交接只做文档与 Git 检查，不重跑应用测试。线上部署完成状态未核实。

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
2. **9 月 25 日已拿到原文件并查清当前平台拒绝原因，尚未修改上传逻辑。**
   `Data_Base_Cyclic.json` 的编号字典未被拆分，内部还有旧字段、缺字段、空值和共享格式问题，详见上方新排查。
   当时“没看到错误”的线上原因仍未确认；Waiting 截图不能证明请求已发出。
   100 个对象低于每次合计 1,000 的限制；JSON 深度是嵌套层数，不是对象数量。
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
- 缺失、null 或空白时，完全照 Ronak 模板的清理、取字段、序列化和 MD5 前 8 位生成。
  不做 base36 转换或冲突延长。合法自带文本 ID 保留，格式错误或首尾空白要报告。
- 历史 SHA-256 指纹列保留但不再生成或读取；已有 identifier 不自动重算。
  顶层可选字段不参与编号计算，原始数据不受计算副本清理影响。
- 全库和上传批次都检查重复；最终查重与配额记账在事务锁内完成。
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
2. **下一轮专注 Charts。** 先看上面的 Charts 接手入口，再听用户具体要调整什么；
   讨论时先白话解释，要求明确后再实施，不将“接着弄 Charts”扩大成整体重构。
3. 上传最新界面调整已完成、验证并推送，不重复实现。新反馈涉及上传时，沿用当前字段识别、
   原始数据保留、按文件保存和精简提示规则；不要自动修改 Ronak 的原文件来凑齐字段。
4. 如核对线上问题，先确认 Render 部署提交。Git push 成功不证明部署完成，也不证明线上行为成功。
5. 本机 `/tmp` 下日志和截图只是上轮验证证据，不随 Git 同步。新聊天或新电脑需重新核实环境和数据。
6. 科学公式、扩容入口、索引搜索、收费基础设施、AI 和知识图谱没有新修改指令，勿自行展开。
