"""Runs inside Blender: verify retargeting against independent landmark directions."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from whiteblock.blender_human import aim, bake_human, clear_forearms, create_human, load_anatomy

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 119, 121
material = bpy.data.materials.new('TestClay')
actor = {'id': 'MotionFixture', 'scale': 1, 'animation': []}
rig, body = create_human(actor, scene.collection, material, load_anatomy())

def error(name, direction):
    bone = rig.pose.bones[name]
    actual = rig.matrix_world.to_3x3() @ (bone.tail - bone.head)
    return math.degrees(actual.angle(Vector(direction)))

# Independent local-space aim check, including a rotated parent chain.
aim(rig, 'spine05', Vector((.2, .3, 1)))
aim(rig, 'spine04', Vector((-.1, .2, 1)))
aim(rig, 'upperarm01.L', Vector((.5, -.2, -.7)))
aim(rig, 'upperarm02.L', Vector((.5, -.2, -.7)))
aim(rig, 'lowerarm01.L', Vector((-.3, -.5, -.6)))
direct = {name: error(name, direction) for name, direction in (
    ('upperarm01.L', (.5, -.2, -.7)), ('lowerarm01.L', (-.3, -.5, -.6)))}
for bone in rig.pose.bones:
    bone.rotation_quaternion = (1, 0, 0, 0)
bpy.context.view_layer.update()

# Arms are outside the torso: no collision repair should change these poses.
for frame, elbow, wrist in ((119, (1.05, -.15, .9), (1.25, -.4, .35)),
                             (120, (.9, -.3, 1.05), (1.1, -.65, .6)),
                             (121, (.8, -.45, 1.2), (1.15, -.9, 1.1))):
    joints = {11: (.5, 0, 1.5), 12: (-.5, 0, 1.5),
              13: elbow, 15: wrist, 14: (-1.05, -.15, .9), 16: (-1.25, -.4, .35),
              23: (.3, 0, 0), 24: (-.3, 0, 0),
              25: (.3, 0, -1), 26: (-.3, 0, -1), 27: (.3, 0, -2), 28: (-.3, 0, -2)}
    actor['animation'].append({'frame': frame, 'root': (0, 0, 0),
        'joints': {str(j): q for j, q in joints.items()},
        'visibility': {str(j): 1 for j in joints}, 'pose_source': 'landmarks'})
bake_human(rig, body, actor, {'start_frame': 119, 'end_frame': 121})
frames = []
for sample in actor['animation']:
    scene.frame_set(sample['frame'])
    joints = sample['joints']
    checks = {}
    for name, a, b in (('upperarm01.L', 11, 13), ('lowerarm01.L', 13, 15),
                        ('upperarm01.R', 12, 14), ('lowerarm01.R', 14, 16)):
        checks[name] = error(name, Vector(joints[str(b)]) - Vector(joints[str(a)]))
    frames.append({'frame': sample['frame'], 'errors': checks})
import whiteblock.blender_human as human
motion_quality = human.audit_pose_directions({'human_actors': [actor], 'resolution_x': 720, 'resolution_y': 1280}) if hasattr(human, 'audit_pose_directions') else None
# Near-torso poses must not be moved solely on a coarse ellipsoid guess.
scene.frame_set(119)
near_joints = {j: Vector(q) for j, q in ((11, (.5, 0, 1.5)), (13, (.45, 0, .8)),
                                       (15, (.5, 0, .2)), (16, (-.5, 0, .2)))}
for name in ('upperarm01.L', 'upperarm02.L'):
    aim(rig, name, near_joints[13] - near_joints[11])
for name in ('lowerarm01.L', 'lowerarm02.L'):
    aim(rig, name, near_joints[15] - near_joints[13])
before = rig.pose.bones['lowerarm02.L'].tail.copy()
proxy_fixes = clear_forearms(rig, near_joints)
proxy_displacement = (rig.pose.bones['lowerarm02.L'].tail - before).length
Path(sys.argv[sys.argv.index('--') + 1]).write_text(json.dumps(
    {'direct': direct, 'frames': frames, 'clearance_fixes': rig.get('arm_chain_clearance_fixes', 0),
     'proxy_fixes': proxy_fixes, 'proxy_displacement': proxy_displacement,
     'motion_quality': motion_quality}))
