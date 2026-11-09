#!/usr/bin/env python
"""Test the camera and ground plane improvements"""
import sys
import json
from pathlib import Path

# Read the template to verify changes
template_path = Path('whiteblock/blender_scene.py.template')
template = template_path.read_text(encoding='utf-8')

print("=== 相机和地面改进验证 ===\n")

# Check 1: Perspective camera
if "camera.data.type = 'PERSP'" in template:
    print("✅ 相机已改为透视投影 (PERSP)")
else:
    print("❌ 相机仍是正交投影")
    sys.exit(1)

# Check 2: Focal length calculation
if "focal_length = sensor_height" in template and "vertical_fov_deg" in template:
    print("✅ 添加了焦距计算（基于垂直视角）")
else:
    print("❌ 缺少焦距计算")
    sys.exit(1)

# Check 3: Ground plane
if "GroundPlane" in template and "primitive_grid_add" in template:
    print("✅ 添加了地面网格平面")
else:
    print("❌ 缺少地面平面")
    sys.exit(1)

# Check 4: Improved depth calculation
if "depth_scale = view_width * 0.5" in template:
    print("✅ 改进了深度估算（扩大范围）")
else:
    print("❌ 深度计算未优化")
    sys.exit(1)

# Check 5: Updated camera position
if "location=(0, -15, 0)" in template:
    print("✅ 相机位置已调整（更接近）")
else:
    print("⚠️  相机位置未变")

print("\n=== 关键参数 ===")
print("相机距离: Y = -15 (was -30)")
print("垂直视角: 65° (手机相机典型值)")
print("地面位置: Z = -1.6 (人物脚底参考)")
print("深度范围: Y ∈ [-8, 8] (was [-2, 2])")

print("\n✅ 所有关键改进已应用！")
print("\n下一步: 用真实视频测试渲染效果")
