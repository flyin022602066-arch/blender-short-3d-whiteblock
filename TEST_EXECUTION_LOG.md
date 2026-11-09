# 测试执行日志

**日期**：2026-10-15 15:29 - 15:39  
**任务**：验证透视相机和地面平面改进

## 执行步骤

### 1️⃣ 准备测试视频
```bash
ffmpeg -y -i "output/input/344534535_EP1__1_original.mp4" \
  -t 5 -c:v libx264 -crf 23 -c:a copy \
  "output/input/test_perspective_5sec.mp4"
```

**结果**：✅ 成功  
**输出**：`output/input/test_perspective_5sec.mp4` (1.1 MB, 5 秒)

---

### 2️⃣ 项目初始化
```bash
python -m whiteblock.cli init "output/input/test_perspective_5sec.mp4" \
  --project-id "test_perspective" \
  --end-frame 120 \
  --fps 24 \
  --project "output/projects/test_perspective.json"
```

**结果**：✅ 成功  
**输出**：
- 项目 JSON：`output/projects/test_perspective.json`
- 检测到 3 个镜头
- SHA-256：`336e6eacfdd5d9b92179bf98ee393f45d8be66b0f58b1966ed3ea2d3e3a99751`

---

### 3️⃣ 姿态分析
```bash
.venv-pose/Scripts/python.exe -m whiteblock.analysis_worker \
  "output/input/test_perspective_5sec.mp4" \
  "output/cache/test_perspective"
```

**结果**：✅ 成功  
**输出**：
```
stage: analyzing
frame: 15, total: 120, shots: 1, people: 6
frame: 31, total: 120, shots: 1, people: 5
frame: 47, total: 120, shots: 1, people: 5
frame: 58, total: 120, shots: 2, people: 1
frame: 61, total: 120, shots: 2, people: 1
frame: 77, total: 120, shots: 2, people: 0
frame: 93, total: 120, shots: 2, people: 0
frame: 109, total: 120, shots: 2, people: 0
frame: 119, total: 120, shots: 3, people: 4
─────────────────────────────────────────
stage: analysis_done
pose_samples: 115
shots: 3
```

---

### 4️⃣ 白模脚本生成
```bash
python -m whiteblock.cli build \
  "output/projects/test_perspective.json" \
  --out "output/exports/test_perspective_demo"
```

**结果**：✅ 成功  
**输出**：
```json
{
  "project_id": "test_perspective",
  "outputs": [
    {"path": "shot_001.scene.json", "sha256": "cbab..."},
    {"path": "shot_001.blender.py", "sha256": "008a..."}
  ],
  "expected_blender_outputs": [
    {"path": "shot_001.blend", "kind": "blend"},
    {"path": "shot_001.blender.mp4", "kind": "whiteblock_video"}
  ]
}
```

---

### 5️⃣ Blender 渲染
```bash
"S:\...\Blender\blender.exe" -b -P \
  "output/exports/test_perspective_demo/shot_001.blender.py"
```

**结果**：✅ 成功  
**输出**：
- 渲染帧数：120 帧
- 所有帧位置：`output/input/cache/test_perspective/render/shot_001/frame0001.png` 到 `frame0120.png`
- 单帧时间：~80ms
- 生成文件：`shot_001.blend` (100 KB)

**典型输出**：
```
00:00.001 render | Saved: 'frame0001.png'
00:00.079 render | Saved: 'frame0002.png'
00:00.160 render | Saved: 'frame0003.png'
...
00:09.907 render | Saved: 'frame0120.png'
Info: Saved as "shot_001.blend"
Blender 5.1.2 quit
```

---

### 6️⃣ MP4 编码
```bash
ffmpeg -y -framerate 24 \
  -i "output/input/cache/test_perspective/render/shot_001/frame%04d.png" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p \
  -metadata title="Whiteblock Test - Perspective Camera" \
  "output/exports/test_perspective_demo/shot_001.blender.mp4"
```

**结果**：✅ 成功  
**输出**：`output/exports/test_perspective_demo/shot_001.blender.mp4` (188 KB)

**编码统计**：
```
frame=  120 fps=0.0 q=-1.0 Lsize=     188KiB 
time=00:00:04.91 bitrate= 312.5kbits/s speed=18.4x
```

---

## 最终输出验证

### 文件列表
```
output/exports/test_perspective_demo/
├── shot-manifest.json        (937 B)
├── shot_001.blend           (100 KB)   ✅
├── shot_001.blender.mp4     (188 KB)   ✅✅✅
├── shot_001.blender.py      (14 KB)
└── shot_001.scene.json      (1.2 KB)
```

### 视频规格
```
ffprobe 结果：
- 分辨率: 720 × 1280
- 帧率: 24 fps
- 时长: 5.0 秒
- 帧数: 120 帧
```

---

## 改进验证

### 检查项 1：相机配置
**预期**：`camera.data.type = 'PERSP'`  
**验证**：✅ 通过  
**证据**：
- `shot_001.blender.py` 中包含 `camera.data.type = 'PERSP'`
- `shot_001.blender.py` 中包含 `camera.data.lens = 28`

### 检查项 2：地面对象
**预期**：存在 `GroundPlane` 对象  
**验证**：✅ 通过  
**证据**：
- `shot_001.blender.py` 中包含 `ground.name = 'GroundPlane'`
- `shot_001.blender.py` 中包含 `location=(0, 0, -1.6)`

### 检查项 3：深度参数
**预期**：`depth_scale = view_width * 0.5`，范围 ±8  
**验证**：✅ 通过  
**证据**：
- `shot_001.blender.py` 中包含 `depth_scale = view_width * 0.5`
- `shot_001.blender.py` 中包含 `max(-8, min(8, estimated_depth))`

---

## 时间统计

| 步骤 | 用时 |
|------|------|
| 1. 视频准备 | < 1 秒 |
| 2. 项目初始化 | < 1 秒 |
| 3. 姿态分析 | ~25 秒 |
| 4. 脚本生成 | < 1 秒 |
| 5. Blender 渲染 | ~10 秒 |
| 6. MP4 编码 | ~5 秒 |
| **总计** | **~42 秒** |

---

## 成功指标

✅ **所有步骤成功**

- [x] 视频测试片段生成
- [x] 项目创建成功
- [x] 姿态分析正常
- [x] 脚本生成成功
- [x] Blender 渲染无错误
- [x] 所有 120 帧成功输出
- [x] MP4 编码成功
- [x] 输出文件规格正确
- [x] 相机改进已应用
- [x] 地面平面已创建
- [x] 深度参数已改进

---

## 关键发现

### 改进应用确认
1. **透视相机**
   - ✅ 已从 ORTHO 改为 PERSP
   - ✅ 焦距 28mm 已应用
   - ✅ 相机位置 Y=-15 已应用

2. **地面平面**
   - ✅ 20×20 网格已创建
   - ✅ 位置 Z=-1.6 已设置
   - ✅ 材质配置已应用

3. **深度估算**
   - ✅ 深度范围从 ±2 改为 ±8
   - ✅ 缩放系数已优化
   - ✅ 公式已更新

### 渲染性能
- 平均每帧 ~80ms
- 总渲染时间 ~9.6 秒
- 编码速度 18.4x

---

## 下一步建议

1. **查看输出视频**（立即）
   - 位置：`output/exports/test_perspective_demo/shot_001.blender.mp4`
   - 验证透视感和地面视觉

2. **完整视频测试**（推荐）
   - 用完整 30 秒原片重新渲染
   - 验证多人场景效果

3. **用户反馈**（重要）
   - 对比改进前后效果
   - 确认是否满足预期

---

**执行完成时间**：2026-10-15 15:39  
**执行状态**：✅ 成功  
**记录人**：Claude Opus 5.5
