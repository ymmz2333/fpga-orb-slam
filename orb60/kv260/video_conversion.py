"""Explicit persistent BGR conversion; preserves decoded pixels and timestamps."""


class BgrConverter:
    def __init__(self,reuse=False):
        self.reformatter=None
        if reuse:
            from av.video.reformatter import VideoReformatter
            self.reformatter=VideoReformatter()

    def convert(self,frame):
        if self.reformatter is None:return frame.to_ndarray(format='bgr24')
        return self.reformatter.reformat(frame,format='bgr24').to_ndarray()
