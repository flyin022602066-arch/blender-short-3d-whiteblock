import importlib.util
import unittest


def actor(name='A', confidence=0.9):
    points = [[0.5,0.5,0,confidence] for _ in range(33)]
    points[0]=[0.5,0.15,0,confidence]
    points[11],points[12]=[0.35,0.3,0,confidence],[0.65,0.3,0,confidence]
    points[23],points[24]=[0.4,0.65,0,confidence],[0.6,0.65,0,confidence]
    points[13],points[15]=[0.43,0.45,0,confidence],[0.55,0.5,0,confidence]
    points[14],points[16]=[0.57,0.45,0,confidence],[0.45,0.5,0,confidence]
    changed=[p[:] for p in points];changed[0][0]=0.55
    return {'id':name,'confidence':confidence,'poses':[{'frame':1,'landmarks':points,'confidence':confidence},
        {'frame':5,'landmarks':changed,'confidence':confidence}]}


class PoseCleanupTests(unittest.TestCase):
    def run_cleanup(self, actors):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.pose_cleanup'), 'Raw landmarks require geometry constraints.')
        from whiteblock.pose_cleanup import optimize_actors
        return optimize_actors(actors,1,5,24,5.625,10)

    def test_duplicate_person_is_removed_and_motion_is_baked_every_frame(self):
        result=self.run_cleanup([actor('A'),actor('duplicate',0.6)])
        self.assertEqual(len(result['actors']),1)
        self.assertEqual([s['frame'] for s in result['actors'][0]['animation']], [1,2,3,4,5])
        self.assertGreater(result['quality']['duplicate_samples_removed'],0)

    def test_folded_arms_do_not_pass_through_torso(self):
        result=self.run_cleanup([actor()])
        self.assertGreater(result['quality']['arm_torso_intersections_before'],0)
        self.assertEqual(result['quality']['arm_torso_intersections_after'],0)
        for sample in result['actors'][0]['animation']:
            self.assertLess(sample['joints']['15'][1], sample['body_center'][1]-sample['body_depth'])

    def test_overlapping_people_are_separated_in_depth(self):
        first,second=actor('A'),actor('B')
        for p in second['poses']:
            for joint in p['landmarks']: joint[0]+=0.15
        result=self.run_cleanup([first,second])
        self.assertEqual(len(result['actors']),2)
        a,b=result['actors']
        self.assertLess(a['depth_bounds'][1],b['depth_bounds'][0])

