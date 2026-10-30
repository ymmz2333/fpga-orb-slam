import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from orb60.demo_bridge.patch_shutdown import patch
from orb60.demo_bridge.controller import Controller

class Shutdown(unittest.TestCase):
    def test_worker_quiescence_precedes_atlas_save_and_is_idempotent(self):
        before='#include "System.h"\nvoid System::Shutdown()\n{ SaveAtlas(FileType::BINARY_FILE); }\nbool System::isShutDown(){return true;}\n'
        after=patch(before)
        self.assertLess(after.index('while(!mpLocalMapper->isFinished()'),after.index('SaveAtlas(FileType::BINARY_FILE)'))
        self.assertLess(after.index('mptLoopClosing->join()'),after.index('SaveAtlas(FileType::BINARY_FILE)'))
        self.assertEqual(patch(after),after)
        self.assertIn('bool System::isShutDown(){return true;}',after)

    def test_signal_exit_and_last_stage_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Controller({});c.run=Path(tmp);(c.run/'tracking').mkdir()
            (c.run/'tracking/handover_stage.json').write_text('{"stage":"SHUTDOWN_BEGIN"}')
            c.state='MAPPING';c.child=Mock();c.child.wait.return_value=-11;c.zcommand=Mock(return_value={})
            with self.assertRaisesRegex(RuntimeError,'SIGSEGV.*SHUTDOWN_BEGIN'):c._finalize()
            report=json.loads((c.run/'handover_receiver_exit.json').read_text())
            self.assertEqual(report['returncode'],-11);self.assertEqual(report['signal'],'SIGSEGV')

if __name__=='__main__':unittest.main()
