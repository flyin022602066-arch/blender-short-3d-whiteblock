import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from whiteblock.pipeline import ROOT, find_blender


@unittest.skipUnless(find_blender(), 'Local Blender required')
class BlenderMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(dir=ROOT / 'output/cache') as folder:
            output = Path(folder) / 'motion.json'
            result = subprocess.run([find_blender(), '-b', '--python-exit-code', '1',
                '--python', str(ROOT / 'tests/blender_motion_fixture.py'), '--', str(output)],
                capture_output=True, timeout=90)
            if result.returncode:
                raise RuntimeError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
            cls.report = json.loads(output.read_text())

    def test_aim_preserves_landmark_direction_with_rotated_parents(self):
        self.assertLess(max(self.report['direct'].values()), .1, self.report)

    def test_baked_animation_keeps_each_frames_elbow_and_wrist_direction(self):
        for frame in self.report['frames']:
            self.assertLess(max(frame['errors'].values()), .1, frame)

    def test_coarse_torso_proxy_does_not_silently_overwrite_measured_pose(self):
        self.assertEqual(self.report['proxy_fixes'], 0, self.report)
        self.assertLess(self.report['proxy_displacement'], .0001)

    def test_saved_motion_audit_reports_measured_direction_errors(self):
        audit = self.report['motion_quality']
        self.assertIsInstance(audit, dict)
        self.assertEqual(audit['sources']['measured']['count'], 24)
        self.assertLess(audit['sources']['measured']['max_degrees'], .1)
        self.assertIn('upperarm01.L', audit['bones'])


if __name__ == '__main__':
    unittest.main()
