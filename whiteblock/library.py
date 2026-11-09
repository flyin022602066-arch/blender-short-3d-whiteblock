"""Persistent local preview catalog. Videos remain in their existing export folders."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from .pipeline import atomic_json, media_tool, probe_media
from .actor_profiles import template_profile


def _json(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,UnicodeError): return {}


def load_library(workspace: Path) -> list[dict]:
    entries=_json(Path(workspace)/'library/index.json').get('entries',[])
    if not isinstance(entries,list):return []
    required=('id','video','directory','project_id','source_name','kind','name','created_at',
              'duration_seconds','width','height','size_bytes','warnings')
    return [e for e in entries if isinstance(e,dict) and all(k in e for k in required)
            and isinstance(e.get('video'),str) and Path(e['video']).is_file()]


def refresh_library(workspace: Path) -> list[dict]:
    workspace=Path(workspace).resolve()
    library=workspace/'library';thumbs=library/'thumbnails';thumbs.mkdir(parents=True,exist_ok=True)
    cached={e['video']:e for e in load_library(workspace)}
    projects={}
    for path in (workspace/'projects').glob('*.json'):
        p=_json(path)
        if p.get('project_id'):projects[p['project_id']]=(p,path)
    entries=[]
    # Only final whiteblock output names are indexed; .part files and source videos are excluded.
    for directory in (workspace/'exports').iterdir() if (workspace/'exports').is_dir() else []:
        if not directory.is_dir():continue
        project,project_path=projects.get(directory.name,({},None))
        manifest=_json(directory/'shot-manifest.json')
        videos=list(directory.glob('shot_*.blender.mp4'))
        if (directory/'whiteblock_preview.mp4').is_file():videos.append(directory/'whiteblock_preview.mp4')
        for video in videos:
            stat=video.stat();fingerprint=f'{stat.st_size}:{stat.st_mtime_ns}'
            old=cached.get(str(video))
            media=old if old and old.get('fingerprint')==fingerprint else probe_media(video)
            if not media.get('available',bool(old)) or not media.get('width') or media.get('duration_seconds',0)<=0:continue
            entry_id=hashlib.sha256(str(video).encode('utf-8')).hexdigest()[:24]
            thumbnail=thumbs/(entry_id+'_'+str(stat.st_mtime_ns)+'.png')
            kind='full' if video.name=='whiteblock_preview.mp4' else 'shot'
            shot_id=video.name.split('.')[0] if kind=='shot' else None
            shot=next((s for s in project.get('shots',[]) if s['shot_id']==shot_id),{})
            if not thumbnail.is_file() and media_tool('ffmpeg'):
                # A contact sheet gives users a useful thumbnail even when the opening shot is empty.
                interval=max(0.1,media['duration_seconds']/3)
                command=[media_tool('ffmpeg'),'-y','-loglevel','error','-i',str(video),'-vf',
                         f'fps=1/{interval},scale=90:128:force_original_aspect_ratio=decrease,pad=90:128:(ow-iw)/2:(oh-ih)/2:color=0x151c23,tile=3x1',
                         '-frames:v','1',str(thumbnail)]
                try:
                    subprocess.run(command,capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except (OSError,subprocess.SubprocessError):pass
            blends=[str(p) for p in sorted(directory.glob('*.blend'))]
            specific=directory/(shot_id+'.blend') if shot_id else None
            version=project.get('geometry_profile') or manifest.get('geometry_profile') or 'legacy'
            quality=project.get('geometry_quality',{})
            warnings=list(project.get('analysis',{}).get('limitations',[]))
            relevant_shots=project.get('shots',[]) if kind=='full' else [shot]
            profiles=[{'shot_id':s['shot_id'],'id':a['id'],**template_profile(a)}
                      for s in relevant_shots if s.get('shot_id') for a in s.get('actors',[])]
            pending=sum(a['template_needs_render'] for a in profiles)
            unconfirmed=sum(not a['template_confirmed'] for a in profiles)
            if pending:warnings.append(f'{pending} 个人物模板已修改，此视频仍为旧模板；请在“人物与模板”应用并重渲染。')
            if unconfirmed:warnings.append(f'{unconfirmed} 个人物模板待确认；请在“人物与模板”确认男型、女型或中性。')
            remaining=quality.get('mesh_audit',{}).get('remaining_frames',0)
            if remaining:warnings.insert(0,f'逐帧网格复核仍有 {remaining} 帧相交，请在 Blender 修正后重新渲染。')
            if kind=='full':
                missing=project.get('analysis',{}).get('shots_without_pose',[])
                if missing:warnings.append('待补充场景或局部人物：'+'、'.join(missing))
            elif not shot.get('actors') and shot.get('reconstruction')=='landmark_proxy':
                warnings.append('此镜头没有可靠完整人体，场景或局部几何待补充。')
            if version=='legacy':warnings.insert(0,'早期白模；建议重新转换以应用人物几何优化。')
            entries.append({'id':entry_id,'video':str(video),'directory':str(directory),'project_id':directory.name,
                'project_path':str(project_path) if project_path else None,'source_name':Path(project.get('source',{}).get('path',directory.name)).name,
                'kind':kind,'shot_id':shot_id,'name':'完整白模' if kind=='full' else shot.get('name',shot_id),
                'created_at':datetime.fromtimestamp(stat.st_mtime,timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M'),
                'modified_ns':stat.st_mtime_ns,'fingerprint':fingerprint,'size_bytes':stat.st_size,
                'duration_seconds':media['duration_seconds'],'width':media['width'],'height':media['height'],'fps':media.get('fps',24),
                'thumbnail':str(thumbnail) if thumbnail.is_file() else None,'blend':str(specific) if specific and specific.is_file() else (blends[0] if blends else None),
                'blend_count':len(blends),'geometry_profile':version,'quality':quality,'warnings':warnings,'available':True})
            entries[-1]['blender_path']=project.get('settings',{}).get('blender_path')
            entries[-1]['actor_templates']=profiles
    entries.sort(key=lambda e:(-e['modified_ns'],0 if e['kind']=='full' else 1,e.get('shot_id') or ''))
    atomic_json(library/'index.json',{'schema_version':1,'entries':entries})
    return entries
