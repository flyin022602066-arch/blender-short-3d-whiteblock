# Eggfans API 接入说明

## 已确认配置

- Base URL：`https://api.eggfans.com`
- 模型列表/计价入口：`GET https://api.eggfans.com/api/pricing`
- Agent 对话入口：`POST https://api.eggfans.com/v1/chat/completions`，与 Seedance 共用 Base URL、API key 和鉴权配置，但使用 Agent 对话模型 ID。
- 目标模型：Seedance 2.5（实际模型 ID 以 `/pricing` 返回为准）

## 接入原则

Blender 只依赖统一的 provider adapter，不直接把 Eggfans HTTP 细节散落在 UI、渲染或资产模块中。adapter 提供：

```text
discover_models() -> /pricing
build_request(shot_manifest, references, prompt)
submit(request)
poll(request_id)
cancel(request_id)        # 若 Eggfans 支持
download(result)
```

首版必须支持离线 `build_request` 和本地模拟 `submit/poll`。真实网络调用需要用户明确授权，并在界面显示即将上传的文件、目标域名和模型。

## 鉴权与密钥

默认从 `EGGFANS_API_KEY` 环境变量读取，后续可接入 Windows 安全存储。密钥不得写入 `.blend`、项目 JSON、请求包、日志、截图或 Git。错误日志需过滤 `Authorization`、API key 和完整 URL 查询参数。

## `/pricing` 发现流程

启动或用户点击“刷新模型”时，adapter 请求 `/api/pricing`，校验 HTTP 状态、JSON 类型和必要字段，提取模型 ID、名称、能力、价格和更新时间。若失败，使用最近一次脱敏缓存，并在 UI 标示“缓存数据”；没有缓存时只能使用离线请求包，不能盲目提交。

## 提交/轮询契约

用户目前只提供了 base URL 和 `/pricing`。因此提交路径、鉴权头名称、Seedance 请求字段、任务 ID 字段、轮询 URL、取消接口和结果 URL 不能在计划中臆造。实现阶段应先依据 Eggfans 官方文档或一次经授权的 schema 探测完成契约确认，然后写入 adapter 的版本化 schema 和模拟测试。

## 请求内容

请求中保持供应商原生 `content` 数组：文本、白模参考视频和可选参考音频分别使用 `type: text`、`type: video_url`、`type: audio_url`，并标记 `role: reference_video`/`reference_audio`。白模视频、参考帧和提示词必须关联 `project_id`、`shot_id`、`revision`。

## 错误与重试

认证失败不重试；4xx 契约错误进入人工检查；429 和明确的 5xx 可指数退避重试；上传超时可重新生成新 job；轮询超时保留 request_id 并允许继续查询。所有请求记录脱敏后的状态、耗时、错误码和本地输出路径。
