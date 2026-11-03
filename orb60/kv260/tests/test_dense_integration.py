import argparse
import tempfile
from pathlib import Path
import unittest
import csv
import json
import hashlib
import os
import subprocess
import sys
from unittest.mock import patch
import numpy as np
from orb60.kv260.gui import commands
from orb60.kv260.frame_store import FrameStore
from orb60.kv260.dense_fusion import Fusion
from orb60.dense.kv260.placement import validate_placement
from orb60.dense.kv260.compile_model import check_application_acceptance
from orb60.dense.kv260.preflight import query_current_device


class TestDenseIntegration(unittest.TestCase):
    def test_device_query_overrides_firmware_autoload_without_changing_caller(self):
        reply=subprocess.CompletedProcess(['xdputil','query'],0,'{"kernels":[]}', '')
        version=subprocess.CompletedProcess(['xbutil','--version'],0,'Version : 2.13.0\n', '')
        with patch.dict(os.environ,{'XLNX_DISABLE_LOAD_XCLBIN':'0'}),patch('orb60.dense.kv260.preflight.subprocess.run',side_effect=[reply,version]) as run,patch('orb60.dense.kv260.preflight.shutil.which',return_value=__file__):
            actual=query_current_device()
            self.assertEqual(actual['kernels'],[])
            self.assertEqual(actual['XRT Runtime Probe']['version'],'2.13.0')
            self.assertEqual(run.call_count,2)
            for call in run.call_args_list:self.assertEqual(call.kwargs['env']['XLNX_DISABLE_LOAD_XCLBIN'],'1')
            self.assertEqual(run.call_args_list[0].args[0][:3],[sys.executable,'-m','xdputil'])
            self.assertEqual(run.call_args_list[1].args[0],[__file__,'--version'])
            self.assertEqual(os.environ['XLNX_DISABLE_LOAD_XCLBIN'],'0')

    def test_device_query_preserves_native_failure_details(self):
        error=subprocess.CalledProcessError(-6,['xdputil','query'],stderr='missing xclbin metadata')
        with patch('orb60.dense.kv260.preflight.subprocess.run',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'Read-only DPU query failed.*missing xclbin metadata'):query_current_device()

    def test_gui_default_is_separate_local_dense_windows(self):
        args=argparse.Namespace(renderer='gles2',recording=None,dense=None,dense_live='127.0.0.1:18786',telemetry=None,
                               video=None,screenshot=None,exit_after=0,metrics=None)
        command,bridge=commands(args)
        self.assertIn('--separate-maps',command);self.assertIn('--dense-live',command);self.assertIsNone(bridge)

    def test_gui_instances_do_not_overwrite_each_others_status(self):
        def args(name):
            return argparse.Namespace(renderer='gles2',recording=None,dense=Path('map'),dense_live=None,
                                      telemetry=None,video=None,screenshot=None,exit_after=0,metrics=Path('run')/name)
        live,_=commands(args('gpu_display.json'));offline,_=commands(args('final_gpu.json'))
        live_status=live[live.index('--desktop-status')+1]
        offline_status=offline[offline.index('--desktop-status')+1]
        self.assertNotEqual(live_status,offline_status)
        self.assertEqual(Path(live_status).parent,Path('run'))

    def test_exact_rgb_pose_pairing_and_cache_bound(self):
        with tempfile.TemporaryDirectory() as d:
            store=FrameStore(d,capacity=2);image=np.zeros((720,960,3),np.uint8);gray=np.zeros((720,960),np.uint8)
            record=store.publish(0,12345,image,gray);self.assertEqual(store.read(record).shape,image.shape)
            with self.assertRaises(ValueError):store.read(dict(record,timestamp_ns=12346))
            store.publish(1,12346,image,gray);store.publish(2,12347,image,gray)
            self.assertFalse((Path(d)/'f0.json').exists())

    def test_cpu_convolution_stays_forbidden_and_relu_is_model_explicit(self):
        groups=[{'device':'DPU','ops':[{'name':'conv','type':'conv2d-fix'}]}, {'device':'CPU','ops':[{'name':'boundary','type':'relu'}]}]
        with self.assertRaises(ValueError):validate_placement(groups)
        self.assertEqual(validate_placement(groups,[{'name':'boundary','type':'relu'}])['convolutions'],1)
        groups[0]['device']='CPU'
        with self.assertRaises(ValueError):validate_placement(groups,[{'name':'boundary','type':'relu'}])
        with self.assertRaises(ValueError):check_application_acceptance({'status':'QUANTIZATION_FAILED','checkpoint_sha256':'A','reproduction_status':'PASS'},{'user_visual_acceptance':True,'weights_sha256':'B'})

    def test_rgb_fusion_and_pose_updates_keep_local_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            events=[];fusion=Fusion(Path(d)/'blocks',lambda meta,payload:events.append((meta.copy(),payload)),'quantized-reference-test')
            k=np.array([[600.,0,480.],[0,600.,360.],[0,0,1.]])
            yy,xx=np.mgrid[0:720,0:960];bgr=np.stack((xx%256,yy%256,(xx+yy)%256),axis=-1).astype(np.uint8)
            u,v=np.meshgrid(np.linspace(100,850,12),np.linspace(100,620,8));u=u.ravel();v=v.ravel();alpha=.3
            xnet=(np.arange(256)+.5)*960/256-.5
            for i,t in enumerate((0.,.08)):
                pose=np.eye(4);pose[0,3]=t
                z=(1-alpha*t)/(1+alpha*(u-480)/600)
                observations=np.c_[u,v,(u-480)*z/600+t,(v-360)*z/600,z,np.arange(len(u))]
                prediction=np.broadcast_to((1+alpha*(xnet-480)/600)/(1-alpha*t),(256,256)).astype(np.float32).copy()
                meta={'map_id':0,'keyframe_id':i,'source_frame_id':i,'timestamp_ns':100+i,'twc':pose.tolist(),'observations':observations.tolist()}
                fusion.process(meta,bgr,prediction,k,np.zeros(5))
            self.assertGreater(len(events),0);original=events[0][1]
            xyz_rgb=np.frombuffer(original,dtype=[('xyz','<f4',(3,)),('rgb','u1',(3,))])
            self.assertTrue(np.isfinite(xyz_rgb['xyz']).all());self.assertGreater(np.std(xyz_rgb['rgb'].astype(float)),20)
            pose=np.eye(4);pose[1,3]=.2;key=events[0][0]['keyframe_id'];fusion.update_pose(0,key,pose)
            self.assertEqual(events[-1][1],original);self.assertEqual(events[-1][0]['revision'],2)
            self.assertGreater(fusion.export(0,Path(d)/'color.ply')['points'],100)
            with self.assertRaises(ValueError):fusion.update_pose(99,key,pose)
            tracking=Path(d)/'tracking';(tracking/'map').mkdir(parents=True)
            (tracking/'map/map_id.txt').write_text('0')
            with (tracking/'frames.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['source_frame_id','slam_timestamp_ns']);writer.writerows([[0,100],[1,101]])
            pose=np.eye(4);pose[1,3]=.2
            with (tracking/'map/final_frames.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['map_id','slam_timestamp_ns']+['twc_%d%d'%(r,c) for r in range(4) for c in range(4)])
                writer.writerow([0,100]+pose.ravel().tolist())
            anchor=json.loads((fusion.folder/'m0_f0.anchors.json').read_text())
            with (tracking/'map/points.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['point_id','x','y','z'])
                for row in anchor['observations']:writer.writerow([int(row[5]),row[2]*2,row[3]*2+.2,row[4]*2])
            before=hashlib.sha256((fusion.folder/'m0_f0.bin').read_bytes()).hexdigest()
            report=fusion.finalize(tracking);self.assertIn('m0_f0',report['accepted'])
            final=(fusion.folder/'m0_f0.final.bin').read_bytes();fusion.finalize(tracking)
            self.assertEqual((fusion.folder/'m0_f0.final.bin').read_bytes(),final)
            self.assertEqual(hashlib.sha256((fusion.folder/'m0_f0.bin').read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
