# Blender 短剧视频反推 3D 白模系统

本项目以 Blender 5.1.2 为主控，用已有短剧视频反推可编辑的 3D 白模分镜，并通过 Eggfans API（`https://api.eggfans.com`）调用 Seedance 2.5 等视频模型进行二次渲染。

## 文档入口

- [需求规格（PRD）](docs/01-prd.md)
- [总体技术方案](docs/02-technical-plan.md)
- [交互与数据流程](docs/03-interaction-flow.md)
- [分阶段交付计划](docs/04-delivery-plan.md)
- [接口与数据契约](docs/05-data-contract.md)
- [Eggfans API 接入说明](docs/07-eggfans-api.md)
- [白模仓库、精细度优化与复核范围](docs/09-whiteblock-library.md)
- [仿真人白模与 Blender CLI / MCP 使用](docs/10-human-whiteblock-blender-integration.md)
- [测试与验收清单](checklists/acceptance-checklist.md)
- [风险与回滚登记表](docs/06-risk-rollback.md)
- [Git 代码备份与恢复范围](docs/11-git-backup.md)

## 目录约定

自动转换统一写入项目根目录的 `output/`：`output/input/` 原始视频（默认只读）；`output/projects/` 项目 JSON；`output/cache/` 跟踪和姿态中间产物；`output/exports/` 白模工程、视频、参考帧和 Seedance 请求包；`output/models/` 本地模型；`output/logs/` 日志。手动新建项目时，工作区使用你在对话框中选择的目录。

## 当前一键白模能力

桌面“一键转换白模”会在本地分析镜头和人物姿态，调用本机 Blender 创建可编辑的人物代理动画，并输出保持原片比例、帧率和时长的白模预览。所有产物保存在项目 `output/` 下，完成后自动进入“白模仓库”。仓库支持历史完整视频和单镜头的缩略图、搜索、软件内播放与拖动进度，以及继续编辑项目、打开 Blender 工程和文件夹；索引与缩略图保存在 `output/library/`，视频保留在原有导出批次目录。

新版默认 `human_v3`：使用连续的 CC0 人体网格、164 根骨架、混合蒙皮、细分表面、世界/画面关键点驱动和逐帧网格复核，再用 EEVEE 输出白色人物预览。旧部件白模可在设置中选择 `mannequin_v2`。人物深度、相机、遮挡和完整场景仍需复核，旧结果不会自动覆盖。

群演镜头会先用本地 YuNet 头部定位锁定人物轨迹，再用 MediaPipe 姿态；短暂漏掉身体关键点时，系统保留连续人体网格并以 `pose_source=anatomical_prior` 标记补全帧。人物离开画面时人体和骨架同步隐藏，不会留下单独骨架。YuNet 模型及许可证清单在 `output/models/yunet/`，不上传视频；群演身份、遮挡关系和深度仍需人工复核。

仓库“连接 Blender / Agent 修正”会连接软件内置 MCP，可查看场景、跳帧、调整手脚 IK 和相机、切换人体轮廓、另存并重渲染。Agent 示例：“查看场景”“把 Actor_01 的左手放到胸前”“检查穿模”“重渲染”。修订单镜头会另存入库，原完整视频保留。无需用户安装第三方 MCP 编码插件。

### 人物模板确认（必须先做）

在“人物与模板”页按镜头逐个人物填写角色名，并选择“男型”“女型”或“中性”。系统只保存用户明确选择或角色资料提供的模板，**不会根据脸、服装、体型或原片画面自动判断性别**。分析新视频时人物默认是“中性 / 待确认”；角色编号只在当前镜头内有效，不能当作跨镜头身份匹配。

保存选择后，人物状态会变为“待重渲染”，旧视频仍保留但不会被请求包标记为可直接使用。点击“应用并重渲染当前镜头”，或对 Agent 说“把 Actor_01 设为女型并重渲染”。Agent 会按“保存模板 → 连接 Blender → 另存修订 → 渲染”的顺序执行；任一步失败会停止后续操作。新 `.blend`、MP4、质量报告和 JSON 都记录 `body_template`、`template_confirmed`、`template_source`、`role_name`。模板变化后仍需复核比例、接触和穿模。

当前为近似人物白模，相机和深度未做真实求解，背景、道具、遮挡和人物局部需人工复核。无可靠人体姿态的镜头会明确标记，不能算完整场景重建。详见 [本地原片测试与边界](docs/08-local-video-test.md)。该流程不上传原片、不调用 Eggfans。

## 当前可执行离线闭环

项目已提供不联网的项目初始化和白模场景脚本生成器。它不会启动 Blender、上传素材或调用 Seedance：

```text
D:\Python\python.exe -m whiteblock init <视频路径> --project-id demo --end-frame 900 --project project.json
D:\Python\python.exe -m whiteblock build project.json --out exports
```

`exports/` 会生成每个镜头的 `.scene.json`、可在 Blender 5.1.2 中复核后执行的 `.blender.py`，以及带 SHA-256 的 `shot-manifest.json`。初始化通过 ffprobe 读取媒体信息，也可显式指定帧数与帧率；桌面一键转换继续完成本地镜头切分、姿态分析和实际渲染。

## 桌面端与 Agent 控制层

双击 `launch_whiteblock.bat`，或运行 `D:\Python\python.exe -m whiteblock desktop` 打开桌面控制室。启动脚本会探测本机 `BLENDER_BIN`、PATH 和常见 Blender 安装目录，并把路径传给桌面端。桌面端覆盖项目、视频/镜头、白模生成、离线请求包四个阶段；右上角 `Agent 控制台` 是可拖动悬浮操作员，支持“查看状态”“生成白模”“运行 Blender”“选择镜头 shot_001”“生成 Seedance 请求包”“保存项目”等指令。

白模实际创建分两步：先生成 `.blender.py` 场景脚本，再由“运行本地 Blender 创建 `.blend`”按钮或 Agent 的“运行 Blender”调用本机 Blender 的后台模式执行。一键转换会连续完成这两步并渲染预览。Blender 路径可在“连接与设置”中配置，也支持 `BLENDER_BIN` 和常见安装目录探测；没有 Blender 时会明确报错。

首次使用桌面端时打开“连接与设置”：填写 Eggfans Base URL、`/pricing` 路径、模型 ID、API Key 和本地 Blender `blender.exe` 路径，点击“保存设置”。首页“一键转换白模”会自动选择视频、创建项目目录、探测媒体、分析姿态、生成场景脚本，再调用 Blender 创建 `.blend` 和完整预览；开始前检查 Blender、ffmpeg 与 ffprobe，缺失时提示配置后再转换。Eggfans “测试 /pricing 连接”只在用户点击后访问配置的 pricing 地址，实际提交接口仍需依据 Eggfans 契约确认。

Agent 默认使用本地工具解析，不联网。启用在线 Agent 后，它复用“连接与设置”中 Eggfans 的 Base URL、API Key 和鉴权头，并使用同一 Eggfans 通道下的 Agent 对话模型，通过 `/v1/chat/completions` 规划工具；只需填写一套 Eggfans 凭证。模型只能规划已注册的项目工具，不能访问编码工具。真实媒体上传和 Seedance 提交仍没有注册为工具，必须由后续明确授权和契约实现。

Agent 也可在用户明确说“运行 Blender”后调用已生成的脚本；Blender 路径优先取项目设置，其次取 `BLENDER_BIN`，找不到时会返回明确错误，不会伪造成功。
