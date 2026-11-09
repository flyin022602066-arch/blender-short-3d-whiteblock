"""Explicit per-track rendering templates; never infer gender from appearance."""
from .pipeline import utc_now

TEMPLATE_LABELS={'neutral':'中性','male':'男型','female':'女型'}


def template_profile(actor):
    template=actor.get('body_template','neutral')
    if template not in TEMPLATE_LABELS:raise ValueError('人物模板请选择男型、女型或中性')
    return {'body_template':template,
            'template_confirmed':actor.get('template_confirmed',template!='neutral') is True,
            'template_source':actor.get('template_source','provided' if template!='neutral' else 'unset'),
            'role_name':actor.get('role_name') or actor['id'],
            'template_needs_render':actor.get('template_needs_render',False) is True}


def actor_profiles(project,shot_id):
    shot=next((s for s in project.get('shots',[]) if s['shot_id']==shot_id),None)
    if shot is None:raise ValueError('不存在镜头 '+str(shot_id))
    return [{'id':a['id'],**template_profile(a)} for a in shot.get('actors',[])]


def update_actor_template(project,shot_id,actor,template,role_name=None):
    if template not in TEMPLATE_LABELS:raise ValueError('人物模板请选择男型、女型或中性')
    shot=next((s for s in project.get('shots',[]) if s['shot_id']==shot_id),None)
    if shot is None:raise ValueError('不存在镜头 '+str(shot_id))
    person=next((a for a in shot.get('actors',[]) if a['id']==actor),None)
    if person is None:raise ValueError('该镜头不存在人物 '+str(actor))
    if role_name is not None and (not isinstance(role_name,str) or len(role_name)>80):raise ValueError('角色名称请控制在80字以内')
    previous=template_profile(person)
    person.update(body_template=template,template_confirmed=True,template_source='user',
                  template_needs_render=previous['template_needs_render'] or previous['body_template']!=template)
    if role_name is not None:person['role_name']=role_name.strip() or actor
    shot['status']='needs_review';project['status']='needs_review'
    project.setdefault('history',[]).append({'timestamp':utc_now(),'status':'needs_review',
        'message':f'{shot_id} / {actor} 确认人物模板：{TEMPLATE_LABELS[template]}；修改后需重渲染'})
    return {'id':actor,'shot_id':shot_id,**template_profile(person)}
