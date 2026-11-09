# 交互与数据流程

1. 新建项目并选择 S 盘目录，检查 Blender、ffmpeg 和可选姿态模型。
2. 导入视频，显示分辨率、帧率、时长、音轨和哈希，源文件只读。
3. 自动切分镜头，允许拖动起止帧、合并、拆分和命名。
4. 运行相机求解，显示进度、跟踪点和误差；失败时选择手工相机或跳过。
5. 生成人体代理，选择单人/多人和尺度，显示 person_id、置信度和遮挡段。
6. 在实景参考、叠加和纯白模视图间修正相机、角色、道具和遮挡。
7. 导出白模视频、参考帧和 manifest；失败保留中间产物。
8. 生成 Seedance 离线请求包，展示文件清单、提示词、模型和上传状态。
9. 用户明确确认后才上传/提交；任务支持轮询、取消、重试和结果下载。
10. 结果下载到 S 盘新版本目录，校验哈希并回链到 shot/version，不覆盖白模源文件。

## Agent 悬浮控制台

桌面端右上角打开可拖动 Agent 面板。用户可以自然语言下达“查看状态”“生成白模”“选择镜头 shot_001”“运行 Blender”“生成 Seedance 请求包”“保存项目”等指令。Agent 先解析为白名单工具，再在后台线程执行，完成后把工具结果、错误和输出路径回显到对话面板。

默认使用本地解析，不联网。启用在线 Agent 后直接复用 Eggfans 配置页中的 Base URL、API Key 和鉴权，Agent 使用单独的 Eggfans 对话模型 ID，并调用 `/v1/chat/completions`；模型只能规划已注册工具，禁止代码生成、任意命令和未注册网络提交。真实媒体上传和 Eggfans 提交暂不注册为工具，仍需单独的确认与契约实现。

状态机：`created → ingesting → ready → analyzing → needs_review → exporting → exported → packaged → awaiting_confirmation → submitted → polling → completed/failed/cancelled`。供应商不可用时仍可完成 Blender 白模和离线请求包。
