import ast, json, tempfile, unittest
from pathlib import Path
from whiteblock.pipeline import run, sha256, create_project, find_blender, blender_script, default_workspace, DEFAULT_WORKSPACE, build_scene_spec
from whiteblock import pipeline

class PipelineTests(unittest.TestCase):
    def test_empty_shot_does_not_fabricate_an_actor(self):
        spec = build_scene_spec({'project_id': 'empty', 'media': {'width': 720, 'height': 1280}},
                                {'shot_id': 'shot_001', 'start_frame': 1, 'end_frame': 24, 'actors': []})
        self.assertEqual(spec['actors'], [])

    def test_scene_preserves_portrait_composition(self):
        spec = build_scene_spec({'project_id': 'portrait', 'media': {'width': 720, 'height': 1280}},
                                {'shot_id': 'shot_001', 'start_frame': 1, 'end_frame': 24, 'actors': []})
        self.assertEqual((spec.get('resolution_x'), spec.get('resolution_y')), (720, 1280))

    def test_one_click_has_a_shared_desktop_entry(self):
        self.assertTrue(callable(getattr(pipeline, 'one_click_convert', None)),
                        'Desktop conversion must use a testable analysis-to-render entry.')

    def test_end_to_end_chinese_path_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / "原始视频.mp4"; source.write_bytes(b"offline-fixture")
            project = root / "项目.json"; project.write_text(json.dumps({"schema_version":"1.0","project_id":"p1","blender_version":"5.1.2","source":{"path":str(source),"sha256":sha256(source),"readonly":True},"shots":[{"shot_id":"shot_001","start_frame":1,"end_frame":30,"fps":30}]}, ensure_ascii=False), encoding="utf-8")
            out = root / "exports"; manifest = run(project, out)
            self.assertEqual(manifest["upload_permission"], "offline")
            self.assertTrue((out / "shot_001.blender.py").exists())
            self.assertEqual(len(manifest["outputs"]), 2)
            self.assertEqual(manifest["expected_blender_outputs"][0]["kind"], "blend")
            self.assertEqual(manifest["expected_blender_outputs"][1]["kind"], "whiteblock_video")
            script_text = (out / "shot_001.blender.py").read_text(encoding="utf-8")
            ast.parse(script_text)
            self.assertIn("save_as_mainfile", script_text)
            self.assertIn("render(animation=True)", script_text)

    def test_init_hashes_source_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "素材.mp4"; source.write_bytes(b"x")
            project = create_project(source, "demo", 60)
            self.assertTrue(project["source"]["readonly"])
            self.assertEqual(project["source"]["sha256"], sha256(source))

    def test_missing_source_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); project = root / "p.json"
            project.write_text(json.dumps({"schema_version":"1.0","project_id":"p1","blender_version":"5.1.2","source":{"path":str(root/"missing.mp4"),"readonly":True},"shots":[{"shot_id":"s","start_frame":1,"end_frame":2}]}), encoding="utf-8")
            with self.assertRaisesRegex(FileNotFoundError, "E_INPUT_MISSING"): run(project, root/"out")

    def test_explicit_blender_path_is_resolved_locally(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "blender.exe"; fake.write_bytes(b"local executable placeholder")
            self.assertEqual(find_blender(str(fake)), str(fake.resolve()))

    def test_blender_script_declares_blend_and_video_outputs(self):
        script = blender_script({"collections": [], "material": {"base_color": [1, 1, 1, 1], "roughness": 1}, "actors": [], "props": [], "start_frame": 1, "end_frame": 1, "fps": 24, "output_blend": "x.blend", "output_video": "x.mp4"})
        self.assertIn("save_as_mainfile", script)
        self.assertIn("render(animation=True)", script)
        self.assertIn("output_video", script)

    def test_default_workspace_is_deterministic(self):
        self.assertEqual(default_workspace(), DEFAULT_WORKSPACE.resolve())
        self.assertEqual(default_workspace().name, "output")

if __name__ == "__main__": unittest.main()
