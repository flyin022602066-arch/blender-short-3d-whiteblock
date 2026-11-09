"""Measured screen motion with explicit, conservative proxy geometry constraints."""
from __future__ import annotations
import bisect
import math
from statistics import median

PROFILE = 'mannequin_v2'


def distance(a, b):
    return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))


def screen_width(points):
    return math.hypot(points[11][0]-points[12][0],points[11][1]-points[12][1])


def _samples(actor, fps):
    samples = sorted(actor.get('poses', []),key=lambda p:p['frame'])
    result = []
    for index,sample in enumerate(samples):
        points = [p[:] for p in sample['landmarks']]
        if len(points) != 33: continue
        if 0 < index < len(samples)-1 and samples[index+1]['frame']-samples[index-1]['frame'] < fps*0.7:
            for j,p in enumerate(points):
                if p[3] >= 0.45 and min(samples[index-1]['landmarks'][j][3],samples[index+1]['landmarks'][j][3]) >= 0.45:
                    for axis in range(3):
                        neighbors = [samples[index-1]['landmarks'][j][axis],p[axis],samples[index+1]['landmarks'][j][axis]]
                        p[axis] = 0.6*p[axis] + 0.4*median(neighbors)
        result.append({**sample,'landmarks':points})
    return result


def _interpolate(samples, frame, fps):
    frames = [s['frame'] for s in samples]
    index = bisect.bisect_left(frames,frame)
    if index < len(samples) and frames[index] == frame: return samples[index]
    if index == 0 or index == len(samples): return None
    a,b = samples[index-1],samples[index]
    if b['frame']-a['frame'] > fps*0.6: return None
    t=(frame-a['frame'])/(b['frame']-a['frame'])
    return {'frame':frame,'confidence':a.get('confidence',0.5)*(1-t)+b.get('confidence',0.5)*t,
            'landmarks':[[x*(1-t)+y*t for x,y in zip(p,q)] for p,q in zip(a['landmarks'],b['landmarks'])]}


def _arm_hits(joints, center, half_width, half_height, depth, radius):
    count = 0
    for a,b in [(13,15),(14,16)]:
        for t in [0.1,0.3,0.5,0.7,0.9]:
            p=[joints[a][i]*(1-t)+joints[b][i]*t-center[i] for i in range(3)]
            # A conservative ellipsoid expanded by the limb radius.
            if (p[0]/(half_width+radius))**2 + (p[1]/(depth+radius))**2 + (p[2]/(half_height+radius))**2 < 1:
                count+=1
    return count


def optimize_actors(actors, start_frame, end_frame, fps, view_width, view_height):
    candidates=[]
    for actor in actors:
        samples=_samples(actor,fps)
        if not samples: continue
        widths=[screen_width(s['landmarks'])*view_width for s in samples]
        width=max(0.15,min(view_width*0.65,median(widths)))
        candidates.append({'id':actor['id'],'confidence':actor.get('confidence',0),
                           'samples':samples,'width':width,'animation':[]})
    # Bigger screen subjects receive the nearer depth layer. This is an approximation.
    candidates.sort(key=lambda a:(-a['width'],a['id']))
    quality={'profile':PROFILE,'duplicate_samples_removed':0,'arm_torso_intersections_before':0,
             'arm_torso_intersections_after':0,'baked_pose_frames':0,
             'collision_scope':'conservative forearm/torso shell and separate actor depth bands',
             'limitations':['人物深度采用分层近似；未恢复真实接触关系。','关键点漏检和关节误判仍需人工复核。']}
    next_depth=0
    for c in candidates:
        span=c['width']*0.9
        c['depth']=next_depth+span
        c['depth_bounds']=[next_depth,next_depth+span*2]
        next_depth+=span*2+0.1
    for frame in range(start_frame,end_frame+1):
        accepted=[]
        observed=[(c,_interpolate(c['samples'],frame,fps)) for c in candidates]
        observed=[(c,s) for c,s in observed if s]
        observed.sort(key=lambda pair:-pair[1].get('confidence',0))
        for c,sample in observed:
            p=sample['landmarks']; nose=p[0]
            threshold=max(0.025,min(0.1,screen_width(p)*0.28))
            if any(math.hypot(nose[0]-a[0],nose[1]-a[1]) < threshold for a in accepted):
                quality['duplicate_samples_removed']+=1
                continue
            accepted.append(nose)
            width=max(c['width']*0.75,min(c['width']*1.25,screen_width(p)*view_width))
            joints=[[ (q[0]-0.5)*view_width, c['depth'], (0.5-q[1])*view_height ] for q in p]
            shoulders=[(joints[11][i]+joints[12][i])/2 for i in range(3)]
            hips=[(joints[23][i]+joints[24][i])/2 for i in range(3)]
            if min(p[23][3],p[24][3]) < 0.45 or not width*0.65 <= distance(shoulders,hips) <= width*2.6:
                hips=[shoulders[0],c['depth'],shoulders[2]-width*1.6]
                joints[23]=[hips[0]-width*0.3,c['depth'],hips[2]]
                joints[24]=[hips[0]+width*0.3,c['depth'],hips[2]]
            center=[(shoulders[i]+hips[i])/2 for i in range(3)]
            height=distance(shoulders,hips)
            body_depth=width*0.22
            radius=width*0.075
            before=_arm_hits(joints,center,width*0.46,height*0.55,body_depth,radius)
            quality['arm_torso_intersections_before']+=before
            # Retain measured X/Z; move folded arms to the front surface instead of through the chest.
            for j in (11,12,13,14,15,16):
                joints[j][1]=c['depth']-body_depth-radius-width*0.025
            quality['arm_torso_intersections_after']+=_arm_hits(joints,center,width*0.46,height*0.55,body_depth,radius)
            c['animation'].append({'frame':frame,'joints':{str(j):[round(v,6) for v in q] for j,q in enumerate(joints)},
                                   'visibility':{str(j):round(p[j][3],4) for j in range(33)},
                                   'width':round(width,6),'body_center':center,'hips':hips,'shoulders':shoulders,
                                   'body_height':height,'body_depth':body_depth,'confidence':sample.get('confidence',0)})
            quality['baked_pose_frames']+=1
    result=[]
    for c in candidates:
        if len(c['animation']) < 2: continue
        result.append({k:v for k,v in c.items() if k not in ('samples','width','depth')})
    return {'actors':result,'quality':quality}
