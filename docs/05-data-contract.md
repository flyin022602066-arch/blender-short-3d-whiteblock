# 接口与数据契约

## project.json

```json
{
  "schema_version": "1.0",
  "project_id": "proj_20261007_001",
  "blender_version": "5.1.2",
  "source": {"path": "S:/.../input/episode01.mp4", "sha256": "...", "readonly": true},
  "shots": [{"shot_id": "shot_001", "start_frame": 1, "end_frame": 180, "fps": 30}]
}
```

## pose.json

每帧必须有 `frame`、`person_id`、`keypoints_2d`、`confidence`、`occlusion`、`model_version`；可选 `keypoints_3d`，并声明单位和坐标系。缺失点不能填成高置信度零值。

## shot-manifest.json

包含 `project_id`、`shot_id`、`revision`、源视频哈希、Blender/算法版本、输出文件哈希、角色/场景/道具、人工修正摘要、渲染参数和上传许可状态。

## Eggfans API 连接配置

```json
{
  "provider": "eggfans",
  "base_url": "https://api.eggfans.com",
  "pricing_endpoint": "/api/pricing",
  "agent_endpoint": "/v1/chat/completions",
  "agent_model": "gpt-6-astra",
  "api_key_source": "EGGFANS_API_KEY",
  "timeout_seconds": 60,
  "offline_by_default": true
}
```

`base_url` 必须支持环境变量覆盖，但默认值保持为用户提供的地址。API key 不进入 Blender 工程、manifest、请求包或普通日志。`/pricing` 的原始响应只保存脱敏后的模型/价格缓存，不保存密钥。

## Seedance 请求

适配器通过 Eggfans API 调用模型，但必须保留 provider-native `content` 数组：

```json
{
  "model": "seedance-2.5",
  "content": [
    {"type": "text", "text": "保持角色、场景、道具和镜头运动一致"},
    {"type": "video_url", "video_url": {"url": "https://.../whiteblock.mp4"}, "role": "reference_video"},
    {"type": "audio_url", "audio_url": {"url": "https://.../dialogue.wav"}, "role": "reference_audio"}
  ],
  "metadata": {"project_id": "...", "shot_id": "...", "revision": 3}
}
```

无音频时省略 `audio_url`。公共 URL 只能在用户确认后生成；内部 `asset://` 仅在供应商明确支持时使用。保存 request_id、状态、错误码、结果 URL、下载哈希和时间戳。具体提交路径、轮询路径、鉴权头和字段名以 Eggfans 实际 API 契约为准，在真实调用前不得猜测。

## 错误码

`E_INPUT_MISSING`、`E_TRACK_SOLVE`、`E_POSE_LOW_CONF`、`E_EXPORT_CODEC`、`E_UPLOAD_CONFIRM_REQUIRED`、`E_PROVIDER_AUTH`、`E_PROVIDER_RATE_LIMIT`、`E_PROVIDER_SCHEMA`。
