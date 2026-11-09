"""Desktop-managed live Blender session and immutable preview revisions."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import secrets
import socket
import subprocess
import time
from .blender_mcp import BlenderMCPClient
from .pipeline import ROOT,atomic_json,find_blender,run_blender_script,load_project,save_project,sha256

class BlenderSession:
    def __init__(self):self.client=None;self.process=None;self.session_path=None

    def start(self,blend_path,blender_path=None):
        if self.client:
            try:return self.client.call('get_scene_summary')
            except Exception:self.close()
        executable=find_blender(blender_path)
        if not executable:raise FileNotFoundError('请先设置本地 Blender 路径')
        blend=Path(blend_path)
        if not blend.is_file():raise FileNotFoundError('当前镜头尚未生成 Blender 工程')
        for existing in sorted((ROOT/'output/cache/blender_sessions').glob('*/session.json'),reverse=True):
            try:
                info=json.loads(existing.read_text(encoding='utf-8'))
                if info.get('ready') and info.get('bridge_revision')==2 and info.get('blend_path')==str(blend.resolve()):
                    from .blender_mcp import bridge_call
                    status=bridge_call(existing,'get_scene_summary',{})
                    self.session_path=existing;self.client=BlenderMCPClient(existing);return status
            except (OSError,ValueError,RuntimeError):continue
        directory=ROOT/'output/cache/blender_sessions'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');directory.mkdir(parents=True)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        self.session_path=directory/'session.json';atomic_json(self.session_path,{'host':'127.0.0.1','port':port,'token':secrets.token_urlsafe(32),'ready':False,'blend_path':str(blend.resolve()),'bridge_revision':2})
        with (directory/'blender.log').open('w',encoding='utf-8') as log:
            self.process=subprocess.Popen([executable,str(blend),'--python',str(ROOT/'whiteblock/blender_bridge.py'),'--',str(self.session_path)],stdout=log,stderr=subprocess.STDOUT,
                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise RuntimeError('Blender 启动失败；日志：'+str(directory/'blender.log'))
            try:
                if json.loads(self.session_path.read_text(encoding='utf-8')).get('ready'):
                    self.client=BlenderMCPClient(self.session_path);return self.client.call('get_scene_summary')
            except (OSError,ValueError):pass
            time.sleep(.2)
        raise TimeoutError('Blender MCP 未就绪；日志：'+str(directory/'blender.log'))

    def call(self,name,**args):
        if not self.client:raise ValueError('请先连接 Blender 交互会话')
        return self.client.call(name,**args)

    def render_revision(self,project_path,shot_id,progress=None):
        saved=self.call('save_revision');original=load_project(Path(project_path))
        shot=next(s for s in original['shots'] if s['shot_id']==shot_id)
        pid=original['project_id']+'_edit_'+datetime.now().strftime('%H%M%S_%f')
        root=Path(original['workspace_root']);out=root/'exports'/pid;out.mkdir(parents=True)
        project={**original,'project_id':pid,'shots':[dict(shot)],'status':'needs_review','revision_of':original['project_id']}
        profiles={a['id']:a for a in saved.get('actors',[])}
        project['shots'][0]['actors']=[dict(a) for a in shot.get('actors',[])]
        for actor in project['shots'][0]['actors']:
            profile=profiles.get(actor['id'])
            if profile:
                for key in ('body_template','template_confirmed','template_source','role_name'):
                    if key in profile:actor[key]=profile[key]
                actor['template_needs_render']=False
        spec={'shot_id':shot_id,'start_frame':shot['start_frame'],'end_frame':shot['end_frame'],'fps':shot['fps'],
              'output_blend':str(out/(shot_id+'.blend')),'output_video':str(out/(shot_id+'.blender.mp4')),
              'quality_path':str(out/(shot_id+'.quality.json')),
              'render_frames':str(root/'cache'/pid/'render/frame')}
        script=out/(shot_id+'.blender.py')
        script.write_text('import bpy,sys\nfrom pathlib import Path\nspec = '+repr(spec)+'\n'+
            'sys.path.insert(0,'+repr(str(ROOT))+')\nfrom whiteblock.blender_operations import audit_motion\n'+
            'bpy.ops.wm.open_mainfile(filepath='+repr(saved['blend'])+')\n'+
            'scene=bpy.context.scene\nscene.frame_start=spec["start_frame"];scene.frame_end=spec["end_frame"]\n'+
            'audit_motion(spec["quality_path"])\nscene.frame_set(scene.frame_start)\n'+
            'scene.render.filepath=spec["render_frames"]\nscene.render.image_settings.file_format="PNG"\n'+
            'bpy.ops.wm.save_as_mainfile(filepath=spec["output_blend"])\nPath(scene.render.filepath).parent.mkdir(parents=True,exist_ok=True)\n'+
            'bpy.ops.render.render(animation=True)\n',encoding='utf-8')
        result=run_blender_script(script,original.get('settings',{}).get('blender_path'),progress=progress)
        project['shots'][0].update({'whiteblock_blend_path':spec['output_blend'],'whiteblock_video_path':spec['output_video']})
        report=json.loads(Path(spec['quality_path']).read_text(encoding='utf-8'))
        project['geometry_quality']={'mesh_audit':report,'collision_scope':report.get('scope','')}
        project['media']={**original.get('media',{}),'frame_count':shot['end_frame']-shot['start_frame']+1,
                          'fps':shot['fps'],'duration_seconds':(shot['end_frame']-shot['start_frame']+1)/shot['fps']}
        project['analysis']={**original.get('analysis',{}),'shots_without_pose':[shot_id] if shot_id in original.get('analysis',{}).get('shots_without_pose',[]) else []}
        # This revision contains one edited shot; never mislabel it as a complete episode.
        project.pop('whiteblock_preview_path',None);project.pop('last_manifest',None)
        target=root/'projects'/(pid+'.json');save_project(target,project)
        manifest={'project_id':pid,'geometry_profile':project.get('geometry_profile'),'revision_of':original['project_id'],
                  'geometry_quality':project['geometry_quality'],
                  'outputs':[{'path':p,'sha256':sha256(Path(p))} for p in result['outputs']]}
        manifest['outputs'].append({'path':spec['quality_path'],'sha256':sha256(Path(spec['quality_path'])),'kind':'mesh_quality'})
        atomic_json(out/'shot-manifest.json',manifest)
        from .library import refresh_library
        refresh_library(root)
        return {'project_path':str(target),'video':spec['output_video'],'blend':spec['output_blend'],'directory':str(out),'kind':'shot'}

    def close(self):
        if self.client:self.client.close();self.client=None
        # Leave the visible editor and unsaved user work open.
