# 坐标系诊断报告

**问题表现**：
- 人物朝向相反（后脑勺对镜头）
- 手部闪烁
- 人物位置不正确

## 诊断分析

### 1. MediaPipe 坐标系统

**屏幕坐标（2D）**：
```
(0, 0) = 左上
(1, 1) = 右下

鼻子:     x=0.3670, y=0.3245, z=-0.1608
左肩:     x=0.3274, y=0.4418, z=0.1011
右肩:     x=0.2306, y=0.3713, z=-0.2129
左臀:     x=0.2365, y=0.7245, z=0.1249
右臀:     x=0.1712, y=0.7284, z=-0.1247
```

**3D 世界坐标**（MediaPipe Pose）：
```
鼻子 3D:  x=0.3286,  y=-0.3976, z=-0.1613
左肩 3D:  x=0.2622,  y=-0.3161, z=0.0775
右肩 3D:  x=0.0379,  y=-0.3676, z=-0.1755
左臀 3D:  x=0.0757,  y=0.0027,  z=0.1003
右臀 3D:  x=-0.0759, y=-0.0033, z=-0.0993
```

**观察**：
- 左肩 X (0.2622) > 右肩 X (0.0379) → 人物正面对镜头
- 左肩 Z (0.0775) > 右肩 Z (-0.1755) → 左肩更靠前
- 人物应该正面对镜头

### 2. Blender 坐标系统

**期望**：
- 人物也应该正面对镜头
- X: 左负 → 右正
- Y: 后负 → 前正
- Z: 下负 → 上正

### 3. 坐标映射问题

**关键代码位置**：`whiteblock/blender_human.py` 第 24 行

```python
x,y,z=map(float,fields[1:4]);vertices.append(Vector((x,-z,y)))
```

这是 OBJ 模型加载时的坐标变换：
- OBJ: (x, y, z)
- Blender: (x, -z, y)

**问题**：如果骨骼的方向向量没有按照同样的转换规则应用，就会导致朝向错误。

### 4. 根本原因推断

**最可能的问题**：骨骼旋转计算中的坐标变换不一致

文件 `blender_human.py` 中的 `aim()` 函数（第 79-89 行）计算骨骼方向：

```python
def aim(rig,name,direction):
    bone=rig.pose.bones.get(name)
    if not bone or direction.length<.001:return
    # 这里的 direction 向量可能没有经过正确的坐标变换
    rest_global=bone.bone.matrix_local.to_quaternion()
    desired=(rest_global@Vector((0,1,0))).rotation_difference(direction.normalized())@rest_global
    ...
```

如果 `direction` 向量的坐标系与骨骼期望的坐标系不匹配，就会导致骨骼指向错误的方向。

## 解决方案

### 方案 1：检查骨骼方向（最可能有效）

修改 `aim()` 函数，确保方向向量的坐标系正确。

**关键改动**：
```python
def aim(rig,name,direction):
    bone=rig.pose.bones.get(name)
    if not bone or direction.length<.001:return
    
    # 反转 X 坐标以匹配 OBJ 模型的坐标变换
    direction = Vector((-direction.x, direction.y, direction.z))
    
    # 或者，完整的坐标变换（如果模型使用了 (x,-z,y) 变换）
    # direction = Vector((direction.x, -direction.z, direction.y))
    
    rest_global=bone.bone.matrix_local.to_quaternion()
    ...
```

### 方案 2：在关键点映射时修正

在 `point()` 函数或姿态处理中，在转换 MediaPipe 坐标时应用镜像：

```python
def point(p):
    # MediaPipe: (x, y, z)
    # 反转 X 以修正朝向
    x = -(p[0] - 0.5) * view_width  # 反转
    y = ...
    z = ...
    return Vector((x, y, z))
```

### 方案 3：校准参数调整

如果是由于深度估算或坐标缩放的问题，可以在 `point()` 函数中添加缩放因子或偏移。

## 手部问题分析

**问题**：手部闪烁、消失

**原因**：
1. 手部关键点置信度低（见诊断输出中的置信度值）
2. 当关键点丢失时，系统的降级处理不当
3. 可能与朝向问题有关（骨骼方向错误导致手部位置计算错误）

**解决**：
- 一旦骨骼朝向问题解决，手部位置应该会自动改善
- 如需进一步改善，可以增加手部关键点的平滑/插值

## 建议行动

1. **立即修试**（方案 1）：
   - 在 `blender_human.py` 的 `aim()` 函数中试试反转方向向量的 X 坐标
   - 重新生成白模看效果

2. **如果不行**（方案 2）：
   - 检查 `point()` 函数中的坐标转换
   - 考虑完整的坐标系变换

3. **验证**：
   - 对比诊断输出中的 MediaPipe 坐标和 Blender 中的骨骼位置
   - 确保方向一致

## 文件修改候选

1. `whiteblock/blender_human.py` - `aim()` 函数
2. `whiteblock/blender_scene.py.template` - `point()` 函数（如需要）
3. `whiteblock/human_pose.py` - 姿态处理（如需要）

---

**下一步**：等待用户确认是否进行这些修改。
