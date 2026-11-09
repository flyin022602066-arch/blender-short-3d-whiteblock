"""Allowlisted Blender operations. No caller-provided source code is executed."""
import json
import math
from pathlib import Path
from datetime import datetime
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
_REGION_CACHE={}


def actor_template_metadata(rig):
    from .actor_profiles import template_profile
    actor=rig.name.removesuffix('_Rig');body=bpy.data.objects.get(actor+'_WhiteModel')
    stored={'id':actor}
    if body:
        for key in ('body_template','template_confirmed','template_source','role_name'):
            if key in body:stored[key]=body[key]
    return {'id':actor,**template_profile(stored)}


def get_scene_summary(**unused):
    scene=bpy.context.scene
    return {'frame':scene.frame_current,'start_frame':scene.frame_start,'end_frame':scene.frame_end,
            'blend_path':bpy.data.filepath,
            'engine':scene.render.engine,'camera':scene.camera.name if scene.camera else None,
            'geometry_profile':scene.get('geometry_profile','legacy'),'objects':len(scene.objects),
            'actors':[{**actor_template_metadata(obj),'rig':obj.name,'bones':len(obj.data.bones),
                       'location':list(obj.location),'scale':list(obj.scale),
                       'hands':{limb:list(obj.matrix_world@obj.pose.bones[bone].tail) for limb,bone in [('left_hand','lowerarm02.L'),('right_hand','lowerarm02.R')] if bone in obj.pose.bones}}
                      for obj in scene.objects if obj.type=='ARMATURE']}


def set_frame(frame):
    scene=bpy.context.scene
    if not scene.frame_start<=int(frame)<=scene.frame_end:raise ValueError('帧超出当前镜头范围')
    scene.frame_set(int(frame));return get_scene_summary()


def get_preview(workspace):
    path=Path(workspace)/'preview.png';scene=bpy.context.scene
    old=scene.render.filepath;scene.render.filepath=str(path);scene.render.image_settings.file_format='PNG'
    try:bpy.ops.render.render(write_still=True)
    finally:scene.render.filepath=old
    return {'image':str(path),'frame':scene.frame_current}


def set_ik_target(actor,limb,position):
    names={'left_hand':('lowerarm02.L',4),'right_hand':('lowerarm02.R',4),
           'left_foot':('lowerleg02.L',4),'right_foot':('lowerleg02.R',4)}
    if limb not in names or len(position)!=3 or not all(math.isfinite(float(x)) and abs(float(x))<1000 for x in position):raise ValueError('无效 IK 参数')
    rig=bpy.data.objects.get(actor+'_Rig')
    if rig is None or rig.type!='ARMATURE':raise ValueError('未找到人物：'+actor)
    name,count=names[limb];bone=rig.pose.bones.get(name)
    if bone is None:raise ValueError('此工程没有标准人体骨架；请用新版重新转换')
    target_name=actor+'_'+limb+'_IK';target=bpy.data.objects.get(target_name)
    if target is None:target=bpy.data.objects.new(target_name,None);bpy.context.scene.collection.objects.link(target)
    target.empty_display_type='SPHERE';target.empty_display_size=.1;target.location=Vector(position)
    target.keyframe_insert('location',frame=bpy.context.scene.frame_current)
    constraint=bone.constraints.get('WhiteblockIK') or bone.constraints.new('IK');constraint.name='WhiteblockIK'
    constraint.target=target;constraint.chain_count=count;constraint.use_stretch=False
    scene=bpy.context.scene;frame=scene.frame_current
    span=(max(scene.frame_start,frame-4),min(scene.frame_end,frame+4))
    for boundary in span:
        if boundary!=frame:
            constraint.influence=0;constraint.keyframe_insert('influence',frame=boundary)
    constraint.influence=1;constraint.keyframe_insert('influence',frame=frame)
    bpy.context.view_layer.update()
    actual=rig.matrix_world@bone.tail
    return {'actor':actor,'limb':limb,'target':list(target.location),'frame':frame,'transition_frames':list(span),
            'target_error':round((actual-target.location).length,5),'note':'仅当前帧附近过渡调整，区间外保留原动作'}


def pose_preset(limb,pose,actor=None):
    rigs=[o for o in bpy.context.scene.objects if o.type=='ARMATURE' and not bpy.data.objects.get(o.name.removesuffix('_Rig')+'_WhiteModel',o).hide_render]
    if not actor:
        if len(rigs)!=1:raise ValueError('当前有多个可见人物，请指定 Actor 编号；可先查看场景')
        actor=rigs[0].name.removesuffix('_Rig')
    rig=bpy.data.objects.get(actor+'_Rig')
    if rig is None:raise ValueError('未找到人物')
    if limb not in ('left_hand','right_hand'):raise ValueError('此预设用于手部')
    side='L' if limb=='left_hand' else 'R'
    shoulder=rig.pose.bones['upperarm01.'+side].head
    if pose=='hand_chest':target=rig.pose.bones['spine02'].head+Vector((-.15 if side=='L' else .15,-.65,.2))
    elif pose=='raise_hand':target=shoulder+Vector((.25 if side=='L' else -.25,-.25,1.3))
    elif pose=='hand_down':target=shoulder+Vector((.18 if side=='L' else -.18,-.15,-1.65))
    else:raise ValueError('未知姿态预设')
    frame=bpy.context.scene.frame_current;remaining=[]
    for attempt in range(5):
        result=set_ik_target(actor,limb,list(rig.matrix_world@(target+Vector((0,-attempt*.2,0)))))
        remaining=[]
        for check_frame in range(result['transition_frames'][0],result['transition_frames'][1]+1):
            bpy.context.scene.frame_set(check_frame);report=check_intersections()
            relevant=[i for i in report['issues'] if i.get('object')==actor+'_WhiteModel' and i.get('regions',[None,None])[1]==('left_forearm' if side=='L' else 'right_forearm')
                      or actor+'_WhiteModel' in i.get('objects',[])]
            if relevant:remaining.append({'frame':check_frame,'issues':relevant})
        bpy.context.scene.frame_set(frame)
        if not remaining:break
    result.update({'clearance_adjustments':attempt,'remaining_contact_issues':remaining})
    if remaining:result['warning']='过渡区间仍有网格相交，请复核并调整 IK 目标后重新渲染'
    return result


def set_body_template(actor,template,role_name=None):
    if template not in ('neutral','male','female'):raise ValueError('人体模板可选 neutral/male/female')
    if role_name is not None and (not isinstance(role_name,str) or len(role_name)>80):raise ValueError('角色名称请控制在80字以内')
    from .blender_human import load_anatomy
    body=bpy.data.objects.get(actor+'_WhiteModel')
    if body is None or body.get('geometry_profile')!='human_v3':raise ValueError('请先载入新版人体')
    vertices=load_anatomy(template)[0]
    if len(vertices)!=len(body.data.vertices):raise ValueError('模板拓扑不匹配')
    for vertex,coordinate in zip(body.data.vertices,vertices):vertex.co=coordinate
    body.data.update();body['body_template']=template;body['template_confirmed']=True;body['template_source']='user'
    if role_name is not None:body['role_name']=role_name.strip() or actor
    if 'whiteblock_spec' in bpy.context.scene:
        spec=json.loads(bpy.context.scene['whiteblock_spec'])
        for key in ('actors','human_actors'):
            for person in spec.get(key,[]):
                if person.get('id')==actor:person.update(actor_template_metadata(body.parent))
        bpy.context.scene['whiteblock_spec']=json.dumps(spec,ensure_ascii=False)
    return {'actor':actor,'template':template,**actor_template_metadata(body.parent),'note':'同拓扑轮廓切换；请复核比例和接触并重渲染'}


def set_camera(scale=None,x=None,z=None):
    camera=bpy.context.scene.camera
    if camera is None:raise ValueError('场景没有相机')
    if scale is not None:
        if not .1<=float(scale)<=100:raise ValueError('相机 scale 超出范围')
        camera.data.ortho_scale=float(scale);camera.data.keyframe_insert('ortho_scale',frame=bpy.context.scene.frame_current)
    for axis,value in [(0,x),(2,z)]:
        if value is not None:
            if not math.isfinite(float(value)) or abs(float(value))>1000:raise ValueError('无效相机坐标')
            camera.location[axis]=float(value)
    camera.keyframe_insert('location',frame=bpy.context.scene.frame_current)
    return {'scale':camera.data.ortho_scale,'location':list(camera.location)}


def check_intersections():
    scene=bpy.context.scene;depsgraph=bpy.context.evaluated_depsgraph_get();surfaces=[];hits=[]
    for obj in scene.objects:
        if obj.type!='MESH' or obj.hide_render or obj.get('geometry_profile')!='human_v3':continue
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh()
        try:
            vertices=[obj.matrix_world@v.co for v in mesh.vertices]
            faces=[tuple(p.vertices) for p in mesh.polygons]
            surfaces.append((obj.name,BVHTree.FromPolygons(vertices,faces,all_triangles=False)))
            key=(bpy.data.filepath,obj.data.as_pointer(),len(mesh.vertices),len(mesh.polygons))
            regions=_REGION_CACHE.get(key)
            if regions is None:
                groups={g.index:g.name for g in obj.vertex_groups}
                regions={'torso':[],'left_forearm':[],'right_forearm':[]}
                for poly in mesh.polygons:
                    scores={'torso':0,'left_forearm':0,'right_forearm':0}
                    for i in poly.vertices:
                        for group in mesh.vertices[i].groups:
                            name=groups.get(group.group,'')
                            label='torso' if name.startswith('spine') else 'left_forearm' if name.startswith('lowerarm') and name.endswith('.L') else 'right_forearm' if name.startswith('lowerarm') and name.endswith('.R') else None
                            if label:scores[label]+=group.weight
                    best=max(scores,key=scores.get)
                    if scores[best]>len(poly.vertices)*.55:regions[best].append(tuple(poly.vertices))
                if len(_REGION_CACHE)>64:_REGION_CACHE.clear()
                _REGION_CACHE[key]=regions
            if regions['torso']:
                torso=BVHTree.FromPolygons(vertices,regions['torso'])
                for label in ('left_forearm','right_forearm'):
                    if regions[label]:
                        overlap=torso.overlap(BVHTree.FromPolygons(vertices,regions[label]))
                        if overlap:hits.append({'object':obj.name,'regions':['torso',label],'surface_pairs':len(overlap)})
        finally:evaluated.to_mesh_clear()
    for i,(name,a) in enumerate(surfaces):
        for other,b in surfaces[i+1:]:
            overlap=a.overlap(b)
            if overlap:hits.append({'objects':[name,other],'surface_pairs':len(overlap)})
    return {'frame':scene.frame_current,'issues':hits,'scope':'当前帧人体间表面交叉、前臂与躯干；不含衣物、道具、全部自碰撞和纯体积包含','checked_actors':len(surfaces)}


def audit_motion(quality_path=None):
    """Audit edited keyframes without silently changing the user's revision."""
    scene=bpy.context.scene;current=scene.frame_current
    quality={'audited_frames':0,'frames_with_initial_issues':0,'remaining_frames':0,'arm_repairs':0,'depth_repairs':0,'remaining':[]}
    try:
        for frame in range(scene.frame_start,scene.frame_end+1):
            scene.frame_set(frame);report=check_intersections();quality['audited_frames']+=1;quality['scope']=report['scope']
            if report['issues']:
                quality['frames_with_initial_issues']+=1;quality['remaining_frames']+=1
                if len(quality['remaining'])<30:quality['remaining'].append({'frame':frame,'issues':report['issues']})
            if (frame-scene.frame_start)%24==0:print('WHITEBLOCK MESH AUDIT',frame,'remaining',quality['remaining_frames'],flush=True)
    finally:scene.frame_set(current)
    scene['mesh_quality']=json.dumps(quality,ensure_ascii=False)
    if quality_path:Path(quality_path).write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    return quality


def save_revision(workspace):
    original=Path(bpy.data.filepath)
    folder=Path(workspace)/'revisions';folder.mkdir(exist_ok=True)
    path=folder/(original.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(path),copy=True)
    return {'blend':str(path),'frame':bpy.context.scene.frame_current,'actors':get_scene_summary()['actors']}


def dispatch(operation,arguments,workspace):
    methods={'get_scene_summary':get_scene_summary,'set_frame':set_frame,'get_preview':get_preview,
             'set_ik_target':set_ik_target,'pose_preset':pose_preset,'set_body_template':set_body_template,
             'set_camera':set_camera,'check_intersections':check_intersections,'save_revision':save_revision}
    if operation not in methods:raise ValueError('未注册操作')
    arguments=dict(arguments)
    if operation in ('get_preview','save_revision'):arguments['workspace']=workspace
    return methods[operation](**arguments)
