"""Local head anchors keep occluded actors separate; body priors are explicitly labelled."""
from __future__ import annotations
import copy,hashlib,json,math
from pathlib import Path


class FaceLocator:
    def __init__(self,folder):
        import cv2
        folder=Path(folder);manifest=json.loads((folder/'asset-manifest.json').read_text(encoding='utf-8'))
        asset=manifest['assets'][0];model=folder/asset['filename']
        if hashlib.sha256(model.read_bytes()).hexdigest()!=asset['sha256']:raise ValueError('人物定位模型校验失败')
        self.detector=cv2.FaceDetectorYN.create(str(model),'',(320,320),.6,.3,5000)

    def detect(self,image):
        height,width=image.shape[:2];self.detector.setInputSize((width,height))
        _,faces=self.detector.detect(image)
        return sorted([{'bbox':[float(p[0]/width),float(p[1]/height),float(p[2]/width),float(p[3]/height)],
                        'nose':[float(p[8]/width),float(p[9]/height)],'score':float(p[-1])} for p in faces] if faces is not None else [],
                      key=lambda a:a['bbox'][0])


def face_prior(face,frame,width,height):
    """Anatomical standing prior for a measured head, not a measured full-body pose."""
    x,y,w,h=face['bbox'];cx=x+w/2;unit=h*height/width
    nose=face.get('nose',[cx,y+h*.55]);points=[[cx,y+h*.5,0,0] for _ in range(33)]
    points[0]=[nose[0],nose[1],0,face['score']]
    for j,dx,dy in [(11,-.75,1.4),(12,.75,1.4),(13,-.8,2.8),(14,.8,2.8),
                    (15,-.8,4.0),(16,.8,4.0),(23,-.5,3.65),(24,.5,3.65),
                    (25,-.5,5.6),(26,.5,5.6),(27,-.5,7.5),(28,.5,7.5)]:
        points[j]=[cx+dx*unit,y+dy*h,0,0]
    return {'frame':frame,'landmarks':points,'confidence':face['score']*.5,
            'face_bbox':face['bbox'],'face_score':face['score'],'pose_source':'anatomical_prior'}


def _anchor(sample):
    box=sample.get('face_bbox')
    return [box[0]+box[2]/2,box[1]+box[3]/2,box[2],box[3]] if box else [*sample['landmarks'][0][:2],.05,.08]


def track_candidates(records,candidates,frame,fps):
    """Globally assign closest compatible anchors before creating any new tracks."""
    pairs=[]
    for ci,candidate in enumerate(candidates):
        current=_anchor(candidate)
        for ri,record in enumerate(records):
            last=record['poses'][-1];gap=frame-last['frame']
            if gap>fps*.65:continue
            old=_anchor(last);prediction=old[:2]
            if len(record['poses'])>=2:
                prior=record['poses'][-2];dt=last['frame']-prior['frame'];previous=_anchor(prior)
                if dt>0:prediction=[old[a]+max(-.04,min(.04,(old[a]-previous[a])*gap/dt)) for a in (0,1)]
            distance=math.hypot(current[0]-prediction[0],current[1]-prediction[1])
            scale=abs(math.log(max(.001,current[3])/max(.001,old[3])))
            if distance<max(.025,min(.12,old[2]*.8)) and scale<.55:pairs.append((distance+scale*.035,ri,ci))
    matched_records=set();matched_candidates=set()
    for cost,ri,ci in sorted(pairs):
        if ri in matched_records or ci in matched_candidates:continue
        records[ri]['poses'].append(candidates[ci]);matched_records.add(ri);matched_candidates.add(ci)
    for ci,candidate in enumerate(candidates):
        if ci not in matched_candidates:records.append({'poses':[candidate]})
