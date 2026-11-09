"""Blender-only trusted human construction and retargeting, shared by CLI and MCP."""
import json
import gzip
import hashlib
import math
from functools import lru_cache
from pathlib import Path
import bpy
from mathutils import Vector, Matrix, Quaternion

ASSETS=Path(__file__).resolve().parents[1]/'output/models/makehuman_cc0'


@lru_cache(maxsize=3)
def load_anatomy(body_template='neutral'):
    manifest=json.loads((ASSETS/'asset-manifest.json').read_text(encoding='utf-8'))
    for asset in manifest['assets']:
        if hashlib.sha256((ASSETS/asset['filename']).read_bytes()).hexdigest()!=asset['sha256']:raise ValueError('人体资产校验失败：'+asset['filename'])
    vertices=[];faces=[];group=''
    for line in (ASSETS/'base.obj').read_text(encoding='utf-8').splitlines():
        fields=line.split()
        if not fields:continue
        if fields[0]=='v':
            x,y,z=map(float,fields[1:4]);vertices.append(Vector((x,-z,y)))
        elif fields[0]=='g':group=fields[1]
        elif fields[0]=='f' and group=='body':faces.append(tuple(int(f.split('/')[0])-1 for f in fields[1:]))
    for gender,weight in [('male',1 if body_template=='male' else 0 if body_template=='female' else .5),('female',1 if body_template=='female' else 0 if body_template=='male' else .5)]:
        for ethnicity in ('african','asian','caucasian'):
            target=ASSETS/f'{ethnicity}-{gender}-young.target.gz'
            for line in gzip.decompress(target.read_bytes()).decode('utf-8').splitlines():
                if line.startswith('#') or not line.strip():continue
                i,x,y,z=line.split();vertices[int(i)]+=Vector((float(x),-float(z),float(y)))*(weight/3)
    skeleton=json.loads((ASSETS/'default.mhskel').read_text(encoding='utf-8'))
    weights=json.loads((ASSETS/'default_weights.mhw').read_text(encoding='utf-8'))['weights']
    joints={name:sum((vertices[i] for i in indices),Vector())/len(indices) for name,indices in skeleton['joints'].items()}
    bones=skeleton['bones']
    shoulder_width=(joints[bones['upperarm01.L']['head']]-joints[bones['upperarm01.R']['head']]).length
    hip=(joints[bones['upperleg01.L']['head']]+joints[bones['upperleg01.R']['head']])/2
    vertices=[(v-hip)/shoulder_width for v in vertices]
    joints={k:(v-hip)/shoulder_width for k,v in joints.items()}
    # Drop invisible helper vertices while preserving original indices for skin weights.
    used=sorted({i for f in faces for i in f});mapping={old:new for new,old in enumerate(used)}
    return [vertices[i] for i in used],[tuple(mapping[i] for i in f) for f in faces],joints,bones,weights,mapping


def create_human(actor,collection,material,anatomy):
    vertices,faces,joints,bones,weights,mapping=anatomy
    armature=bpy.data.armatures.new(actor['id']+'_Skeleton');rig=bpy.data.objects.new(actor['id']+'_Rig',armature)
    collection.objects.link(rig);rig.show_in_front=False
    rig['geometry_profile']='human_v3';rig['asset_license']='CC0';rig['pose_mode']='world/image fitted; verify camera and contacts'
    bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
    bpy.ops.object.mode_set(mode='EDIT')
    root=armature.edit_bones.new('Root');root.head=(0,0,0);root.tail=(0,0,.35);root.use_deform=False
    for name,data in bones.items():
        bone=armature.edit_bones.new(name);bone.head=joints[data['head']];bone.tail=joints[data['tail']]
        if (bone.tail-bone.head).length<.0001:bone.tail=bone.head+Vector((0,0,.01))
        bone.align_roll(Vector((0,-1,0)))
    for name,data in bones.items():
        armature.edit_bones[name].parent=armature.edit_bones.get(data.get('parent') or 'Root') or root
    bpy.ops.object.mode_set(mode='OBJECT')
    data=bpy.data.meshes.new(actor['id']+'_Body');data.from_pydata(vertices,[],faces);data.update()
    body=bpy.data.objects.new(actor['id']+'_WhiteModel',data);collection.objects.link(body);body.parent=rig
    body['geometry_profile']='human_v3';body['asset_license']='CC0';body.data.materials.append(material)
    body['body_template']=actor.get('body_template','neutral')
    body['template_confirmed']=actor.get('template_confirmed',body['body_template']!='neutral')
    body['template_source']=actor.get('template_source','provided' if body['template_confirmed'] else 'unset')
    body['role_name']=actor.get('role_name',actor['id'])
    for polygon in data.polygons:polygon.use_smooth=True
    for name,entries in weights.items():
        group=body.vertex_groups.new(name=name)
        for old,weight in entries:
            if old in mapping:group.add([mapping[old]],weight,'REPLACE')
    modifier=body.modifiers.new('HumanDeformation','ARMATURE');modifier.object=rig;modifier.use_deform_preserve_volume=True
    smooth=body.modifiers.new('AnatomicalSurface','SUBSURF');smooth.levels=1;smooth.render_levels=1
    rig.scale=(actor['scale'],)*3
    return rig,body


def aim(rig,name,direction):
    bone=rig.pose.bones.get(name)
    if not bone or direction.length<.001:return
    # Rotation-only retargeting preserves the template's bone lengths and joint hierarchy.
    rest_global=bone.bone.matrix_local.to_quaternion()
    desired=(rest_global@Vector((0,1,0))).rotation_difference(direction.normalized())@rest_global
    parent=bone.parent
    relative=parent.matrix.to_quaternion().inverted()@desired if parent else desired
    rest=parent.bone.matrix_local.to_quaternion().inverted()@bone.bone.matrix_local.to_quaternion() if parent else bone.bone.matrix_local.to_quaternion()
    bone.rotation_mode='QUATERNION';bone.rotation_quaternion=rest.inverted()@relative
    bpy.context.view_layer.update()


def clear_forearms(rig,joints,force=(),clearance=.08):
    """Small depth repair only for a verified deformed-mesh intersection."""
    front=(rig.matrix_world.to_3x3().inverted()@Vector((0,-1,0))).normalized()
    fixes=0
    for side,wrist in [('L',15),('R',16)]:
        first=rig.pose.bones['lowerarm01.'+side];last=rig.pose.bones['lowerarm02.'+side]
        if side not in force:continue
        shoulder=rig.pose.bones['upperarm01.'+side].head.copy()
        elbow=first.head.copy()+front*clearance
        hand=last.tail.copy()+front*clearance*2
        for name in ('upperarm01.','upperarm02.'):aim(rig,name+side,elbow-shoulder)
        current_elbow=rig.pose.bones['lowerarm01.'+side].head
        for name in ('lowerarm01.','lowerarm02.'):aim(rig,name+side,hand-current_elbow)
        fixes+=1
    return fixes


def separate_actor_depth(first_body,second_body):
    """Move the rear actor beyond the actual deformed surface, in camera depth."""
    first,second=first_body.parent,second_body.parent
    rear_body,front_body=(first_body,second_body) if first.location.y>second.location.y else (second_body,first_body)
    graph=bpy.context.evaluated_depsgraph_get()
    bounds=[]
    for body in (rear_body,front_body):
        evaluated=body.evaluated_get(graph);mesh=evaluated.to_mesh()
        try:
            depth=[(evaluated.matrix_world@vertex.co).y for vertex in mesh.vertices]
            bounds.append((min(depth),max(depth)))
        finally:evaluated.to_mesh_clear()
    margin=max(first.scale.x,second.scale.x)*.02
    rear_body.parent.location.y+=max(margin,bounds[1][1]-bounds[0][0]+margin)
    rear_body.parent.keyframe_insert('location',frame=bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def audit_pose_directions(spec):
    """Measure baked bone directions; inferred chains are counted separately."""
    scene=bpy.context.scene;current=scene.frame_current;groups={};bones={};worst=[]
    actors={a['id']:{s['frame']:s for s in a['animation']} for a in spec.get('human_actors',[])}
    frames=sorted({f for samples in actors.values() for f in samples})
    chains=[('upperarm01.L',11,13),('lowerarm01.L',13,15),('upperarm01.R',12,14),('lowerarm01.R',14,16),
            ('upperleg01.L',23,25),('lowerleg01.L',25,27),('upperleg01.R',24,26),('lowerleg01.R',26,28)]
    def add(target,key,angle,screen_angle):
        row=target.setdefault(key,{'count':0,'sum':0,'max_degrees':0,'screen_count':0,'screen_sum':0,'screen_max_degrees':0})
        row['count']+=1;row['sum']+=angle;row['max_degrees']=max(row['max_degrees'],angle)
        if screen_angle is not None:
            row['screen_count']+=1;row['screen_sum']+=screen_angle
            row['screen_max_degrees']=max(row['screen_max_degrees'],screen_angle)
    try:
        for frame in frames:
            scene.frame_set(frame)
            for actor,samples in actors.items():
                sample=samples.get(frame);rig=bpy.data.objects.get(actor+'_Rig')
                if not sample or not rig or rig.hide_render:continue
                for name,j1,j2 in chains:
                    source=sample.get('joint_sources',{}).get(name.replace('01',''))
                    if not source:
                        if min(sample.get('visibility',{}).get(str(j1),0),sample.get('visibility',{}).get(str(j2),0))<.45:continue
                        source='measured'
                    desired=Vector(sample['joints'][str(j2)])-Vector(sample['joints'][str(j1)])
                    bone=rig.pose.bones.get(name)
                    if not bone or desired.length<.001:continue
                    actual=rig.matrix_world.to_3x3()@(bone.tail-bone.head)
                    angle=math.degrees(actual.angle(desired));screen_angle=None
                    screen=sample.get('screen_landmarks',{})
                    if source=='measured' and str(j1) in screen and str(j2) in screen:
                        a,b=screen[str(j1)],screen[str(j2)]
                        target=Vector(((b[0]-a[0])*spec['resolution_x'],(a[1]-b[1])*spec['resolution_y']))
                        projected=Vector((actual.x,actual.z))
                        if min(target.length,projected.length)>.001:screen_angle=math.degrees(projected.angle(target))
                    add(groups,source,angle,screen_angle);add(bones,name,angle,screen_angle)
                    if angle>15:worst.append({'frame':frame,'actor':actor,'bone':name,'source':source,'degrees':round(angle,3)})
    finally:scene.frame_set(current)
    for table in (groups,bones):
        for row in table.values():
            row['mean_degrees']=round(row.pop('sum')/row['count'],4)
            row['max_degrees']=round(row['max_degrees'],4)
            screen_sum=row.pop('screen_sum')
            row['screen_mean_degrees']=round(screen_sum/row['screen_count'],4) if row['screen_count'] else None
            row['screen_max_degrees']=round(row['screen_max_degrees'],4) if row['screen_count'] else None
    return {'audited_frames':len(frames),'sources':groups,'bones':bones,
            'worst':sorted(worst,key=lambda r:-r['degrees'])[:30],
            'scope':'骨骼方向与拟合目标、可见视频关节的屏幕方向；不代表真实三维位置误差或完整动作恢复'}


def finalize_motion(spec):
    from .blender_operations import check_intersections
    scene=bpy.context.scene
    frames={a['id']:{p['frame']:p for p in a['animation']} for a in spec.get('human_actors',[])}
    quality={'audited_frames':0,'frames_with_initial_issues':0,'remaining_frames':0,'arm_repairs':0,'depth_repairs':0,
             'scope':'每帧人体间表面交叉、前臂与躯干；不含全部自碰撞、衣物、道具和纯体积包含','remaining':[]}
    if not frames:
        scene['mesh_quality']=json.dumps(quality,ensure_ascii=False)
        if spec.get('quality_path'):Path(spec['quality_path']).write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    # A second traversal evaluates saved keyframes after all edits. This catches
    # dependency-graph changes that are not visible in the immediate repair check.
    for step in range(2*(scene.frame_end-scene.frame_start+1)):
        count=scene.frame_end-scene.frame_start+1;verification=step>=count
        frame=scene.frame_start+step%count
        scene.frame_set(frame);report=check_intersections()
        if not verification:
            quality['audited_frames']+=1
            if report['issues']:quality['frames_with_initial_issues']+=1
        for attempt in range(4):
            if not report['issues']:break
            for issue in report['issues']:
                if 'object' in issue:
                    actor=issue['object'].removesuffix('_WhiteModel');sample=frames.get(actor,{}).get(frame)
                    if not sample:continue
                    rig=bpy.data.objects[actor+'_Rig'];joints={int(k):Vector(v) for k,v in sample['joints'].items()}
                    side='L' if issue['regions'][1]=='left_forearm' else 'R'
                    clear_forearms(rig,joints,force=(side,),clearance=.08+attempt*.04)
                    for name in ('upperarm01.','upperarm02.','lowerarm01.','lowerarm02.'):
                        rig.pose.bones[name+side].keyframe_insert('rotation_quaternion',frame=frame)
                    quality['arm_repairs']+=1
                else:
                    separate_actor_depth(*(bpy.data.objects[n] for n in issue['objects']))
                    quality['depth_repairs']+=1
            bpy.context.view_layer.update();scene.frame_set(frame);report=check_intersections()
        if verification and report['issues']:
            quality['remaining_frames']+=1
            if len(quality['remaining'])<30:quality['remaining'].append({'frame':frame,'issues':report['issues']})
        if (frame-scene.frame_start)%24==0:print('WHITEBLOCK MESH AUDIT',frame,'remaining',quality['remaining_frames'],'pass',2 if verification else 1,flush=True)
    quality['verification_passes']=2
    quality['pose_audit']=audit_pose_directions(spec)
    scene['mesh_quality']=json.dumps(quality,ensure_ascii=False)
    if spec.get('quality_path'):Path(spec['quality_path']).write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    scene.frame_set(scene.frame_start)


def bake_human(rig,body,actor,spec):
    samples={s['frame']:s for s in actor['animation']}
    for frame in range(spec['start_frame'],spec['end_frame']+1):
        bpy.context.scene.frame_set(frame)
        sample=samples.get(frame)
        for obj in (body,rig):
            obj.hide_render=obj.hide_viewport=sample is None
            obj.keyframe_insert('hide_render',frame=frame);obj.keyframe_insert('hide_viewport',frame=frame)
        if not sample:continue
        v={int(k):Vector(q) for k,q in sample['joints'].items()};visibility=sample['visibility']
        rig.location=sample['root'];rig.keyframe_insert('location',frame=frame)
        lateral=v[11]-v[12]
        if lateral.length>.01:
            yaw=math.atan2(lateral.y,lateral.x)
            rig.rotation_mode='QUATERNION';rig.rotation_quaternion=Quaternion((0,0,1),yaw)
            rig.keyframe_insert('rotation_quaternion',frame=frame)
        bpy.context.view_layer.update()
        inverse_rotation=rig.rotation_quaternion.inverted()
        shoulder=(v[11]+v[12])/2;hip=Vector(sample['root']);up=shoulder-hip
        targets={'spine05':up,'spine04':up,'spine03':up,'spine02':up,'spine01':up,
                 'neck01':up,'neck02':up,'neck03':up,'head':up}
        for side,a,b,c,h,k,f in [('L',11,13,15,23,25,27),('R',12,14,16,24,26,28)]:
            for name,j1,j2 in [('upperarm01',a,b),('upperarm02',a,b),('lowerarm01',b,c),('lowerarm02',b,c),
                               ('upperleg01',h,k),('upperleg02',h,k),('lowerleg01',k,f),('lowerleg02',k,f)]:
                observed=min(visibility[str(j1)],visibility[str(j2)])>=.45
                if j1>=23:
                    screen=sample.get('screen_landmarks',{})
                    observed=observed and all(-.05<=screen.get(str(j),[.5,.5])[1]<=1.05 for j in (h,k,f))
                source=sample.get('joint_sources',{}).get(name.removesuffix('01').removesuffix('02')+'.'+side)
                if source or observed:targets[name+'.'+side]=v[j2]-v[j1]
                elif j1>=23:
                    rig.pose.bones[name+'.'+side].rotation_mode='QUATERNION';rig.pose.bones[name+'.'+side].rotation_quaternion=Quaternion()
                    targets[name+'.'+side]=None
        # Parent-first evaluation is required for rotation-only skinning.
        for bone in sorted(rig.pose.bones,key=lambda b:len(b.parent_recursive)):
            if bone.name in targets and targets[bone.name] is not None:aim(rig,bone.name,inverse_rotation@targets[bone.name])
        keyed=set(targets)
        keyed.update(name+side for side in ('L','R') for name in ('upperarm01.','upperarm02.','lowerarm01.','lowerarm02.'))
        for name in keyed:
            bone=rig.pose.bones.get(name)
            if bone:bone.keyframe_insert('rotation_quaternion',frame=frame)


def setup_scene(spec):
    scene=bpy.context.scene;scene.frame_start=spec['start_frame'];scene.frame_end=spec['end_frame']
    scene.render.fps=round(spec['fps']);scene.render.fps_base=round(spec['fps'])/spec['fps']
    scene.render.resolution_x=spec['resolution_x'];scene.render.resolution_y=spec['resolution_y'];scene.render.resolution_percentage=100
    mode=spec.get('render_engine','eevee')
    scene.render.engine={'eevee':'BLENDER_EEVEE','cycles':'CYCLES','workbench':'BLENDER_WORKBENCH'}[mode]
    if mode=='cycles':scene.cycles.samples=32;scene.cycles.use_denoising=True
    if mode=='eevee':scene.eevee.taa_render_samples=16
    scene.display.render_aa='32';scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL'
    scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
    scene.world=bpy.data.worlds.new('WhiteblockWorld');scene.world.color=(.13,.15,.18)
    scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.14,.17,.21,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.6
    scene.view_settings.view_transform='AgX'
    material=bpy.data.materials.new('ClayWhite');material.diffuse_color=(.8,.8,.8,1);material.use_nodes=True
    shader=material.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=(.8,.8,.8,1);shader.inputs['Roughness'].default_value=.8
    collection=bpy.data.collections.new('CHARACTERS');scene.collection.children.link(collection)
    bpy.ops.object.camera_add(location=(0,-30,0));camera=bpy.context.object;camera.name='CompositionCamera_APPROXIMATE'
    camera.rotation_euler=(math.pi/2,0,0);camera.data.type='ORTHO';camera.data.ortho_scale=10;camera.data.sensor_fit='VERTICAL';scene.camera=camera
    for name,location,energy,size in [('Key',(-6,-10,9),1700,8),('Fill',(6,-7,3),1000,7),('Rim',(0,5,8),1300,6)]:
        bpy.ops.object.light_add(type='AREA',location=location);light=bpy.context.object;light.name=name
        light.data.energy=energy;light.data.shape='DISK';light.data.size=size;light.rotation_euler=(-Vector(location)).to_track_quat('-Z','Y').to_euler()
    for actor in spec.get('human_actors',[]):
        anatomy=load_anatomy(actor.get('body_template',spec.get('body_template','neutral')))
        rig,body=create_human(actor,collection,material,anatomy);bake_human(rig,body,actor,spec)
    scene['geometry_profile']='human_v3';scene['limitations']='Template human; world/image pose estimate; camera, occlusion and contacts require review.'
    scene['source_video']=spec.get('source_path','');scene['whiteblock_spec']=json.dumps(spec,ensure_ascii=False)
    # Store the original video as an optional camera reference, not a rendered substitute.
    source=spec.get('source_path')
    if source and Path(source).is_file():
        image=bpy.data.images.load(source,check_existing=True);image.source='MOVIE'
        bg=camera.data.background_images.new();bg.image=image;bg.alpha=.4
        bg.image_user.frame_duration=spec.get('source_frame_count',scene.frame_end);camera.data.show_background_images=False
    for obj in list(collection.objects):
        if not obj.animation_data or not obj.animation_data.action:continue
        for layer in obj.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:point.interpolation='CONSTANT' if curve.data_path.startswith('hide_') else 'LINEAR'
    finalize_motion(spec)
    scene.frame_set(scene.frame_start)
    return scene
