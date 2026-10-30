"""Image rectification for replay; all poses/observations come from the recorded run."""
import sys
from pathlib import Path
import cv2
import numpy as np


class RectifyReplay:
    def __init__(self,replay):
        self.replay=replay;self.maps=None

    def __call__(self,image):
        prep=self.replay.get('preparation')
        if prep:
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
            from dense.video import working_image
            return working_image(image,prep['camera'],prep['rotation_degrees'])[0]
        if image.shape[:2]!=(720,960):raise ValueError('Replay source dimensions differ from recorded calibration')
        if self.maps is None:
            k=np.array(self.replay['k']);dist=np.array(self.replay['distortion'])
            self.maps=cv2.initUndistortRectifyMap(k,dist,None,k,(960,720),cv2.CV_32FC1)
        return cv2.remap(image,*self.maps,cv2.INTER_LINEAR)


def splat_diameter(voxel_edge,total,displayed,multiplier=1.5):
    """World-space diameter follows actual voxel spacing and the display subsample."""
    return float(voxel_edge)*float(multiplier)*np.sqrt(max(1.,total/max(1,displayed)))
