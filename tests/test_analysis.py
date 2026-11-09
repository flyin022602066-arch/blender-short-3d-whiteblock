import tempfile
import unittest
from pathlib import Path
from whiteblock import pipeline


class AnalysisTests(unittest.TestCase):
    def test_cut_with_same_color_histogram_still_splits(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root/'same-colors.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 12, (64,96))
            frame = np.full((96,64,3), 64, dtype=np.uint8)
            frame[:,32:] = 128
            for image in [frame]*12 + [frame[:,::-1]]*12: writer.write(image)
            writer.release()
            result = pipeline.analyze_video(source, root/'cache')
            self.assertEqual([(s['start_frame'],s['end_frame']) for s in result['shots']], [(1,12),(13,24)])

    def test_local_cut_detection_has_no_invented_people(self):
        analyze = getattr(pipeline, 'analyze_video', None)
        self.assertTrue(callable(analyze), 'The one-click path must actually decode the input video.')
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / '中文输入.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 12, (64, 96))
            self.assertTrue(writer.isOpened())
            for color in [0] * 12 + [255] * 12:
                writer.write(np.full((96, 64, 3), color, dtype=np.uint8))
            writer.release()
            result = analyze(source, root / 'cache')
            self.assertEqual([(s['start_frame'], s['end_frame']) for s in result['shots']], [(1, 12), (13, 24)])
            self.assertEqual(result['pose_samples'], 0)
            self.assertEqual(result['source_sha256'], pipeline.sha256(source))


if __name__ == '__main__':
    unittest.main()
