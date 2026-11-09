from pathlib import Path
import argparse, json
from .pipeline import run, create_project, atomic_json

def main():
    p = argparse.ArgumentParser(description="Offline whiteblock preparation")
    sub = p.add_subparsers(dest="command")
    init = sub.add_parser("init"); init.add_argument("source", type=Path); init.add_argument("--project-id", required=True); init.add_argument("--end-frame", type=int, required=True); init.add_argument("--fps", type=int, default=30); init.add_argument("--project", type=Path, default=Path("project.json"))
    build = sub.add_parser("build"); build.add_argument("project", type=Path); build.add_argument("--out", type=Path, default=Path("exports"))
    sub.add_parser("desktop", help="open the desktop control room")
    a = p.parse_args()
    if a.command == "init":
        value = create_project(a.source, a.project_id, a.end_frame, a.fps); atomic_json(a.project, value); print(json.dumps(value, ensure_ascii=False, indent=2)); return
    if a.command == "build": print(json.dumps(run(a.project, a.out), ensure_ascii=False, indent=2)); return
    if a.command == "desktop":
        from .ui import main as desktop_main
        desktop_main(); return
    p.error("choose init or build")
if __name__ == "__main__": main()
