import json
import csv
import cv2
import numpy as np
import pytest
from orb60.dense.kv260.common import digest,save
from orb60.dense.kv260.replay import fuse_blocks,update_poses,inside
from orb60.dense.kv260.replay import replay
from orb60.dense.ply import read_ply


def make_map(folder,mid):
    folder.mkdir();blocks=[]
    for key,x in [('a',0.),('b',2.)]:
        path=folder/(key+'.npz');pose=np.eye(4);pose[0,3]=x
        np.savez_compressed(path,xyz_camera=np.array([[0.,0,2],[.02,0,2]],np.float32),
                            rgb=np.array([[255,0,0],[0,0,255]],np.uint8),twc=pose)
        blocks.append({'name':key,'file':path.name,'sha256':digest(path)})
    save(folder/'blocks.json',{'map_id':mid,'reference':1.,'capacity':100,'blocks':blocks})
    return blocks


def test_pose_updates_preserve_local_points_and_maps(tmp_path):
    first=tmp_path/'map0';blocks=make_map(first,0);second=tmp_path/'map1';make_map(second,1)
    fuse_blocks(first,blocks,1.,100);before,colors=read_ply(first/'dense.ply');hashes=[digest(first/b['file']) for b in blocks]
    pose=np.eye(4);pose[0,3]=10;changes=tmp_path/'updates.json';save(changes,{'map_id':0,'poses':{'a':pose.tolist()}})
    update_poses(first,changes);after,after_colors=read_ply(first/'dense.ply')
    assert np.max(after[:,0])>9 and np.min(after[:,0])>1
    np.testing.assert_array_equal(np.sort(colors,axis=0),np.sort(after_colors,axis=0))
    # A second partial correction must retain the first correction.
    pose[0,3]=20;save(changes,{'map_id':0,'poses':{'b':pose.tolist()}});update_poses(first,changes)
    xyz,_=read_ply(first/'dense.ply');assert np.min(xyz[:,0])>=10 and np.max(xyz[:,0])>=20
    assert hashes==[digest(first/b['file']) for b in blocks]
    with pytest.raises(ValueError):update_poses(second,changes)
    assert not (second/'dense.ply').exists()


def test_block_corruption_capacity_and_no_path_escape(tmp_path):
    folder=tmp_path/'map';blocks=make_map(folder,0);r=fuse_blocks(folder,blocks,1.,1);assert r['points']<=1
    (folder/'a.npz').write_bytes(b'broken')
    with pytest.raises(ValueError):fuse_blocks(folder,blocks,1.,100)
    with pytest.raises(ValueError):inside(folder,'../outside.npz')


def test_end_to_end_saved_replay_maps_pairing_and_nan(tmp_path):
    from orb60.dense.geometry import backproject
    inputs=tmp_path/'inputs';inputs.mkdir();depths=tmp_path/'depths';depths.mkdir()
    maps=[];rows=[];k=np.array([[30.,0,15.5],[0,30.,11.5],[0,0,1.]])
    for mid,color in [(0,[0,0,255]),(1,[255,0,0])]:
        folder=inputs/('map_%d'%mid);folder.mkdir();frames=[];observations=[]
        for j,tx in enumerate([0.,.08]):
            name='m%d_k%d'%(mid,j);pose=np.eye(4);pose[0,3]=tx
            image=np.full((24,32,3),color,np.uint8);cv2.imwrite(str(folder/(name+'.png')),image)
            cv2.imwrite(str(folder/(name+'.mask.png')),np.full((24,32),255,np.uint8))
            # A slanted plane z + .2*x = 2, in both camera views.
            u=(np.arange(256)+.5)*32/256-.5
            prediction=np.broadcast_to(((1+.2*(u-15.5)/30)/(2-.2*tx))[None,:],(256,256)).astype('<f4').copy()
            prediction.tofile(depths/(name+'.output.f32'))
            resized=cv2.resize(prediction,(32,24),interpolation=cv2.INTER_LINEAR)
            yy,xx=np.mgrid[3:21:2,3:29:2];uv=np.c_[xx.ravel(),yy.ravel()];z=1/resized[yy,xx].ravel()
            world=backproject(uv,z,k,pose)
            for n,(pixel,xyz) in enumerate(zip(uv,world)):
                observations.append({'keyframe_id':j,'point_id':j*1000+n,'u':pixel[0],'v':pixel[1],
                                     'x':xyz[0],'y':xyz[1],'z':xyz[2]})
            frame={'map_id':mid,'keyframe_id':j,'timestamp_ns':j+1,'twc':pose.tolist(),'k':k.tolist(),
                   'name':name,'selected':True,'input_sha256':'input_'+name,
                   'rgb':'map_%d/%s.png'%(mid,name),'valid_mask':'map_%d/%s.mask.png'%(mid,name)}
            frames.append(frame);rows.append({'id':name,'input_sha256':frame['input_sha256'],
                                               'output_sha256':digest(depths/(name+'.output.f32'))})
        with (folder/'observations.csv').open('w',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=list(observations[0]));w.writeheader();w.writerows(observations)
        maps.append({'map_id':mid,'frames':frames,'observations':'map_%d/observations.csv'%mid})
    save(inputs/'keyframes.json',{'maps':maps})
    report={'status':'HOST_REFERENCE_PASS','backend':'reference','model_sha256':'model','hardware_inference_verified':False,'frames':rows}
    save(depths/'worker.json',report)
    result=replay(inputs,depths,tmp_path/'cloud',capacity=10)
    assert result['status']=='HOST_REPLAY_PASS' and len(result['maps'])==2
    for mid,expected in [(0,[255,0,0]),(1,[0,0,255])]:
        xyz,rgb=read_ply(tmp_path/'cloud'/('map_%d'%mid)/'dense.ply');assert 0<len(xyz)<=10
        np.testing.assert_array_equal(rgb,np.broadcast_to(expected,rgb.shape))
    report['frames']=list(reversed(rows));save(depths/'worker.json',report)
    with pytest.raises(ValueError,match='ordering'):replay(inputs,depths,tmp_path/'bad_order')
    report['frames']=rows
    bad=depths/(rows[0]['id']+'.output.f32');np.full((256,256),np.nan,np.float32).tofile(bad)
    rows[0]['output_sha256']=digest(bad);save(depths/'worker.json',report)
    with pytest.raises(ValueError,match='Nonfinite'):replay(inputs,depths,tmp_path/'nan')
