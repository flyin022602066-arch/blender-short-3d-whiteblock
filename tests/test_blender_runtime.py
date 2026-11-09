import json
import tempfile
import unittest
from pathlib import Path
import subprocess
from whiteblock.pipeline import ROOT, blender_script, find_blender, probe_media, run_blender_script


@unittest.skipUnless(find_blender(), 'A local Blender is required for the render regression.')
class BlenderRuntimeTests(unittest.TestCase):
    def test_clean_scene_animates_and_encodes_nonzero_start_frame(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            root = Path(d)
            points = [[0.5, 0.5, 0, 0.9] for _ in range(33)]
            points[0] = [0.3, 0.2, 0, 0.9]
            points[11], points[12] = [0.4,0.35,0,0.9], [0.6,0.35,0,0.9]
            points[23], points[24] = [0.4,0.65,0,0.9], [0.6,0.65,0,0.9]
            moved = [p[:] for p in points]
            moved[0][0] = 0.7
            spec = {'shot_id': 'shot_001', 'collections': ['WHITEBLOCK', 'CHARACTERS', 'CAMERA_SOLVE'],
                    'start_frame': 13, 'end_frame': 14, 'fps': 24, 'resolution_x': 72, 'resolution_y': 128,
                    'material': {'base_color': [0.8,0.8,0.8,1], 'roughness': 0.8},
                    'actors': [{'id': 'Actor_01', 'poses': [{'frame': 13, 'landmarks': points},
                                                         {'frame': 14, 'landmarks': moved}]}],
                    'output_blend': str(root/'测试.blend'), 'output_video': str(root/'测试.mp4'),
                    'render_frames': str(root/'frames/frame')}
            script = root/'scene.py'
            script.write_text(blender_script(spec), encoding='utf-8')
            result = run_blender_script(script, find_blender())
            self.assertEqual(len(result['outputs']), 2)
            info = probe_media(root/'测试.mp4')
            self.assertTrue(info['available'])
            self.assertEqual((info['width'], info['height']), (72,128))
            self.assertAlmostEqual(info['duration_seconds'], 2/24, delta=0.01)
            inspection = root/'inspect.py'
            output = root/'inspect.json'
            inspection.write_text('import bpy,json\n' +
                'rig=bpy.data.objects["Actor_01_Rig"]\nhead=rig.pose.bones["Head"]\n' +
                'bpy.context.scene.frame_set(13)\na=list(head.matrix.translation)\n' +
                'bpy.context.scene.frame_set(14)\nb=list(head.matrix.translation)\n' +
                'models=[o for o in bpy.data.objects if o.type=="MESH" and o.name.startswith("Actor_01")]\n' +
                'open(' + repr(str(output)) + ',"w").write(json.dumps({"a":a,"b":b,"cube":"Cube" in bpy.data.objects,"models":len(models),"bound":all(any(m.type=="ARMATURE" for m in o.modifiers) for o in models),"vertices":sum(len(o.data.vertices) for o in models)}))\n', encoding='utf-8')
            child = subprocess.run([find_blender(), '-b', spec['output_blend'], '--python-exit-code', '1',
                                    '--python', str(inspection)], capture_output=True, timeout=60)
            self.assertEqual(child.returncode, 0, child.stderr.decode(errors='replace'))
            values = json.loads(output.read_text())
            self.assertGreater(values['b'][0]-values['a'][0], 1)
            self.assertFalse(values['cube'])
            self.assertEqual(values['models'],1)
            self.assertTrue(values['bound'])
            self.assertGreater(values['vertices'],1000)


if __name__ == '__main__': unittest.main()
