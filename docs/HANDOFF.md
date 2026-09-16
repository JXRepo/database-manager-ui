# 工作交接

更新：2026-09-16。分支：`main`。最近功能提交：`7fc1121`。

## 接手先看这里

这是给另一台电脑上的 Codex 的进度记录，不是聊天记录的自动同步。
先读 [AGENTS.md](../AGENTS.md)，检查本机 Git 状态和最新提交，再根据用户接下来的要求继续。不要重复实现已完成的功能。

- 项目：Django FAIR 材料模拟数据平台，供少量研究用户试用。
- 试用网址：https://fair-materials-data-hub.onrender.com/
- 仓库：`JXRepo/database-manager-ui`；Render 部署 `main`，数据库为 Supabase PostgreSQL。
- 最新功能代码已推送；本轮没有核实 Render 是否已部署完成，不要把推送成功说成上线验证成功。
- 本轮没有未完成的功能修改；现在只是换电脑继续工作。

## 用户的工作习惯

- 用户不熟悉开发操作，解释用简短中文，界面文字保持英文。
- 按用户明确要求直接修改并验证，不要每一步重复询问；不要自行扩大功能范围。
- 用户要求修改完成后代做 `git add .`、有意义的 `git commit -m "..."`、`git push`。先检查改动，避免提交密码或无关文件；不要强制推送。
- 重视实际交互质量、清楚的错误提示、紧凑布局；不要堆长说明或大幅重新设计。
- README 已注明基于 Ronak Shoghi 的 DatabaseManager **web application**，不要改称 prototype。许可证及第三方声明已有文件，不要重新选择许可证。

## 最近完成的搜索功能

1. 主搜索框：空格分隔的词必须全部匹配，词序无关，忽略大小写。
2. 高级搜索分两块，所有条件为 AND：
   - Common filters：Identifier、Creator、Software、Phase、Owner、Access、Title。保持这套，不新增软件版本。
   - Data field filters：来自 Ronak 的 11 个专业参数，不再扫描所有 JSON 字段，也不混入 Owner、软件版本等通用信息。没有数据时仍显示预设选项。
3. Match 按类型限制，前端与后台都检查：
   - 数值：`Element_Number`、`Grain_Number`、`Scaling_Factor`、`Max_Total_Strain`，支持等于、大小、包含端点的范围比较。
   - 文本：`Hash_Orientation`、`Texture_Type`、`Load_Type`、`Stress_Type`、`Load_Descriptor`、`Hash_load`，支持 Contains words 和 Equals text。
   - 数组：`Material_parameters`，支持文字及数值比较；数值比较针对数组中的单个数字，界面有提示。
4. 最多 10 个字段条件。新字段按完整 JSON 键名递归查找、忽略大小写；旧 URL 的 JSON 路径仍只匹配原位置。错误条件保留供修改，不悄悄改变条件或放宽结果。
5. Live Data Objects：后台只返回最新 20 个 **Public** 对象。自己的 Private、别人共享给你的 Private 都不显示。页面可见时每 5 秒刷新，列表最高 280px，超出滚动；卡片不撑满屏幕，已检查手机长标题。
6. 普通搜索仍能找到自己的、Public、明确共享给自己的数据。实时列表的 Public 限制不影响 My Data、搜索结果和详情权限。

之前已完成注册校验、ORCID 绑定与解绑、ORCID 账号首次补设用户名和密码，以及 Remember me。普通登录固定 30 天，勾选后采用 365 天滚动续期，并非绝对永久有效。细节见 [README](../README.md)，不要因换电脑重新改动这些约定。

## 主要文件与验证记录

- `apps/pages/advanced_search.py`：字段类型、Match 规则、条件解析与匹配。
- `apps/pages/views.py`：`search_view` 和 `search_live_data_objects_view`。
- `templates/pages/search.html`、`static/assets/js/advanced-search.js`：界面、布局及动态条件。
- 测试：`apps/pages/test_advanced_search.py`、`apps/pages/test_advanced_search_engine.py`、`apps/pages/tests.py`、`tests/js/*.test.cjs`。
- 最近验证：全量 Django 422 项通过；随后补了空 Match 回显测试，相关 Django 68 项通过；最终 Node 测试 34 项通过，无跳过。桌面、手机浏览器验证和独立代码审查已完成。
- 已知测试警告：本机没有 `staticfiles/`，不影响上述测试。手动浏览器验证用隔离的合成数据，没有改线上用户数据。
- 本次交接仅修改文档，不把此前的测试记录说成本轮重新运行的结果。

## 笔记本如何续上

1. 已有仓库：先检查 `git status`，工作区干净时执行 `git pull --ff-only`。没有仓库则克隆 `https://github.com/JXRepo/database-manager-ui.git`。有本机改动或分支分叉时先检查，不强制覆盖。
2. 本机启动、虚拟环境、依赖和 Windows 命令见 [README Local Setup](../README.md#local-setup)。以笔记本实际解释器为准；Render 使用 Python 3.12，本机上次测试环境是 Python 3.10。
3. `.env` 不随 Git 同步：参考 `env.sample` 配置本地 `DEBUG=True` 和本地密钥，使用 SQLite。不要把 Supabase 生产密码写进交接文件，也不要连接生产库来跑测试。
4. 本地执行 migrations 后用 `manage.py runserver 127.0.0.1:8001` 启动。笔记本、本机、线上账号和数据不自动同步；本地测试可以重新注册。ORCID 本地调试需单独的回调配置，普通开发可用用户名密码。
5. 后端改动运行相关 Django 测试；前端改动运行 `node --test tests/js/*.test.cjs`，需要支持全局 WebSocket 的 Node 和 Chromium。没有浏览器或测试被跳过时要如实说明。

下一步：先向用户简短确认已读到最新进度，按用户晚上提出的下一项要求继续；若用户要看刚才的线上效果，先确认 Render 部署状态，再检查 Match 和仅 Public 的紧凑列表。不要自行开启新的大功能。
