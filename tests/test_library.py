import importlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class LibraryTests(unittest.TestCase):
    def test_template_warnings_use_only_characters_in_this_preview(self):
        from whiteblock.library import refresh_library
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'exports/batch';out.mkdir(parents=True)
            for name in ('shot_001.blender.mp4','shot_002.blender.mp4','whiteblock_preview.mp4'):(out/name).write_bytes(b'fixture')
            projects=root/'projects';projects.mkdir()
            (projects/'batch.json').write_text(json.dumps({'project_id':'batch','geometry_profile':'human_v3',
                'shots':[{'shot_id':'shot_001','actors':[{'id':'Actor_01','body_template':'male','template_confirmed':True}]},
                         {'shot_id':'shot_002','actors':[{'id':'Actor_01','body_template':'female','template_needs_render':True},
                                                        {'id':'Actor_02'}]}]}),encoding='utf-8')
            with patch('whiteblock.library.probe_media',return_value={'available':True,'width':64,'height':96,'duration_seconds':1}), \
                 patch('whiteblock.library.media_tool',return_value=None):entries=refresh_library(root)
            by_name={Path(e['video']).name:e for e in entries}
            self.assertEqual(by_name['shot_001.blender.mp4']['warnings'],[])
            for name in ('shot_002.blender.mp4','whiteblock_preview.mp4'):
                warnings=by_name[name]['warnings']
                self.assertTrue(any('此视频仍为旧模板' in text for text in warnings))
                self.assertTrue(any('1 个人物模板待确认' in text for text in warnings))
            self.assertEqual(len(by_name['shot_001.blender.mp4']['actor_templates']),1)

    def test_damaged_index_does_not_prevent_startup(self):
        from whiteblock.library import load_library
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);index=root/'library/index.json';index.parent.mkdir()
            for data in ([], {'entries':[None, {}, {'video':None}]}):
                index.write_text(json.dumps(data),encoding='utf-8')
                self.assertEqual(load_library(root),[])

    def test_thumbnail_failure_keeps_the_generated_video_in_library(self):
        from whiteblock.library import refresh_library
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'exports/batch';out.mkdir(parents=True)
            (out/'whiteblock_preview.mp4').write_bytes(b'fixture')
            with patch('whiteblock.library.probe_media',return_value={'available':True,'width':64,'height':96,'duration_seconds':1}), \
                 patch('whiteblock.library.media_tool',return_value='ffmpeg'), \
                 patch('whiteblock.library.subprocess.run',side_effect=FileNotFoundError('ffmpeg removed')):
                entries=refresh_library(root)
            self.assertEqual(len(entries),1)
            self.assertIsNone(entries[0]['thumbnail'])

    def test_library_recovers_history_and_ignores_partial_or_broken_videos(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.library'), 'Historical videos need a persistent library.')
        from whiteblock.library import refresh_library
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); out = root/'exports/批次一'; out.mkdir(parents=True)
            projects = root/'projects'; projects.mkdir()
            video = out/'whiteblock_preview.mp4'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 12, (64,96))
            for _ in range(12): writer.write(np.full((96,64,3),100,dtype=np.uint8))
            writer.release()
            (out/'whiteblock_preview.part.mp4').write_bytes(b'incomplete')
            (out/'shot_999.blender.mp4').write_bytes(b'invalid')
            (projects/'批次一.json').write_text(json.dumps({'project_id':'批次一','source':{'path':'C:/输入/原片.mp4'},
                'shots':[], 'whiteblock_preview_path':str(video)}, ensure_ascii=False),encoding='utf-8')
            entries = refresh_library(root)
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['source_name'],'原片.mp4')
            self.assertEqual(entries[0]['duration_seconds'],1)
            self.assertTrue(Path(entries[0]['thumbnail']).is_file())
            self.assertTrue((root/'library/index.json').is_file())
            self.assertEqual(refresh_library(root)[0]['id'],entries[0]['id'])
            video.unlink()
            self.assertEqual(refresh_library(root),[])
