import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from whiteblock.pipeline import ROOT, blender_script, build_scene_spec, find_blender, run_blender_script


def actor_fixture():
    p=[[0.5,0.5,0,0.95] for _ in range(33)]
    positions={0:(0.5,0.18),11:(0.4,0.3),12:(0.6,0.3),13:(0.33,0.45),14:(0.67,0.45),
               15:(0.28,0.59),16:(0.72,0.59),23:(0.43,0.56),24:(0.57,0.56),25:(0.43,0.74),
               26:(0.57,0.74),27:(0.43,0.92),28:(0.57,0.92)}
    for j,(x,y) in positions.items():p[j]=[x,y,0,0.95]
    world=[[q[0]-0.5,q[1]-0.56,q[2],q[3]] for q in p]
    world[15][2]=-0.25;world[16][2]=0.2
    return {'id':'Actor_01','poses':[{'frame':13,'landmarks':p,'world_landmarks':world},
                                  {'frame':14,'landmarks':p,'world_landmarks':world}]}


class HumanUpgradeTests(unittest.TestCase):
    def test_one_click_scene_selects_human_and_quality_renderer_by_default(self):
        project={'project_id':'fixture','media':{'width':720,'height':1280},'source':{'path':''}}
        shot={'shot_id':'shot_001','start_frame':1,'end_frame':3,'fps':24,'reconstruction':'landmark_proxy','actors':[actor_fixture()]}
        spec=build_scene_spec(project,shot)
        self.assertEqual(spec.get('geometry_profile'),'human_v3')
        self.assertEqual(spec.get('render_engine'),'eevee')
    def test_human_fitting_preserves_world_depth_and_fixed_body_size(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.human_pose'),'A true 3D skeleton fitter is required')
        from whiteblock.human_pose import fit_humans
        result=fit_humans([actor_fixture()],13,14,24,5.625,10)
        actor=result['actors'][0]
        a,b=actor['animation']
        self.assertNotEqual(a['joints']['15'][1],a['joints']['16'][1])
        self.assertEqual(a['scale'],b['scale'])
        self.assertEqual(result['quality']['world_pose_samples'],2)

    @unittest.skipUnless(find_blender(),'Local Blender required')
    def test_depth_repair_uses_deformed_surface_extent(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d);script=folder/'depth.py';output=folder/'quality.json'
            script.write_text('import bpy,sys,json\n'+
                'sys.path.insert(0,'+repr(str(ROOT))+')\n'+
                'from whiteblock.blender_human import finalize_motion\n'+
                'bpy.ops.wm.read_factory_settings(use_empty=True)\n'+
                'scene=bpy.context.scene;scene.frame_start=scene.frame_end=1\n'+
                'for i in range(2):\n'+
                '    name="Actor_0"+str(i+1)\n'+
                '    rig=bpy.data.objects.new(name+"_Rig",bpy.data.armatures.new(name));scene.collection.objects.link(rig)\n'+
                '    rig.location=(i*.1,i,i*.1)\n'+
                '    bpy.ops.mesh.primitive_cube_add();body=bpy.context.object;body.name=name+"_WhiteModel"\n'+
                '    body.dimensions=(1,8,2);body.parent=rig;body["geometry_profile"]="human_v3"\n'+
                'bpy.context.view_layer.update()\n'+
                'finalize_motion({"human_actors":[{"id":"Actor_01","animation":[{"frame":1}]},{"id":"Actor_02","animation":[{"frame":1}]}],"quality_path":'+repr(str(output))+'})\n',encoding='utf-8')
            child=subprocess.run([find_blender(),'-b','--python-exit-code','1','--python',str(script)],capture_output=True,timeout=90)
            self.assertEqual(child.returncode,0,child.stderr.decode(errors='replace'))
            data=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(data['frames_with_initial_issues'],1)
            self.assertEqual(data['remaining_frames'],0)

    @unittest.skipUnless(find_blender(),'Local Blender required')
    def test_human_render_has_continuous_anatomy_and_parented_deform_skeleton(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d)
            actor=actor_fixture()
            actor['poses'][1]['landmarks']=[list(q) for q in actor['poses'][1]['landmarks']]
            actor['poses'][1]['landmarks'][13][3]=0
            spec={'shot_id':'shot_001','collections':['WHITEBLOCK','CHARACTERS','CAMERA_SOLVE'],
                  'start_frame':13,'end_frame':14,'fps':24,'resolution_x':72,'resolution_y':128,
                  'geometry_profile':'human_v3','render_engine':'workbench','actors':[actor],
                  'material':{'base_color':[0.8,0.8,0.8,1],'roughness':0.8},
                  'output_blend':str(folder/'真人.blend'),'output_video':str(folder/'真人.mp4'),
                  'render_frames':str(folder/'frames/frame')}
            script=folder/'scene.py';script.write_text(blender_script(spec),encoding='utf-8')
            run_blender_script(script,find_blender())
            inspection=folder/'inspect_human.py';output=folder/'body.json'
            inspection.write_text('import bpy,json,sys\nsys.path.insert(0,'+repr(str(ROOT))+')\n'+
                'rig=bpy.data.objects["Actor_01_Rig"];body=bpy.data.objects["Actor_01_WhiteModel"]\n'+
                'data={"profile":body.get("geometry_profile"),"vertices":len(body.data.vertices),'+
                '"parented":sum(b.parent is not None for b in rig.data.bones),'+
                '"subdivision":any(m.type=="SUBSURF" for m in body.modifiers),'+
                '"mixed_weights":sum(len(v.groups)>1 for v in body.data.vertices),'+
                '"quality":json.loads(bpy.context.scene.get("mesh_quality","{}")),'+
                '"bones":list(rig.data.bones.keys())}\n'+
                'from whiteblock.blender_operations import check_intersections\ndata["collisions"]=check_intersections()\n'+
                'data["arm_frames"]=sorted({p.co.x for layer in rig.animation_data.action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves if curve.data_path==\'pose.bones["upperarm01.L"].rotation_quaternion\' for p in curve.keyframe_points})\n'+
                'bpy.context.scene.frame_set(14);before=rig.pose.bones["lowerarm02.L"].tail.copy()\n'+
                'bpy.context.scene.frame_set(13)\nfrom whiteblock.blender_operations import pose_preset\n'+
                'data["preset"]=pose_preset("left_hand","hand_chest","Actor_01")\n'+
                'bpy.context.scene.frame_set(14);data["untouched_end_error"]=(rig.pose.bones["lowerarm02.L"].tail-before).length\n'+
                'open('+repr(str(output))+',"w").write(json.dumps(data))\n',encoding='utf-8')
            child=subprocess.run([find_blender(),'-b',spec['output_blend'],'--python-exit-code','1','--python',str(inspection)],capture_output=True,timeout=90)
            self.assertEqual(child.returncode,0,child.stderr.decode(errors='replace'))
            data=json.loads(output.read_text())
            self.assertEqual(data['profile'],'human_v3')
            self.assertGreater(data['vertices'],10000)
            self.assertGreater(data['parented'],30)
            self.assertGreater(data['mixed_weights'],1000)
            self.assertTrue(data['subdivision'])
            self.assertIn('lowerarm01.L',data['bones'])
            self.assertEqual(data['collisions']['issues'],[])
            self.assertEqual(data['quality'].get('audited_frames'),2)
            self.assertEqual(data['quality'].get('remaining_frames'),0)
            self.assertEqual(data['arm_frames'],[13,14])
            self.assertLess(data['untouched_end_error'],.0001)


if __name__=='__main__':unittest.main()
