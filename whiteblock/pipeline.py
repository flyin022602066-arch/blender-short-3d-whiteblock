"""Offline-first whiteblock pipeline. It emits Blender Python and JSON only."""
from __future__ import annotations
import ast, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "output"
STATUS_FLOW = ("created", "ingesting", "ready", "analyzing", "needs_review", "exporting", "exported", "packaged", "awaiting_confirmation", "submitted", "polling", "completed")
WORKSPACE_DIRS = ("input", "projects", "cache", "exports", "models", "logs")
BLENDER_CANDIDATES = (
    Path("C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"),
    Path("C:/Program Files/Blender Foundation/Blender 5.0/blender.exe"),
    Path("C:/Program Files/Blender Foundation/Blender 4.3/blender.exe"),
    Path("D:/Program Files/Blender Foundation/Blender 5.1/blender.exe"),
    Path("D:/Blender/blender.exe"),
)

def find_blender(explicit: str | None = None) -> str | None:
    """Resolve a local Blender executable without downloading or contacting a service."""
    values = [explicit, os.getenv("BLENDER_BIN"), shutil.which("blender.exe"), shutil.which("blender")]
    values.extend(str(path) for path in BLENDER_CANDIDATES)
    for value in values:
        if value and Path(value).is_file(): return str(Path(value).resolve())
    return None

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def ensure_workspace(root: Path) -> Path:
    root = root.resolve()
    for name in WORKSPACE_DIRS: (root / name).mkdir(parents=True, exist_ok=True)
    return root

def default_workspace() -> Path:
    """Return the single deterministic workspace used by automatic conversion."""
    return ensure_workspace(DEFAULT_WORKSPACE)

def log_event(root: Path, event: str, **fields: Any) -> None:
    log_path = ensure_workspace(root) / "logs" / "pipeline.jsonl"
    record = {"timestamp": utc_now(), "event": event, **fields}
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _parse_rate(value: str) -> float | None:
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator) if float(denominator) else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def probe_media(source: Path, ffprobe_bin: str = "ffprobe") -> dict:
    """Read media metadata without decoding or uploading the source."""
    source = Path(source).resolve()
    if not source.is_file(): raise FileNotFoundError("E_INPUT_MISSING: " + str(source))
    executable = media_tool(ffprobe_bin)
    if not executable:
        return {"available": False, "error": "ffprobe_not_found", "path": str(source)}
    command = [executable, "-v", "error", "-show_entries", "format=duration:stream=index,codec_type,width,height,r_frame_rate", "-of", "json", str(source)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        if result.returncode != 0: return {"available": False, "error": result.stderr.strip() or "ffprobe_failed", "path": str(source)}
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc), "path": str(source)}
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    fps = _parse_rate(video.get("r_frame_rate", "")) or 30.0
    duration = float((payload.get("format") or {}).get("duration") or 0)
    return {"available": True, "path": str(source), "duration_seconds": duration, "fps": round(fps, 3),
            "width": video.get("width"), "height": video.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams), "format": source.suffix.lower().lstrip(".")}

def validate_project(project: dict) -> None:
    required = ("schema_version", "project_id", "blender_version", "source", "shots")
    missing = [k for k in required if k not in project]
    if missing: raise ValueError("E_PROJECT_SCHEMA: missing " + ", ".join(missing))
    src = project["source"]
    if not isinstance(src, dict) or not src.get("path") or src.get("readonly") is not True:
        raise ValueError("E_PROJECT_SOURCE: source.path and readonly=true are required")
    if not isinstance(project["shots"], list) or not project["shots"]:
        raise ValueError("E_PROJECT_SHOTS: at least one shot is required")
    shot_ids = set()
    for shot in project["shots"]:
        if not shot.get("shot_id") or shot["shot_id"] in shot_ids: raise ValueError("E_SHOT_ID: shot IDs must be unique")
        shot_ids.add(shot["shot_id"])
        if shot.get("fps", 30) <= 0:
            raise ValueError("E_SHOT_FPS: fps must be positive")
        if shot.get("start_frame", 0) < 1 or shot.get("end_frame", 0) < shot.get("start_frame", 0):
            raise ValueError("E_SHOT_RANGE: invalid frame range")

def build_scene_spec(project: dict, shot: dict) -> dict:
    actors = shot.get("actors") or []
    props = shot.get("props") or []
    media = project.get("media", {})
    width, height = media.get("width") or 1280, media.get("height") or 720
    max_edge = int(project.get('settings', {}).get('preview_max_edge', 1280))
    ratio = min(1, max(640, min(1920, max_edge)) / max(width, height))
    render_width, render_height = max(2, round(width*ratio/2)*2), max(2, round(height*ratio/2)*2)
    return {"project_id": project["project_id"], "shot_id": shot["shot_id"],
            "fps": shot.get("fps", 30), "start_frame": shot["start_frame"], "end_frame": shot["end_frame"],
            "resolution_x": render_width, "resolution_y": render_height,
            "geometry_profile":project.get('settings',{}).get('geometry_profile','human_v3') if shot.get('reconstruction')=='landmark_proxy' or any(a.get('poses') for a in actors) else 'manual',
            "render_engine":project.get('settings',{}).get('render_engine','eevee'),
            "source_path": project.get("source", {}).get("path", ""),
            "source_frame_count": media.get("frame_count", shot["end_frame"]),
            "reconstruction": shot.get("reconstruction", "manual_geometry"),
            "collections": ["REF_VIDEO", "CAMERA_SOLVE", "CHARACTERS", "PROPS", "WHITEBLOCK"],
            "objects": [{"name": "CompositionCamera_APPROXIMATE", "kind": "camera", "location": [0, -30, 0]}],
            "lighting": "workbench_studio",
            "actors": actors, "props": props,
            "material": {"name": "Whiteblock", "base_color": [0.8, 0.8, 0.8, 1], "roughness": 0.8}}

def create_project(source: Path, project_id: str, end_frame: int | None = None, fps: int | None = None, workspace: Path | None = None) -> dict:
    source = source.resolve()
    if not source.is_file(): raise FileNotFoundError("E_INPUT_MISSING: " + str(source))
    media = probe_media(source)
    actual_fps = fps or round(media.get("fps") or 30)
    actual_end = end_frame or max(1, round((media.get("duration_seconds") or 30) * actual_fps))
    if actual_end < 1 or actual_fps < 1: raise ValueError("E_PROJECT_TIMELINE: end_frame and fps must be positive")
    root = ensure_workspace(workspace or source.parent)
    project = {"schema_version": "1.0", "project_id": project_id, "blender_version": "5.1.2", "status": "ready",
               "created_at": utc_now(), "workspace_root": str(root),
               "source": {"path": str(source), "sha256": sha256(source), "readonly": True}, "media": media,
               "settings": {"offline_by_default": True, "eggfans_base_url": "https://api.eggfans.com", "pricing_endpoint": "/pricing"},
               "shots": [{"shot_id": "shot_001", "name": "镜头 001", "start_frame": 1, "end_frame": actual_end, "fps": actual_fps, "revision": 1, "status": "ready", "actors": [], "props": []}],
               "history": [{"timestamp": utc_now(), "status": "ready", "message": "项目已创建，默认离线"}]}
    log_event(root, "project_created", project_id=project_id, source_sha256=project["source"]["sha256"])
    return project

def save_project(path: Path, project: dict) -> None:
    validate_project(project); atomic_json(Path(path), project)

def load_project(path: Path) -> dict:
    project = json.loads(Path(path).read_text(encoding="utf-8")); validate_project(project); return project

def set_status(project: dict, status: str, message: str = "") -> dict:
    if status not in STATUS_FLOW and status not in {"failed", "cancelled"}: raise ValueError("E_STATUS: unknown status " + status)
    project["status"] = status
    project.setdefault("history", []).append({"timestamp": utc_now(), "status": status, "message": message})
    return project

def blender_script(spec: dict) -> str:
    if spec.get('geometry_profile')=='human_v3':
        from .human_pose import fit_humans
        cleaned=fit_humans(spec.get('actors',[]),spec['start_frame'],spec['end_frame'],spec['fps'],
                           10*spec['resolution_x']/spec['resolution_y'],10)
        spec={**spec,'human_actors':cleaned['actors'],'geometry_quality':cleaned['quality'],'runtime_root':str(ROOT)}
        template=Path(__file__).with_name('blender_human.py.template').read_text(encoding='utf-8')
        return template.replace('__SPEC__','spec = '+repr(spec))
    if any(a.get('poses') for a in spec.get('actors', [])) and 'optimized_actors' not in spec:
        from .pose_cleanup import optimize_actors, PROFILE
        cleaned = optimize_actors(spec['actors'], spec['start_frame'], spec['end_frame'], spec['fps'],
                                  10 * spec.get('resolution_x', 640) / spec.get('resolution_y', 360), 10)
        spec = {**spec, 'optimized_actors': cleaned['actors'], 'geometry_quality': cleaned['quality'], 'geometry_profile': PROFILE}
    template = Path(__file__).with_name("blender_scene.py.template").read_text(encoding="utf-8")
    return template.replace("__SPEC__", "spec = " + repr(spec))


def run(project_path: Path, output_dir: Path) -> dict:
    project = json.loads(project_path.read_text(encoding="utf-8")); validate_project(project)
    source = Path(project["source"]["path"])
    if not source.exists(): raise FileNotFoundError("E_INPUT_MISSING: " + str(source))
    digest = sha256(source)
    declared = project["source"].get("sha256")
    if declared and declared != digest: raise ValueError("E_SOURCE_HASH: source SHA-256 mismatch")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for shot in project["shots"]:
        sid = shot["shot_id"]; spec = build_scene_spec(project, shot)
        if spec.get('geometry_profile')=='human_v3':
            from .human_pose import fit_humans
            cleaned=fit_humans(spec.get('actors',[]),spec['start_frame'],spec['end_frame'],spec['fps'],
                               10*spec['resolution_x']/spec['resolution_y'],10)
            spec.update({'human_actors':cleaned['actors'],'geometry_quality':cleaned['quality'],'runtime_root':str(ROOT)})
        elif any(a.get('poses') for a in spec.get('actors', [])):
            from .pose_cleanup import optimize_actors, PROFILE
            cleaned = optimize_actors(spec['actors'], spec['start_frame'], spec['end_frame'], spec['fps'],
                                      10 * spec['resolution_x'] / spec['resolution_y'], 10)
            spec.update({'optimized_actors': cleaned['actors'], 'geometry_quality': cleaned['quality'], 'geometry_profile': PROFILE})
        spec["output_blend"] = str(Path(output_dir).resolve() / (sid + ".blend"))
        if spec.get('geometry_profile')=='human_v3':spec['quality_path']=str(Path(output_dir).resolve()/(sid+'.quality.json'))
        spec["output_video"] = str(Path(output_dir).resolve() / (sid + ".blender.mp4"))
        spec["render_frames"] = str(Path(project.get("workspace_root", output_dir)).resolve() / "cache" / project["project_id"] / "render" / sid / "frame")
        spec_path = output_dir / (sid + ".scene.json"); script_path = output_dir / (sid + ".blender.py")
        atomic_json(spec_path, spec); script_path.write_text(blender_script(spec), encoding="utf-8", newline="\n")
        outputs += [{"path": str(spec_path), "sha256": sha256(spec_path)}, {"path": str(script_path), "sha256": sha256(script_path)}]
    manifest = {"project_id": project["project_id"], "shot_id": "batch", "revision": 1,
                "source_sha256": digest, "blender_version": project["blender_version"],
                "outputs": outputs, "expected_blender_outputs": [
                    {"path": str((output_dir / (shot["shot_id"] + ".blend")).resolve()), "kind": "blend"}
                    for shot in project["shots"]
                ] + [
                    {"path": str((output_dir / (shot["shot_id"] + ".blender.mp4")).resolve()), "kind": "whiteblock_video"}
                    for shot in project["shots"]
                ], "upload_permission": "offline"}
    atomic_json(output_dir / "shot-manifest.json", manifest)
    return manifest

def build_seedance_request(project: dict, shot: dict, output_dir: Path, prompt: str = "保持角色、场景、道具和镜头运动一致") -> dict:
    """Build provider-native content offline; no network or API key is used."""
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    sid = shot["shot_id"]
    video = Path(shot.get("whiteblock_video_path") or output_dir / (sid + ".blender.mp4"))
    from .actor_profiles import template_profile,TEMPLATE_LABELS
    profiles = [{"id": a["id"], **template_profile(a)} for a in shot.get("actors", [])]
    confirmed = [a for a in profiles if a['template_confirmed']]
    if confirmed:
        descriptions = [a['id'] + (" / " + a['role_name'] if a['role_name'] else "") + "：" + TEMPLATE_LABELS[a['body_template']] for a in confirmed]
        prompt += "\n人物模板（用户确认）：" + "；".join(descriptions) + "。"
    content = [{"type": "text", "text": prompt}]
    missing = []
    pending_templates = any(a['template_needs_render'] for a in profiles)
    if pending_templates: missing.append('actor_template_render')
    if video.exists():
        content.append({"type": "video_url", "video_url": {"url": video.resolve().as_uri()}, "role": "reference_video"})
    else:
        content.append({"type": "video_url", "video_url": {"url": "asset://exports/" + video.name}, "role": "reference_video"})
        missing.append("whiteblock_video")
    audio_value = shot.get("reference_audio_path") or shot.get("audio_path")
    if audio_value:
        audio = Path(audio_value)
        if audio.exists(): content.append({"type": "audio_url", "audio_url": {"url": audio.resolve().as_uri()}, "role": "reference_audio"})
        else: missing.append("reference_audio")
    request = {"provider": "eggfans", "base_url": project.get("settings", {}).get("eggfans_base_url", "https://api.eggfans.com"),
               "model": shot.get("model") or project.get("settings", {}).get("eggfans_model") or "seedance-2.5", "content": content,
               "metadata": {"project_id": project["project_id"], "shot_id": sid, "revision": shot.get("revision", 1), "actor_templates": profiles},
               "offline": True, "upload_permission": "awaiting_confirmation", "media_status": "pending_render" if missing else "ready",
               "template_status": "pending_render" if pending_templates else "needs_confirmation" if any(not a['template_confirmed'] for a in profiles) else "confirmed" if profiles else "not_applicable",
               "missing_media": missing, "api_key_included": False, "created_at": utc_now()}
    request_path = output_dir / (sid + ".seedance-request.json")
    atomic_json(request_path, request)
    return {"request": request, "path": str(request_path), "sha256": sha256(request_path)}


def media_tool(name: str) -> str | None:
    executable = shutil.which(name) or shutil.which(name + '.exe')
    if executable: return executable
    explicit = Path(name)
    if explicit.is_file(): return str(explicit.resolve())
    fallback = Path('D:/ffmpeg-7.1-full_build/bin') / (name.removesuffix('.exe') + '.exe')
    return str(fallback) if fallback.is_file() else None


def analyze_video(source: Path, cache: Path, progress=None, frame_range=None) -> dict:
    """Run the installed local models in an isolated process; never use a remote API."""
    source, cache = Path(source).resolve(), Path(cache).resolve()
    if not source.is_file(): raise FileNotFoundError('E_INPUT_MISSING: ' + str(source))
    cache.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / '.venv-pose' / 'Scripts' / 'python.exe'
    executable = str(runtime) if runtime.is_file() else sys.executable
    output = cache / 'analysis.json'
    error_log = cache / 'analysis-worker.log'
    with error_log.open('w', encoding='utf-8') as stderr:
        command=[executable, '-m', 'whiteblock.analysis_worker', str(source), str(output)]
        if frame_range:command.extend(['--start-frame',str(frame_range[0]),'--end-frame',str(frame_range[1])])
        child = subprocess.Popen(command,
                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=stderr, text=True,
                                 encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for line in child.stdout:
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                if progress: progress(event)
            returncode = child.wait()
        finally:
            child.stdout.close()
            if child.poll() is None:
                child.kill(); child.wait()
    if returncode:
        raise RuntimeError('E_LOCAL_ANALYSIS: ' + error_log.read_text(encoding='utf-8', errors='replace')[-2200:])
    result = json.loads(output.read_text(encoding='utf-8'))
    result['source_sha256'] = sha256(source)
    result['source_path'] = str(source)
    atomic_json(output, result)
    return result


def run_blender_script(script_path: Path, blender_bin: str = 'blender', timeout: int = 900, progress=None) -> dict:
    """Render to a clean cache, encode atomically, and verify new output rather than stale files."""
    script_path = Path(script_path).resolve()
    if not script_path.is_file(): raise FileNotFoundError('E_BLENDER_SCRIPT: ' + str(script_path))
    executable = find_blender(blender_bin)
    if not executable: raise FileNotFoundError('E_BLENDER_NOT_FOUND: configure the local Blender executable')
    text = script_path.read_text(encoding='utf-8')
    spec = ast.literal_eval(next(line[len('spec = '):] for line in text.splitlines() if line.startswith('spec = ')))
    video_path = Path(spec['output_video']) if spec.get('output_video') else None
    ffmpeg = media_tool('ffmpeg')
    if video_path and not ffmpeg: raise FileNotFoundError('E_FFMPEG_NOT_FOUND: video export requires ffmpeg')
    prefix = Path(spec.get('render_frames', str(video_path) + '.frame'))
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for old in prefix.parent.glob(prefix.name + '*.png'):
        old.unlink()
    log_path = prefix.parent / 'blender.log'
    start, last_count, last_audit = time.monotonic(), -1, -1
    with log_path.open('w', encoding='utf-8') as log:
        child = subprocess.Popen([executable, '--background', '--factory-startup', '--python-exit-code', '1',
                                  '--python', str(script_path)], stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while child.poll() is None:
                if progress and log_path.is_file():
                    with log_path.open('rb') as tail:
                        tail.seek(max(0,log_path.stat().st_size-8192))
                        audits=re.findall(r'WHITEBLOCK MESH AUDIT (\d+)',tail.read().decode('utf-8',errors='replace'))
                    if audits and int(audits[-1])!=last_audit:
                        last_audit=int(audits[-1]);progress({'stage':'geometry_check','shot':spec['shot_id'],
                            'frames':last_audit-spec['start_frame']+1,'total':spec['end_frame']-spec['start_frame']+1})
                count = len(list(prefix.parent.glob(prefix.name + '*.png')))
                if count != last_count:
                    if progress: progress({'stage': 'rendering', 'shot': spec['shot_id'], 'frames': count,
                                           'total': spec['end_frame']-spec['start_frame']+1})
                    last_count = count
                if time.monotonic()-start > timeout:
                    raise TimeoutError('E_BLENDER_TIMEOUT: ' + str(log_path))
                time.sleep(0.5)
        finally:
            if child.poll() is None:
                child.kill(); child.wait()
    log_text = log_path.read_text(encoding='utf-8', errors='replace')
    if child.returncode or 'Traceback (most recent call last)' in log_text:
        raise RuntimeError('E_BLENDER_RUN: ' + log_text[-2500:])
    outputs = []
    blend_path = Path(spec['output_blend']) if spec.get('output_blend') else None
    if blend_path:
        if not blend_path.is_file(): raise RuntimeError('E_BLENDER_OUTPUT_MISSING: ' + str(blend_path))
        outputs.append(str(blend_path))
    if video_path:
        frames = sorted(prefix.parent.glob(prefix.name + '*.png'))
        expected = spec['end_frame']-spec['start_frame']+1
        if len(frames) != expected:
            raise RuntimeError(f'E_RENDER_FRAME_COUNT: expected {expected}, got {len(frames)}; {log_path}')
        if progress: progress({'stage': 'encoding', 'shot': spec['shot_id']})
        partial = video_path.with_name(video_path.stem + '.part.mp4')
        encode = subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-framerate', str(spec['fps']),
                                 '-start_number', str(spec['start_frame']), '-i', str(prefix)+'%04d.png',
                                 '-frames:v', str(expected), '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p',
                                 str(partial)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if encode.returncode: raise RuntimeError('E_VIDEO_ENCODE: ' + encode.stderr[-2000:])
        info = probe_media(partial)
        if not info.get('available') or abs(info['duration_seconds']-expected/spec['fps']) > 1/spec['fps']+0.01:
            raise RuntimeError('E_VIDEO_VERIFY: ' + str(partial))
        os.replace(partial, video_path)
        outputs.append(str(video_path))
        for frame in frames: frame.unlink()
    return {'returncode': child.returncode, 'stdout_tail': log_text[-2000:], 'script': str(script_path),
            'outputs': outputs, 'log': str(log_path)}


def one_click_convert(source: Path, workspace: Path | None = None, blender_bin: str | None = None,
                      settings: dict | None = None, progress=None) -> dict:
    """The desktop and real-video tests share this complete local analysis/render path."""
    source = Path(source).resolve()
    if not source.is_file(): raise FileNotFoundError('E_INPUT_MISSING: ' + str(source))
    executable = find_blender(blender_bin)
    if not executable: raise FileNotFoundError('E_BLENDER_NOT_FOUND: choose the local blender.exe in settings')
    if not media_tool('ffmpeg') or not media_tool('ffprobe'):
        raise FileNotFoundError('E_MEDIA_TOOLS: ffmpeg and ffprobe are required')
    root = ensure_workspace(workspace or DEFAULT_WORKSPACE)
    digest = sha256(source)
    copied = root / 'input' / source.name
    if copied.is_file() and sha256(copied) != digest:
        copied = copied.with_name(copied.stem + '_' + digest[:8] + copied.suffix)
    if source != copied.resolve() and not copied.exists(): shutil.copy2(source, copied)
    stem = re.sub(r'[^A-Za-z0-9_-]+', '_', source.stem).strip('_') or 'project'
    project_id = stem[:50] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    project = create_project(copied, project_id, workspace=root)
    project.setdefault('settings', {}).update(settings or {})
    project['settings']['blender_path'] = executable
    project_path, out, cache = root/'projects'/(project_id+'.json'), root/'exports'/project_id, root/'cache'/project_id

    def report(event):
        event = {'project_id': project_id, **event}
        if progress: progress(event)
        if event['stage'] != 'rendering': log_event(root, 'one_click_progress', **event)

    try:
        set_status(project, 'analyzing', '本地镜头切分和多人姿态分析')
        save_project(project_path, project)
        report({'stage': 'analyzing', 'frame': 0, 'total': project['shots'][0]['end_frame']})
        analysis = analyze_video(copied, cache, report)
        if not analysis['pose_samples']:
            raise ValueError('E_NO_SUBJECTS: 没有检测到可用人物姿态，已保留分析结果；不会用默认方块冒充反推结果。')
        project['shots'] = analysis['shots']
        project['media'].update({k: analysis[k] for k in ['fps', 'width', 'height', 'frame_count']})
        project['analysis'] = {k: v for k,v in analysis.items() if k != 'shots'}
        project['analysis']['path'] = str(cache/'analysis.json')
        project['analysis']['shots_without_pose'] = [s['shot_id'] for s in project['shots'] if not s['actors']]
        set_status(project, 'exporting', '按原片镜头与姿态生成可编辑人物代理')
        save_project(project_path, project)
        manifest = run(project_path, out)
        for shot in project['shots']:
            report({'stage': 'rendering', 'shot': shot['shot_id'], 'frames': 0,
                    'total': shot['end_frame']-shot['start_frame']+1})
            result = run_blender_script(out/(shot['shot_id']+'.blender.py'), executable, progress=report)
            shot['whiteblock_blend_path'] = str(out/(shot['shot_id']+'.blend'))
            shot['whiteblock_video_path'] = str(out/(shot['shot_id']+'.blender.mp4'))
            shot['status'] = 'needs_review'
            manifest['outputs'].extend({'path': p, 'sha256': sha256(Path(p))} for p in result['outputs'])
            save_project(project_path, project)
        report({'stage': 'assembling'})
        listing = cache/'concat.txt'
        listing.write_text(''.join("file '" + Path(s['whiteblock_video_path']).as_posix().replace("'", "'\\''") + "'\n" for s in project['shots']), encoding='utf-8')
        video, partial = out/'whiteblock_preview.mp4', out/'whiteblock_preview.part.mp4'
        result = subprocess.run([media_tool('ffmpeg'), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                                 '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', str(partial)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode: raise RuntimeError('E_VIDEO_ASSEMBLY: ' + result.stderr[-2000:])
        info = probe_media(partial)
        duration = analysis['frame_count']/analysis['fps']
        if not info.get('available') or abs(info['duration_seconds']-duration) > 0.15:
            raise RuntimeError('E_VIDEO_DURATION: assembled output does not match the source timeline')
        os.replace(partial, video)
        info['path'] = str(video)
        manifest['outputs'].append({'path': str(video), 'sha256': sha256(video), 'kind': 'combined_whiteblock_preview'})
        PROFILE=project.get('settings',{}).get('geometry_profile','human_v3')
        qualities = [json.loads((out/(s['shot_id']+'.scene.json')).read_text(encoding='utf-8')).get('geometry_quality', {}) for s in project['shots']]
        counts = ['duplicate_samples_removed','baked_pose_frames','world_pose_samples','fallback_pose_samples','arm_clearance_adjustments'] if PROFILE=='human_v3' else ['duplicate_samples_removed','arm_torso_intersections_before','arm_torso_intersections_after','baked_pose_frames']
        quality = {key:sum(q.get(key,0) for q in qualities) for key in counts}
        quality['collision_scope'] = '关节／躯干代理约束；可在 Blender MCP 复核已变形网格表面'
        if PROFILE=='human_v3':
            mesh_reports=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(out.glob('shot_*.quality.json'))]
            quality['mesh_audit']={key:sum(q.get(key,0) for q in mesh_reports) for key in ('audited_frames','frames_with_initial_issues','remaining_frames','arm_repairs','depth_repairs')}
            quality['mesh_audit']['scope']='每帧人体间表面交叉、前臂与躯干；不含全部自碰撞、衣物、道具和纯体积包含'
            manifest['outputs'].extend({'path':str(p),'sha256':sha256(p),'kind':'mesh_quality'} for p in sorted(out.glob('shot_*.quality.json')))
        project.update({'geometry_profile': PROFILE, 'geometry_quality': quality})
        manifest.update({'reconstruction': 'landmark_proxy', 'analysis_path': str(cache/'analysis.json'),
                         'geometry_profile': PROFILE, 'geometry_quality': quality,
                          'limitations': analysis['limitations'], 'render_verified': True})
        atomic_json(out/'shot-manifest.json', manifest)
        project['last_manifest'], project['whiteblock_preview_path'] = manifest, str(video)
        set_status(project, 'needs_review', '白模预览已生成；相机、深度、遮挡和场景仍需人工复核')
        save_project(project_path, project)
        try:
            from .library import refresh_library
            report({'stage': 'cataloging'})
            refresh_library(root)
        except Exception as catalog_error:
            log_event(root, 'library_refresh_failed', project_id=project_id, error=str(catalog_error))
        report({'stage': 'completed', 'video': str(video), 'directory': str(out)})
        return {'project': project, 'project_path': project_path, 'manifest': manifest,
                'directory': str(out), 'video': str(video), 'media': info, 'blender': executable}
    except Exception as exc:
        set_status(project, 'failed', str(exc)); save_project(project_path, project)
        log_event(root, 'one_click_failed', project_id=project_id, error=str(exc))
        raise
