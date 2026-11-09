import json,subprocess,tempfile,unittest
import importlib.util,copy
from pathlib import Path
from whiteblock.pipeline import ROOT,find_blender,blender_script
from tests.test_human_upgrade import actor_fixture


class CrowdReconstructionTests(unittest.TestCase):
    def test_face_tracks_keep_two_people_when_pose_detection_drops_out(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.crowd_tracking'))
        from whiteblock.crowd_tracking import track_candidates,face_prior
        records=[]
        for frame in (1,3,5):
            faces=[{'bbox':[.2,.1,.06,.08],'score':.9},{'bbox':[.6,.1,.06,.08],'score':.9}]
            candidates=[face_prior(face,frame,720,1280) for face in faces]
            track_candidates(records,list(reversed(candidates)) if frame==3 else candidates,frame,24)
        self.assertEqual(len(records),2)
        self.assertEqual([len(r['poses']) for r in records],[3,3])
        self.assertLess(records[0]['poses'][-1]['landmarks'][0][0],records[1]['poses'][-1]['landmarks'][0][0])
        from whiteblock.human_pose import fit_humans
        actors=[{'id':f'Actor_0{i+1}',**r} for i,r in enumerate(records)]
        fitted=fit_humans(actors,1,6,24,5.625,10)
        self.assertEqual([len(a['animation']) for a in fitted['actors']],[6,6])
        self.assertEqual(fitted['quality'].get('prior_pose_frames'),12)

    def test_detection_absence_does_not_create_a_permanent_extra(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.crowd_tracking'))
        from whiteblock.crowd_tracking import track_candidates,face_prior
        records=[];face={'bbox':[.2,.1,.06,.08],'score':.9}
        for frame in (1,3):track_candidates(records,[face_prior(face,frame,720,1280)],frame,24)
        from whiteblock.human_pose import fit_humans
        fitted=fit_humans([{'id':'Actor_01',**records[0]}],1,40,24,5.625,10)
        self.assertLess(fitted['actors'][0]['animation'][-1]['frame'],12)

    @unittest.skipUnless(find_blender(),'Local Blender required')
    def test_inactive_character_never_leaves_a_visible_skeleton(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d);result=folder/'visibility.json'
            spec={'shot_id':'shot_001','start_frame':1,'end_frame':24,'fps':24,
                  'resolution_x':72,'resolution_y':128,'geometry_profile':'human_v3',
                  'render_engine':'workbench','actors':[actor_fixture()]}
            script=blender_script(spec)
            script+='\nimport json\nchecks=[]\nfor frame in (1,13,24):\n'+\
                '    scene.frame_set(frame);body=bpy.data.objects["Actor_01_WhiteModel"];rig=bpy.data.objects["Actor_01_Rig"]\n'+\
                '    checks.append({"frame":frame,"body":body.visible_get(),"rig":rig.visible_get(),"body_render":not body.hide_render,"rig_render":not rig.hide_render})\n'+\
                'open('+repr(str(result))+',"w").write(json.dumps(checks))\n'
            path=folder/'test.py';path.write_text(script,encoding='utf-8')
            child=subprocess.run([find_blender(),'-b','--python-exit-code','1','--python',str(path)],capture_output=True,timeout=90)
            self.assertEqual(child.returncode,0,child.stderr.decode(errors='replace'))
            checks=json.loads(result.read_text())
            self.assertEqual([c['body'] for c in checks],[False,True,False])
            self.assertEqual([c['rig'] for c in checks],[False,True,False])
            self.assertEqual([c['rig_render'] for c in checks],[False,True,False])
