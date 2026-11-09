import ast,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from whiteblock.blender_session import BlenderSession
from whiteblock.pipeline import ROOT,save_project,load_project


class RevisionTests(unittest.TestCase):
    def test_revision_reports_edited_shot_quality_and_timeline(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as folder:
            root=Path(folder);source=root/'source.mp4';source.write_bytes(b'fixture')
            saved=root/'edit.blend';saved.write_bytes(b'fixture')
            original={'schema_version':'1.0','project_id':'fixture','blender_version':'5.1.2','workspace_root':str(root),
                'source':{'path':str(source),'readonly':True},'settings':{},'geometry_profile':'human_v3',
                'geometry_quality':{'mesh_audit':{'audited_frames':554,'remaining_frames':0}},
                'analysis':{'shots_without_pose':['shot_001']},'media':{'fps':24,'frame_count':721,'duration_seconds':721/24},
                'shots':[{'shot_id':'shot_006','start_frame':330,'end_frame':404,'fps':24,'actors':[{'id':'Actor_01'}]}]}
            project_path=root/'projects/fixture.json';save_project(project_path,original)
            quality={'audited_frames':75,'remaining_frames':2,'frames_with_initial_issues':2,'arm_repairs':0,'depth_repairs':0,'scope':'edited mesh'}
            def render(script,*args,**kwargs):
                tree=ast.parse(script.read_text(encoding='utf-8'))
                spec=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='spec' for t in node.targets))
                outputs=[]
                for key in ('output_blend','output_video'):
                    path=Path(spec[key]);path.write_bytes(b'fixture');outputs.append(str(path))
                if spec.get('quality_path'):Path(spec['quality_path']).write_text(json.dumps(quality),encoding='utf-8')
                return {'outputs':outputs}
            session=BlenderSession()
            with patch.object(session,'call',return_value={'blend':str(saved),'actors':[{'id':'Actor_01','body_template':'male','template_confirmed':True,'role_name':'角色甲'}]}),patch('whiteblock.blender_session.run_blender_script',side_effect=render),patch('whiteblock.library.refresh_library'):
                result=session.render_revision(project_path,'shot_006')
            revised=load_project(Path(result['project_path']))
            self.assertEqual(revised['geometry_quality']['mesh_audit']['audited_frames'],75)
            self.assertEqual(revised['geometry_quality']['mesh_audit']['remaining_frames'],2)
            self.assertEqual(revised['media']['frame_count'],75)
            self.assertEqual(revised['analysis']['shots_without_pose'],[])
            self.assertEqual(revised['shots'][0]['actors'][0].get('body_template'),'male')
            self.assertFalse(revised['shots'][0]['actors'][0].get('template_needs_render',True))
            manifest=json.loads((Path(result['directory'])/'shot-manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(any(p.get('kind')=='mesh_quality' for p in manifest['outputs']))


if __name__=='__main__':unittest.main()
