import json
import re
import tempfile
import unittest
from pathlib import Path

from orb60.demo_bridge.patch_tracking_diagnostics import patch_tracking, patch_matcher, change_function
from orb60.demo_bridge.summarize_tracking_diagnostics import summarize

ROOT=Path(__file__).resolve().parents[3]

class Diagnostics(unittest.TestCase):
    def test_deployed_return_decisions_and_match_updates_are_preserved(self):
        snapshots=ROOT/'orb60/build/demo_bridge/rotation_review'
        source=snapshots/'Tracking.deployed.cc'
        if not source.is_file():self.skipTest('Read-only deployed source snapshots not present')
        before=source.read_text();after=patch_tracking(before)
        self.assertEqual(patch_tracking(after),after)
        for name in ('TrackReferenceKeyFrame','TrackWithMotionModel','TrackLocalMap'):
            bodies=[]
            for text in (before,after):
                change_function(text,'bool Tracking::'+name+'()',lambda body:bodies.append(body) or body)
            unwrapped=re.sub(r'return BridgeDiag::decision\("[^"]+",\((.*?)\),bridge_matches,bridge_inliers\);',r'return \1;',bodies[1])
            self.assertEqual(re.findall(r'\breturn\s+([^;]+);',bodies[0]),re.findall(r'\breturn\s+([^;]+);',unwrapped))
        matcher=(snapshots/'ORBmatcher.deployed.cc').read_text();patched=patch_matcher(matcher)
        self.assertEqual(patch_matcher(patched),patched)
        for token in ('nmatches++','nmatches--','TH_LOW','TH_HIGH','mfNNratio','ComputeThreeMaxima('):
            self.assertEqual(matcher.count(token),patched.count(token),token)

    def test_summary_reports_loss_and_new_map_without_fabricating_pose(self):
        with tempfile.TemporaryDirectory() as folder:
            def row(frame,state,map_id):
                return dict(schema=1,source_frame_id=frame,timestamp_ns=1000+frame,tracking_state=state,
                            features=1,levels=[1]+[0]*7,angle_bins=[1]+[0]*31,tcw=None,events_dropped=0,
                            events=[dict(stage='tracking_exit',state=state,map_id=map_id)])
            path=Path(folder)/'tracking_diagnostics.part000000.jsonl'
            path.write_text(''.join(json.dumps(x)+'\n' for x in (row(1,2,0),row(2,3,0),row(3,0,1)))+'{"unfinished"')
            result=summarize(folder)
            self.assertEqual(result['frames'],3)
            self.assertEqual(result['incomplete_tail_lines'],1)
            self.assertEqual(len(result['loss_windows']),1)
            self.assertEqual(result['transitions'][-1]['to_map'],1)
            self.assertEqual(result['max_adjacent_valid_rotation_deg'],0)

if __name__=='__main__':unittest.main()
