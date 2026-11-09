# 总体技术方案

## 架构

Blender 5.1.2 是项目主控，负责工程、时间轴、参考视频、相机、白模资产、动画修正、预览和渲染。外部能力通过本地 worker 或 Blender Python API 接入：视频索引/代理、镜头切分、相机求解、人体姿态、骨骼重定向、导出和 Seedance 适配器彼此解耦。

```text
短剧视频 -> 索引/镜头 -> 相机跟踪 ┐
                         ├-> Blender 白模场景/动画 -> 白模视频/参考包
视频帧 -> 姿态 worker -> 骨骼重定向 ┘                         -> Seedance 2.5
```

## 模块边界

- Project Manager：项目、镜头、资产、版本、哈希和 S 盘路径。
- Video Ingest：ffprobe 信息、代理视频、帧缓存、镜头时间码。
- Camera Solver：Blender Motion Tracking，输出跟踪点、相机和误差。
- Pose Worker：本地姿态/人体跟踪，输出标准关键点 JSON、置信度和遮挡。
- Rig Retargeter：关键点到代理骨骼、IK、脚底接地、平滑和人工关键帧层。
- Whiteblock Builder：地面、墙、道具和人物占位体，统一白材质和灯光。
- Render/Export：白模 MP4/PNG、参考帧、manifest 和校验。
- Provider Adapter：通过 Eggfans API 构建 Seedance 请求、确认、上传、提交、轮询和下载；`base_url` 可配置，默认 `https://api.eggfans.com`。
- Agent Control Layer：Tkinter 悬浮控制台，使用严格工具注册表操控项目状态、镜头、白模脚本、Blender 执行、离线请求包和输出目录；不提供编码工具，默认本地离线解析；在线规划复用 Eggfans 的同一 Base URL、API key、鉴权和模型。

## 数据流与原则

1. 计算源视频 SHA-256，源文件只读，建立低码率代理。
2. 相机和姿态原始结果写入 `cache/`，人工修正写入独立 revision，不覆盖算法结果。
3. Blender 集合固定为 `REF_VIDEO`、`CAMERA_SOLVE`、`CHARACTERS`、`PROPS`、`WHITEBLOCK`。
4. 导出采用临时文件后原子重命名，失败保留日志和中间产物。
5. Seedance 只消费导出包，不反向修改 Blender；默认只生成离线 JSON，不上传。
6. Agent 的每个动作写入项目 history 与 `logs/pipeline.jsonl`；在线模型只能返回工具名和参数，未知工具直接丢弃。

## Eggfans API 集成边界

- 配置项：`EGGFANS_BASE_URL`（默认 `https://api.eggfans.com`）、`EGGFANS_API_KEY`（仅从环境变量/本地安全存储读取）、连接/读取超时、重试次数。
- 模型发现：调用 `GET /api/pricing`，解析可用模型、计价和能力；不得把模型名硬编码成唯一值。发现结果写入本地缓存并标注时间。
- 任务调用：由独立 adapter 按 Eggfans 实际 API 契约构建请求；Blender 核心只接收统一的 `submit/poll/cancel/download` 接口。
- 认证：API key 只放请求头，不写入 `.blend`、manifest、普通日志或导出包；日志只记录脱敏后的 base URL、模型、request_id 和状态。
- 安全：本地默认只生成离线请求包；只有用户确认后才进行网络访问、媒体上传和模型提交。
- 未知契约：在首次真实调用前，必须用 `/pricing` 和 Eggfans 官方接口文档/示例确认具体鉴权头、视频生成路径、提交字段、轮询字段、取消能力和响应结构；在此之前只实现模拟 adapter。

## 技术选择

Blender Python API、Motion Tracking、Video Sequencer、Rigify（可选）；Python worker；JSON Schema；ffmpeg/ffprobe；姿态模型使用可替换本地接口。Seedance 适配器保留供应商原生 `content` 数组，把文本、`video_url`、`audio_url` 对象放在同一数组并使用 `role` 标记。

## 性能和降级

目标是 1080p、30 秒样片白模预览不超过 10 分钟。无 GPU 时允许手工相机和静态代理；跟踪失败时保留参考视频和手工相机；遮挡严重时降低置信度并要求人工修正。
