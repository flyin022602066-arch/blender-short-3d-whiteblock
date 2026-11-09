#!/usr/bin/env python
"""诊断 MediaPipe 坐标系和 Blender 坐标系的映射问题"""

import json
import math
from pathlib import Path

def distance(p1, p2):
    return math.sqrt(sum((a-b)**2 for a, b in zip(p1, p2)))

def analyze_pose():
    # 读取场景数据
    scene = json.load(open('output/exports/wanxue_real_20261015_162224_377643/shot_002.scene.json'))

    if not scene.get('actors'):
        print("没有演员数据")
        return

    actor = scene['actors'][0]
    poses = actor.get('poses', [])
    if not poses:
        print("没有姿态数据")
        return

    pose = poses[0]
    landmarks = pose.get('landmarks', [])
    world_landmarks = pose.get('world_landmarks', [])

    print("=" * 80)
    print("MEDIAPIPE 坐标系诊断")
    print("=" * 80)

    # 关键点索引
    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26

    print("\n### 屏幕坐标分析（MediaPipe 2D）")
    print("范围: (0,0) = 左上，(1,1) = 右下")
    print()

    nose = landmarks[NOSE]
    left_shoulder = landmarks[LEFT_SHOULDER]
    right_shoulder = landmarks[RIGHT_SHOULDER]
    left_hip = landmarks[LEFT_HIP]
    right_hip = landmarks[RIGHT_HIP]

    print(f"鼻子位置        (x={nose[0]:.4f}, y={nose[1]:.4f}, z={nose[2]:.4f})")
    print(f"左肩位置        (x={left_shoulder[0]:.4f}, y={left_shoulder[1]:.4f}, z={left_shoulder[2]:.4f})")
    print(f"右肩位置        (x={right_shoulder[0]:.4f}, y={right_shoulder[1]:.4f}, z={right_shoulder[2]:.4f})")
    print(f"左臀位置        (x={left_hip[0]:.4f}, y={left_hip[1]:.4f}, z={left_hip[2]:.4f})")
    print(f"右臀位置        (x={right_hip[0]:.4f}, y={right_hip[1]:.4f}, z={right_hip[2]:.4f})")

    print("\n### 屏幕空间的结构分析")
    # 人物应该在画面中心左右
    center_x = (left_shoulder[0] + right_shoulder[0]) / 2
    center_y = (left_shoulder[1] + left_hip[1]) / 2
    shoulder_width = abs(right_shoulder[0] - left_shoulder[0])
    body_height = left_hip[1] - left_shoulder[1]

    print(f"肩膀中点 X 坐标: {center_x:.4f} (0=左边, 1=右边)")
    print(f"人物顶部(肩) Y: {left_shoulder[1]:.4f} (0=顶部, 1=底部)")
    print(f"人物底部(臀) Y: {left_hip[1]:.4f}")
    print(f"肩膀宽度: {shoulder_width:.4f} (占屏幕宽度的 {shoulder_width*100:.1f}%)")
    print(f"身体高度: {body_height:.4f} (占屏幕高度的 {body_height*100:.1f}%)")

    print("\n### Z 轴分析（深度/变换）")
    print("注意: z=0 通常表示主体在中间,z>0 前面,z<0 后面")
    print(f"鼻子 z:     {nose[2]:.4f}")
    print(f"左肩 z:     {left_shoulder[2]:.4f}")
    print(f"右肩 z:     {right_shoulder[2]:.4f}")
    print(f"左臀 z:     {left_hip[2]:.4f}")
    print(f"右臀 z:     {right_hip[2]:.4f}")

    if world_landmarks:
        print("\n### 3D 世界坐标分析")
        print("MediaPipe 的 3D 坐标系统（通常）：")
        print("- X: 左(负) → 右(正)")
        print("- Y: 上(负) → 下(正)")
        print("- Z: 后面(负) → 前面(正) [或反过来]")
        print()

        world_nose = world_landmarks[NOSE]
        world_left_shoulder = world_landmarks[LEFT_SHOULDER]
        world_right_shoulder = world_landmarks[RIGHT_SHOULDER]
        world_left_hip = world_landmarks[LEFT_HIP]
        world_right_hip = world_landmarks[RIGHT_HIP]

        print(f"鼻子 3D        (x={world_nose[0]:7.4f}, y={world_nose[1]:7.4f}, z={world_nose[2]:7.4f})")
        print(f"左肩 3D        (x={world_left_shoulder[0]:7.4f}, y={world_left_shoulder[1]:7.4f}, z={world_left_shoulder[2]:7.4f})")
        print(f"右肩 3D        (x={world_right_shoulder[0]:7.4f}, y={world_right_shoulder[1]:7.4f}, z={world_right_shoulder[2]:7.4f})")
        print(f"左臀 3D        (x={world_left_hip[0]:7.4f}, y={world_left_hip[1]:7.4f}, z={world_left_hip[2]:7.4f})")
        print(f"右臀 3D        (x={world_right_hip[0]:7.4f}, y={world_right_hip[1]:7.4f}, z={world_right_hip[2]:7.4f})")

        # 3D 空间的结构
        world_shoulder_width = distance(world_left_shoulder[:3], world_right_shoulder[:3])
        world_body_height = world_left_hip[1] - world_left_shoulder[1]
        world_shoulder_depth = abs(world_right_shoulder[2] - world_left_shoulder[2])

        print(f"\n3D 肩膀宽度: {world_shoulder_width:.4f}")
        print(f"3D 身体高度: {world_body_height:.4f}")
        print(f"3D 肩膀前后差: {world_shoulder_depth:.4f}")

        # 检查左右肩是否有显著的前后差异（表示人物朝向）
        print(f"\n### 人物朝向检查")
        print("如果左肩 Z 和右肩 Z 明显不同，说明人物有转身")
        print(f"左肩 Z: {world_left_shoulder[2]:.4f}")
        print(f"右肩 Z: {world_right_shoulder[2]:.4f}")
        print(f"差值:   {abs(world_left_shoulder[2] - world_right_shoulder[2]):.4f}")

    print("\n" + "=" * 80)
    print("BLENDER 坐标系统期望")
    print("=" * 80)
    print("""
Blender 世界坐标系:
- X: 左(负) → 右(正)
- Y: 后(负) → 前(正) [摄像机在 Y=-15]
- Z: 下(负) → 上(正)

对于我们的场景:
- 相机在 Y=-15，看向 Y=+
- 人物应该在 Y=0 到 Y=+8 之间
- 地面在 Z=-1.6
- 人物脚底应该在 Z≈-1.6，头部在 Z≈+1.5
""")

    print("\n" + "=" * 80)
    print("问题诊断")
    print("=" * 80)
    print("""
如果白模人物朝向相反（后脑勺对镜头），可能是：

1. **X 轴反了**
   - MediaPipe 的左/右和 Blender 的左/右映射反了
   - 需要反转 X: x_blender = -x_mediapipe

2. **Z 轴反了（深度）**
   - MediaPipe 的深度定义和 Blender 的不同
   - 需要反转 Z: z_blender = -z_mediapipe

3. **Y 轴问题**
   - 虽然不会导致"朝向反"，但会影响高度

4. **骨骼旋转问题**
   - aim() 函数中的旋转计算有错误
   - 导致骨骼指向错误的方向

建议检查:
- human_v3 中 Vector 的映射顺序
- blender_human.py 的 aim() 函数
- point() 函数中的坐标转换
""")

if __name__ == '__main__':
    analyze_pose()
