import copy
import unittest

from whiteblock.crowd_tracking import face_prior
from whiteblock.human_pose import fit_humans
from tests.test_human_upgrade import actor_fixture


class MotionFittingTests(unittest.TestCase):
    def test_unobserved_standing_prior_does_not_bend_thighs_after_hip_reposition(self):
        sample = face_prior({'bbox': [.4, .1, .1, .1], 'score': .95}, 119, 720, 1280)
        second = copy.deepcopy(sample); second['frame'] = 120
        result = fit_humans([{'id': 'A', 'poses': [sample, second]}], 119, 120, 24, 5.625, 10)
        for pose in result['actors'][0]['animation']:
            joints = pose['joints']
            for hip, knee, ankle in ((23, 25, 27), (24, 26, 28)):
                self.assertAlmostEqual(joints[str(hip)][0], joints[str(knee)][0], places=5)
                self.assertAlmostEqual(joints[str(knee)][0], joints[str(ankle)][0], places=5)
                self.assertAlmostEqual(joints[str(hip)][1], joints[str(knee)][1], places=5)

    def test_hip_fallback_preserves_left_right_order_of_visible_shoulders(self):
        actor = actor_fixture()
        for pose in actor['poses']:
            pose['landmarks'][11][0], pose['landmarks'][12][0] = .6, .4
            pose['landmarks'][23][3] = pose['landmarks'][24][3] = 0
        result = fit_humans([actor], 13, 14, 24, 5.625, 10)
        for pose in result['actors'][0]['animation']:
            self.assertGreater(pose['joints']['23'][0], pose['joints']['24'][0])

    def test_measured_forearm_depth_is_preserved_until_actual_mesh_collision(self):
        actor = actor_fixture()
        for pose in actor['poses']:
            pose['landmarks'][13][:2] = [.49, .4]
            pose['landmarks'][15][:2] = [.51, .42]
            pose['world_landmarks'][13][2] = pose['world_landmarks'][15][2] = 0
        result = fit_humans([actor], 13, 14, 24, 5.625, 10)
        pose = result['actors'][0]['animation'][0]
        self.assertEqual(pose['joints']['13'][1], pose['root'][1])
        self.assertEqual(pose['joints']['15'][1], pose['root'][1])

    def test_offscreen_leg_does_not_retain_a_previous_knee_gesture(self):
        actor = actor_fixture()
        actor['poses'][1] = copy.deepcopy(actor['poses'][1])
        actor['poses'][1]['landmarks'][27][1] = 1.2
        result = fit_humans([actor], 13, 14, 24, 5.625, 10)
        last = result['actors'][0]['animation'][-1]
        self.assertEqual(last['joint_sources']['upperleg.L'], 'standing_prior')
        self.assertEqual(last['joint_sources']['lowerleg.L'], 'standing_prior')

    def test_short_projected_thigh_is_flagged_instead_of_lifting_occluded_leg(self):
        actor = actor_fixture()
        for pose in actor['poses']:
            pose['landmarks'][25][:2] = [.38, .55]
        result = fit_humans([actor], 13, 14, 24, 5.625, 10)
        for pose in result['actors'][0]['animation']:
            self.assertEqual(pose['joint_sources']['upperleg.L'], 'standing_prior')
            self.assertLess(pose['joints']['25'][2], pose['joints']['23'][2])


if __name__ == '__main__':
    unittest.main()
