import copy,importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
from whiteblock.human_pose import fit_humans
from whiteblock.pipeline import ROOT,save_project,load_project,blender_script,run_blender_script,find_blender,build_seedance_request
from whiteblock.agent import ProjectAgent,AgentConfig
from tests.test_human_upgrade import actor_fixture


class ActorTemplateTests(unittest.TestCase):
    def test_fitting_retains_explicit_template_and_confirmation(self):
        actor=actor_fixture();actor.update(body_template='female',template_confirmed=True,template_source='user',role_name='角色甲')
        fitted=fit_humans([actor],13,14,24,5.625,10)['actors'][0]
        self.assertEqual(fitted.get('body_template'),'female')
        self.assertTrue(fitted.get('template_confirmed'))
        self.assertEqual(fitted.get('role_name'),'角色甲')

    def test_unspecified_template_stays_unconfirmed(self):
        fitted=fit_humans([actor_fixture()],13,14,24,5.625,10)['actors'][0]
        self.assertEqual(fitted.get('body_template'),'neutral')
        self.assertFalse(fitted.get('template_confirmed',True))

    def test_template_choice_is_scoped_to_actor_and_survives_project_reload(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.actor_profiles'))
        from whiteblock.actor_profiles import update_actor_template
        a=actor_fixture();b={**copy.deepcopy(a),'id':'Actor_02'}
        project={'schema_version':'1.0','project_id':'fixture','blender_version':'5.1.2','source':{'path':'source.mp4','readonly':True},
                 'shots':[{'shot_id':'shot_001','start_frame':13,'end_frame':14,'fps':24,'actors':[a,b]},
                          {'shot_id':'shot_002','start_frame':15,'end_frame':16,'fps':24,'actors':[copy.deepcopy(a)]}]}
        update_actor_template(project,'shot_001','Actor_01','male','角色甲')
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            path=Path(d)/'project.json';save_project(path,project);loaded=load_project(path)
        chosen=loaded['shots'][0]['actors'][0]
        self.assertEqual(chosen['body_template'],'male')
        self.assertTrue(chosen['template_confirmed'])
        self.assertTrue(chosen['template_needs_render'])
        self.assertNotIn('body_template',loaded['shots'][0]['actors'][1])
        self.assertNotIn('body_template',loaded['shots'][1]['actors'][0])
        before=copy.deepcopy(project)
        with self.assertRaises(ValueError):update_actor_template(project,'shot_001','Actor_01','invalid')
        self.assertEqual(project,before)

    def test_agent_changes_template_before_connecting_and_rendering(self):
        actions=[]
        tools={'set_actor_template':lambda **args:actions.append(('template',args)),
               'blender_connect':lambda:actions.append(('connect',{})),
               'blender_render':lambda:actions.append(('render',{}))}
        result=ProjectAgent(tools,AgentConfig()).execute('把 Actor_02 设为女型并重渲染')
        self.assertEqual(actions,[('template',{'actor':'Actor_02','template':'female'}),('connect',{}),('render',{})])
        self.assertTrue(all(a['ok'] for a in result['actions']))

    def test_local_agent_can_target_template_shot_explicitly(self):
        actions=[]
        tools={'set_actor_template':lambda **args:actions.append(args)}
        result=ProjectAgent(tools,AgentConfig()).execute('把 shot_002 的 Actor_02 设为女型')
        self.assertTrue(result['actions'][0]['ok'])
        self.assertEqual(actions,[{'actor':'Actor_02','template':'female','shot_id':'shot_002'}])

    def test_template_questions_or_ambiguous_multi_actor_text_do_not_change_character(self):
        calls=[]
        agent=ProjectAgent({'set_actor_template':lambda **args:calls.append(args)},AgentConfig())
        for text in ('Actor_01 是不是女性？','识别 Actor_01 是男性还是女性',
                     '不要把 Actor_01 设为女型','把 Actor_01 设为男型，把 Actor_02 设为女型'):
            with self.subTest(text=text):
                result=agent.execute(text)
                self.assertEqual(result['actions'],[])
                self.assertEqual(calls,[])

    def test_failed_template_change_stops_dependent_render(self):
        actions=[]
        def reject(**args):raise ValueError('该镜头不存在人物 Actor_99')
        tools={'set_actor_template':reject,'blender_connect':lambda:actions.append('connect'),
               'blender_render':lambda:actions.append('render')}
        result=ProjectAgent(tools,AgentConfig()).execute('把 Actor_99 设为女型并重渲染')
        self.assertFalse(result['actions'][0]['ok'])
        self.assertEqual(actions,[],'A rejected choice must not render an unchanged character')

    def test_external_render_package_retains_confirmed_templates_and_flags_old_video(self):
        actor=actor_fixture();actor.update(body_template='male',template_confirmed=True,role_name='角色甲',template_needs_render=True)
        project={'project_id':'fixture','settings':{}}
        shot={'shot_id':'shot_001','actors':[actor],'revision':1}
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d);(folder/'shot_001.blender.mp4').write_bytes(b'fixture')
            request=build_seedance_request(project,shot,folder)['request']
        self.assertEqual(request.get('template_status'),'pending_render')
        self.assertIn('actor_template_render',request['missing_media'])
        self.assertIn('角色甲',request['content'][0]['text'])
        self.assertEqual(request['metadata']['actor_templates'][0]['body_template'],'male')

    def test_request_distinguishes_unconfirmed_and_confirmed_without_changing_provider_media(self):
        actor=actor_fixture()
        project={'project_id':'fixture','settings':{'eggfans_model':'original-model'}}
        shot={'shot_id':'shot_001','actors':[actor]}
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d);(folder/'shot_001.blender.mp4').write_bytes(b'fixture')
            audio=folder/'reference.wav';audio.write_bytes(b'fixture');shot['reference_audio_path']=str(audio)
            before=build_seedance_request(project,shot,folder,'原有提示词')['request']
            self.assertEqual(before['template_status'],'needs_confirmation')
            self.assertEqual(before['content'][0]['text'],'原有提示词')
            actor.update(body_template='female',template_confirmed=True,role_name='角色乙')
            after=build_seedance_request(project,shot,folder,'原有提示词')['request']
        self.assertEqual(after['template_status'],'confirmed')
        self.assertEqual(after['media_status'],'ready')
        self.assertEqual(after['model'],'original-model')
        self.assertEqual(after['content'][1:],before['content'][1:])
        self.assertEqual(after['content'][2]['role'],'reference_audio')
        self.assertIn('女型',after['content'][0]['text'])

    @unittest.skipUnless(find_blender(),'Local Blender required')
    def test_blender_build_and_revision_keep_individual_template_metadata(self):
        actors=[]
        for index,template in enumerate(('male','female')):
            actor=copy.deepcopy(actor_fixture());actor.update(id=f'Actor_{index+1:02d}',body_template=template,role_name='模板'+str(index+1))
            for pose in actor['poses']:
                for point in pose['landmarks']:point[0]+=.18 if index else -.18
            actors.append(actor)
        with tempfile.TemporaryDirectory(dir=ROOT/'output/cache') as d:
            folder=Path(d)
            spec={'shot_id':'shot_001','start_frame':13,'end_frame':14,'fps':24,'resolution_x':144,'resolution_y':256,
                  'geometry_profile':'human_v3','render_engine':'workbench','actors':actors,
                  'output_blend':str(folder/'people.blend'),'output_video':str(folder/'people.mp4'),'render_frames':str(folder/'frames/frame')}
            script=folder/'build.py';script.write_text(blender_script(spec),encoding='utf-8');run_blender_script(script,find_blender())
            inspect=folder/'inspect.py';payload=folder/'result.json'
            inspect.write_text('import sys,json,bpy\nsys.path.insert(0,'+repr(str(ROOT))+')\n'+
                'from whiteblock.blender_operations import get_scene_summary,set_body_template,save_revision\n'+
                'before=get_scene_summary()\nset_body_template("Actor_01","female")\nafter=get_scene_summary()\n'+
                'saved=save_revision('+repr(str(folder))+')\n'+
                'open('+repr(str(payload))+',"w",encoding="utf-8").write(json.dumps({"before":before,"after":after,"saved":saved}))\n',encoding='utf-8')
            child=subprocess.run([find_blender(),'-b',str(folder/'people.blend'),'--python-exit-code','1','--python',str(inspect)],capture_output=True,timeout=90)
            self.assertEqual(child.returncode,0,child.stderr.decode(errors='replace'))
            data=json.loads(payload.read_text(encoding='utf-8'))
            before={a['id']:a for a in data['before']['actors']}
            self.assertEqual(before['Actor_01'].get('body_template'),'male')
            self.assertEqual(before['Actor_02'].get('body_template'),'female')
            after={a['id']:a for a in data['after']['actors']}
            self.assertEqual(after['Actor_01']['body_template'],'female')
            self.assertTrue(after['Actor_01']['template_confirmed'])
            self.assertEqual({a['id']:a['body_template'] for a in data['saved']['actors']},{'Actor_01':'female','Actor_02':'female'})


if __name__=='__main__':unittest.main()
