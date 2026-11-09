"""Local CPU analysis. Models must already exist; this worker never downloads them."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def analyze(source: Path, sample_fps: float = 12, start_frame: int = 1, end_frame: int | None = None) -> dict:
    import cv2
    import numpy as np
    import mediapipe as mp
    from .crowd_tracking import FaceLocator,face_prior,track_candidates
    locator_path=Path(__file__).resolve().parents[1]/'output/models/yunet'
    locator=FaceLocator(locator_path) if (locator_path/'asset-manifest.json').is_file() else None

    model_root = Path(mp.__file__).parent / 'modules'
    for model in ['pose_landmark/pose_landmark_full.tflite', 'pose_detection/pose_detection.tflite',
                  'face_detection/face_detection_full_range_sparse.tflite']:
        if not (model_root / model).is_file():
            raise FileNotFoundError('E_POSE_MODEL_MISSING: ' + str(model_root / model))
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError('E_VIDEO_DECODE: ' + str(source))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not math.isfinite(fps) or fps <= 0 or not width or not height:
        cap.release()
        raise ValueError('E_VIDEO_METADATA: invalid dimensions or frame rate')
    expected_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    end_frame=end_frame or expected_frames
    if not 1<=start_frame<=end_frame<=expected_frames:
        cap.release();raise ValueError('E_ANALYSIS_RANGE: invalid source frame range')
    cap.set(cv2.CAP_PROP_POS_FRAMES,start_frame-1)
    stride = max(1, round(fps / sample_fps))
    shots, records, sampled, frame_number = [], [], 0, start_frame-1
    start, previous_gray, previous_hist = start_frame, None, None

    def finish(end):
        actors = []
        for record in records:
            poses = record['poses']
            # A track must be observed repeatedly; a one-frame false positive earns no geometry.
            if len(poses) < 2:
                continue
            actors.append({'id': f'Actor_{len(actors)+1:02d}', 'poses': poses,
                            'body_template':'neutral','template_confirmed':False,'template_source':'unset',
                            'tracking_source':'yunet_head_anchor' if locator else 'mediapipe_nose',
                            'prior_pose_samples':sum(p.get('pose_source')=='anatomical_prior' for p in poses),
                           'confidence': round(sum(p['confidence'] for p in poses) / len(poses), 4)})
        shots.append({'shot_id': f'shot_{len(shots)+1:03d}', 'name': f'镜头 {len(shots)+1:03d}',
                      'start_frame': start, 'end_frame': end, 'fps': fps, 'revision': 1,
                      'status': 'needs_review', 'actors': actors, 'props': [],
                      'reconstruction': 'landmark_proxy', 'camera_mode': 'orthographic_composition',
                      'warnings': ['相机与深度为构图近似，遮挡、背景和道具需要人工复核。']})

    try:
        with mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1,
                                    min_detection_confidence=0.4) as pose, \
             mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.45) as faces:
            while frame_number<end_frame:
                ok, image = cap.read()
                if not ok:
                    break
                frame_number += 1
                small = cv2.resize(image, (64, 64))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
                hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256]*3)
                cv2.normalize(hist, hist)
                cut = False
                if previous_gray is not None and frame_number-start >= max(2, round(fps*0.35)):
                    difference = float(np.mean(np.abs(gray-previous_gray)))
                    distance = cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                    cut = (difference > 0.12 and distance > 0.58) or difference > 0.18
                previous_gray, previous_hist = gray, hist
                if cut:
                    finish(frame_number-1)
                    start, records = frame_number, []
                if not cut and (frame_number-start_frame) % stride:
                    continue
                sampled += 1
                # One whole-frame estimate plus face-centred crops recover several people locally.
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                boxes = []
                anchors=locator.detect(image) if locator else []
                if locator:boxes=[tuple(face['bbox']) for face in anchors]
                else:
                    face_result = faces.process(rgb)
                    for detection in face_result.detections or []:
                        b = detection.location_data.relative_bounding_box
                        boxes.append((b.xmin, b.ymin, b.width, b.height))
                boxes.sort(key=lambda b: b[2]*b[3], reverse=True)
                crops = [] if locator and boxes else [(0, 0, width, height, None)]
                for x, y, w, h in boxes[:8]:
                    x1, x2 = max(0, int((x-1.3*w)*width)), min(width, int((x+2.3*w)*width))
                    y1, y2 = max(0, int((y-0.6*h)*height)), min(height, int((y+9*h)*height))
                    if x2-x1 >= 24 and y2-y1 >= 48:
                        crops.append((x1, y1, x2, y2, (x+w/2, y+h/2, w, h)))
                candidates = []
                for x1, y1, x2, y2, anchor in crops:
                    result = pose.process(rgb[y1:y2, x1:x2])
                    if not result.pose_landmarks:
                        continue
                    points = [[round((p.x*(x2-x1)+x1)/width, 5),
                               round((p.y*(y2-y1)+y1)/height, 5),
                               round(p.z*(x2-x1)/width, 5), round(p.visibility, 4)]
                              for p in result.pose_landmarks.landmark]
                    nose = points[0]
                    if nose[3] < 0.5 or not (0 <= nose[0] <= 1 and 0 <= nose[1] <= 1):
                        continue
                    if anchor and (abs(nose[0]-anchor[0]) > anchor[2]*0.9 or abs(nose[1]-anchor[1]) > anchor[3]):
                        continue
                    confidence = sum(p[3] for p in points[11:17]) / 6
                    if confidence < 0.45:
                        continue
                    duplicate = next((c for c in candidates if math.hypot(nose[0]-c['landmarks'][0][0],
                                                                          nose[1]-c['landmarks'][0][1]) < 0.035), None)
                    candidate = {'frame': frame_number, 'landmarks': points, 'confidence': round(confidence, 4)}
                    candidate['pose_source']='landmarks'
                    if anchor:candidate['face_bbox']=[anchor[0]-anchor[2]/2,anchor[1]-anchor[3]/2,anchor[2],anchor[3]]
                    if result.pose_world_landmarks:
                        candidate['world_landmarks']=[[round(p.x,5),round(p.y,5),round(p.z,5),round(p.visibility,4)]
                                                     for p in result.pose_world_landmarks.landmark]
                    if duplicate:
                        if confidence > duplicate['confidence']:
                            candidates.remove(duplicate)
                            candidates.append(candidate)
                    else:
                        candidates.append(candidate)
                if locator and anchors:
                    anchored=[]
                    for face in anchors:
                        x,y,w,h=face['bbox'];cx,cy=x+w/2,y+h/2
                        choices=[c for c in candidates if c.get('face_bbox') and
                                 abs(c['face_bbox'][0]-x)<.001 and abs(c['face_bbox'][1]-y)<.001]
                        anchored.append(max(choices,key=lambda c:c['confidence']) if choices else face_prior(face,frame_number,width,height))
                    candidates=anchored
                track_candidates(records,candidates,frame_number,fps)
                if sampled % 8 == 0 or cut:
                    emit(stage='analyzing', frame=frame_number, total=expected_frames,
                         shots=len(shots)+1, people=len(candidates))
        if frame_number<start_frame:
            raise ValueError('E_VIDEO_DECODE: no decodable frames')
        finish(frame_number)
    finally:
        cap.release()
    pose_samples = sum(len(a['poses']) for s in shots for a in s['actors'])
    covered = len({p['frame'] for s in shots for a in s['actors'] for p in a['poses']})
    return {'algorithm': 'yunet-head-anchored-mediapipe-human-v4' if locator else 'mediapipe-0.10-world-image-human-v3', 'fps': fps,
            'width': width, 'height': height, 'frame_count': frame_number-start_frame+1, 'source_frame_count':expected_frames,
            'start_frame':start_frame,'end_frame':frame_number,'shots': shots,
            'sampled_frames': sampled, 'pose_samples': pose_samples,
            'pose_frame_coverage': round(covered/max(1, sampled), 4),
            'prior_pose_samples':sum(a.get('prior_pose_samples',0) for s in shots for a in s['actors']),
            'limitations': ['单目深度和正交相机为近似，并非真实摄像机求解。',
                            '动作关键点漏检时，以已检测头部定位完整人体，姿态为解剖先验并标注待复核。',
                            '多人遮挡、近景、漏检人物、背景和道具需要在 Blender 内人工复核。']}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--start-frame',type=int,default=1)
    parser.add_argument('--end-frame',type=int)
    args = parser.parse_args()
    result = analyze(args.source,start_frame=args.start_frame,end_frame=args.end_frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    emit(stage='analysis_done', pose_samples=result['pose_samples'], shots=len(result['shots']))


if __name__ == '__main__':
    main()
