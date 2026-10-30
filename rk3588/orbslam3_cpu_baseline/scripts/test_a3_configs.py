import json
import pathlib
import re
import unittest
from prepare_a3 import ROOT, SPECS, generate

class ConfigurationTests(unittest.TestCase):
    def test_single_dimension_changes(self):
        manifest=generate()
        baseline=manifest[0]
        for item in manifest[1:]:
            changes=sum(item[k]!=baseline[k] for k in ('tracking_width','nFeatures','nLevels'))
            self.assertEqual(changes,1)
            self.assertEqual(item['initialization_nFeatures'],5*item['nFeatures'])
            text=(ROOT/item['settings']).read_text()
            self.assertEqual('Camera.newWidth:' in text,item['tracking_width']==376)
            self.assertEqual('Camera.newHeight:' in text,item['tracking_height']==240)
        self.assertEqual(manifest[1]['effective_intrinsics'],[229.327,228.648,183.6075,124.1875])

    def test_round_robin_schedule(self):
        schedule=[(run,spec[0]) for run in range(1,6) for spec in SPECS]
        self.assertEqual(len(set(schedule)),30)
        for run in range(1,6):
            self.assertEqual([name for index,name in schedule if index==run],[spec[0] for spec in SPECS])

if __name__=='__main__': unittest.main()
