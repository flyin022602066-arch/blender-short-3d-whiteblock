"""Fit measured image/world landmarks to a constant-size articulated human prior."""
from __future__ import annotations
from statistics import median
import bisect
import math
from .pose_cleanup import _samples, distance, screen_width
from .actor_profiles import template_profile

PROFILE='human_v3'


def _at(samples,frame,fps):
    frames=[p['frame'] for p in samples];i=bisect.bisect_left(frames,frame)
    if i<len(samples) and frames[i]==frame:return samples[i]
    if i==0 or i==len(samples):
        sample=samples[0 if i==0 else -1]
        return sample if abs(sample['frame']-frame)<=fps*0.2 else None
    a,b=samples[i-1],samples[i]
    if b['frame']-a['frame']>fps*0.75:return None
    t=(frame-a['frame'])/(b['frame']-a['frame']);result={'frame':frame,'confidence':min(a.get('confidence',.5),b.get('confidence',.5))}
    result['pose_source']=a.get('pose_source','landmarks') if a.get('pose_source')==b.get('pose_source') else 'mixed_prior' if any(p.get('pose_source')=='anatomical_prior' for p in (a,b)) else 'landmarks'
    if a.get('face_bbox') and b.get('face_bbox'):result['face_bbox']=[x*(1-t)+y*t for x,y in zip(a['face_bbox'],b['face_bbox'])]
    for key in ('landmarks','world_landmarks'):
        if len(a.get(key,[]))==33 and len(b.get(key,[]))==33:
            result[key]=[[x*(1-t)+y*t for x,y in zip(p,q)] for p,q in zip(a[key],b[key])]
    return result


def fit_humans(actors,start_frame,end_frame,fps,view_width,view_height):
    quality={'profile':PROFILE,'world_pose_samples':0,'fallback_pose_samples':0,'baked_pose_frames':0,
              'duplicate_samples_removed':0,'arm_clearance_adjustments':0,'prior_pose_frames':0,
              'temporal_limb_frames':0,'standing_limb_frames':0,
              'collision_scope':'measured poses retained; deformed mesh checks in Blender'}
    people=[]
    for actor in actors:
        samples=_samples(actor,fps)
        if not samples:continue
        widths=[max(screen_width(p['landmarks'])*view_width,(p.get('face_bbox') or [0,0,0,0])[3]*view_height*1.4) for p in samples]
        scale=max(.15,min(view_width*.7,median(widths)))
        people.append({'id':actor['id'],**template_profile(actor),'scale':scale,'samples':samples,'animation':[],
                       'limb_history':{},'confidence':actor.get('confidence',.5)})
    people.sort(key=lambda p:(-p['scale'],p['id']))
    # Keep actor layers only as a bounded initialisation, while preserving intra-body depth.
    layer=0
    for person in people:
        person['depth']=layer;layer+=person['scale']*.75
    for frame in range(start_frame,end_frame+1):
        seen=[]
        for person in people:
            sample=_at(person['samples'],frame,fps)
            if not sample:continue
            p=sample['landmarks'];w=person['scale'];nose=p[0]
            if not sample.get('face_bbox') and any(math.hypot(nose[0]-q[0],nose[1]-q[1])<max(.025,screen_width(p)*.22) for q in seen):
                quality['duplicate_samples_removed']+=1;continue
            seen.append(nose)
            world=sample.get('world_landmarks',[])
            usable=len(world)==33 and all(math.isfinite(v) for q in world for v in q[:3])
            depth_scale=w/max(.08,distance(world[11][:3],world[12][:3])) if usable else view_width*.5
            hip_depth=(world[23][2]+world[24][2])/2 if usable else (p[23][2]+p[24][2])/2
            joints=[]
            for j,q in enumerate(p):
                source=world[j] if usable else q
                depth=max(-w*1.2,min(w*1.2,(source[2]-hip_depth)*depth_scale))
                joints.append([(q[0]-.5)*view_width,person['depth']+depth,(.5-q[1])*view_height])
            shoulder=[sum(joints[j][i] for j in (11,12))/2 for i in range(3)]
            hip=[sum(joints[j][i] for j in (23,24))/2 for i in range(3)]
            if min(p[23][3],p[24][3])<.5 or not w*.75<distance(shoulder,hip)<w*2:
                hip=[shoulder[0],person['depth'],shoulder[2]-w*1.35]
                lateral=[joints[11][i]-joints[12][i] for i in range(3)]
                length=max(.001,distance(lateral,[0,0,0]))
                for j,sign in [(23,1),(24,-1)]:joints[j]=[hip[i]+sign*w*.32*lateral[i]/length for i in range(3)]
            # Reliable landmarks drive the pose. Missing chains briefly keep the
            # last measured direction, then relax into a labelled standing prior.
            # Never aim a thigh at an old estimated knee after relocating its hip.
            up=[shoulder[i]-hip[i] for i in range(3)];length=max(.001,distance(up,[0,0,0]));up=[v/length for v in up]
            lateral=[joints[11][i]-joints[12][i] for i in range(3)]
            length=max(.001,distance(lateral,[0,0,0]));lateral=[v/length for v in lateral]
            sources={}
            for side,a,b,c,h,k,f,sign in [('L',11,13,15,23,25,27,1),('R',12,14,16,24,26,28,-1)]:
                for label,j1,j2,span in [('upperarm',a,b,.82),('lowerarm',b,c,.78),
                                        ('upperleg',h,k,1.15),('lowerleg',k,f,1.15)]:
                    key=label+'.'+side
                    measured=min(p[j1][3],p[j2][3])>=.65
                    leg_ambiguous=False
                    if j1>=23:
                        outside=not all(-.05<=p[j][1]<=1.05 for j in (h,k,f))
                        projected_thigh=math.hypot((p[k][0]-p[h][0])*view_width,(p[k][1]-p[h][1])*view_height)
                        # Occluded / strongly foreshortened legs do not establish a
                        # reliable knee bend from a single camera. Keep them labelled.
                        leg_ambiguous=outside or min(p[j][3] for j in (h,k,f))<.65 or projected_thigh<w*.55
                        measured=measured and not leg_ambiguous
                    direction=[joints[j2][i]-joints[j1][i] for i in range(3)]
                    measured=measured and distance(direction,[0,0,0])>w*.03
                    if measured:
                        person['limb_history'][key]=(frame,direction);sources[key]='measured'
                        continue
                    history=person['limb_history'].get(key)
                    neutral=[-up[i]*w*span for i in range(3)]
                    if j1<23:
                        for i in range(3):neutral[i]+=sign*lateral[i]*w*(.08 if label=='upperarm' else .01)
                    if history and not leg_ambiguous and frame-history[0]<=fps*.25:
                        t=max(0,min(1,((frame-history[0])/fps-.08)/.17))
                        direction=[history[1][i]*(1-t)+neutral[i]*t for i in range(3)]
                        sources[key]='temporal';quality['temporal_limb_frames']+=1
                    else:
                        direction=neutral
                        sources[key]='standing_prior';quality['standing_limb_frames']+=1
                    joints[j2]=[joints[j1][i]+direction[i] for i in range(3)]
            person['animation'].append({'frame':frame,'joints':{str(j):q for j,q in enumerate(joints)},
                  'joint_sources':sources,
                  'pose_source':sample.get('pose_source','landmarks'),
                 'screen_landmarks':{str(j):q[:2] for j,q in enumerate(p)},
                 'visibility':{str(j):q[3] for j,q in enumerate(p)},'root':hip,'scale':w,
                 'depth_source':'world_landmarks' if usable else 'relative_landmarks',
                 'confidence':sample.get('confidence',person['confidence'])})
            quality['world_pose_samples' if usable else 'fallback_pose_samples']+=1
            quality['baked_pose_frames']+=1
            if sample.get('pose_source') in ('anatomical_prior','mixed_prior'):quality['prior_pose_frames']+=1
    result=[{k:v for k,v in person.items() if k not in ('samples','depth','limb_history')} for person in people if len(person['animation'])>=2]
    return {'actors':result,'quality':quality}
