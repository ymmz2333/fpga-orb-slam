#!/usr/bin/env python3
"""Read-only original protection; byte copies, codec/timestamp audit, no re-encoding."""
import argparse
import csv
import ctypes
import hashlib
import json
import math
import pathlib
import re
import shutil
import stat
import statistics
import subprocess
import time
from fractions import Fraction
import av

START=re.compile(b'\x00\x00(?:\x00)?\x01')

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def csvwrite(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0])); w.writeheader(); w.writerows(rows)

def quantile(values,q):
    a=sorted(values); x=(len(a)-1)*q; low=math.floor(x); high=math.ceil(x)
    return a[low]+(a[high]-a[low])*(x-low)

def jsonl(path):
    with path.open(encoding='utf-8') as f: return [json.loads(line) for line in f if line.strip()]

def interval_stats(times):
    dt=[(b-a)*1000 for a,b in zip(times,times[1:])]
    if not dt:
        return dict(intervals=0,median_ms='',mean_ms='',p05_ms='',p95_ms='',p99_ms='',
                    min_ms='',max_ms='',nonpositive=0,gap_gt50ms=0,stall_ge100ms=0)
    return dict(intervals=len(dt),median_ms=statistics.median(dt),mean_ms=statistics.mean(dt),
                p05_ms=quantile(dt,.05),p95_ms=quantile(dt,.95),p99_ms=quantile(dt,.99),
                min_ms=min(dt),max_ms=max(dt),nonpositive=sum(t<=0 for t in dt),
                gap_gt50ms=sum(t>50 for t in dt),stall_ge100ms=sum(t>=100 for t in dt))

def nal_digest(payload,avcc=False):
    units=[]
    if avcc:
        pos=0
        while pos<len(payload):
            size=int.from_bytes(payload[pos:pos+4],'big'); pos+=4
            if size<=0 or pos+size>len(payload): raise ValueError('Invalid AVC NAL length')
            units.append(payload[pos:pos+size]); pos+=size
    else:
        starts=list(START.finditer(payload))
        for i,m in enumerate(starts): units.append(payload[m.end():starts[i+1].start() if i+1<len(starts) else len(payload)])
    vcl=[u for u in units if u and u[0]&31 in (1,5)]
    return hashlib.sha256(b''.join(len(u).to_bytes(4,'big')+u for u in vcl)).hexdigest() if vcl else None

def protect_copy(source,work,out):
    original_files=sorted(p for p in source.rglob('*') if p.is_file())
    manifest=[]
    if not original_files: raise ValueError('No recordings')
    if any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Source symlink rejected')
    if any(not json.loads(p.read_text(encoding='utf-8')).get('closed') for p in source.rglob('capture.json')):
        raise ValueError('Active/unclosed recording; refusing protection or copy')
    kernel=ctypes.windll.kernel32 if hasattr(ctypes,'windll') else None
    if kernel:
        kernel.GetFileAttributesW.argtypes=[ctypes.c_wchar_p]; kernel.GetFileAttributesW.restype=ctypes.c_uint32
        kernel.SetFileAttributesW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32]
    previous=out/'source_manifest.json'
    old={r['path']:r for r in json.loads(previous.read_text(encoding='utf-8'))['files']} if previous.exists() else {}
    for p in original_files:
        if p.is_symlink(): raise ValueError('Source symlink rejected')
        relative=str(p.relative_to(source)); checksum=sha(p)
        if relative in old and old[relative]['sha256']!=checksum: raise ValueError('Original changed since first manifest: '+relative)
        attr=kernel.GetFileAttributesW(str(p)) if kernel else stat.S_IMODE(p.stat().st_mode)
        q=work/p.relative_to(source); q.parent.mkdir(parents=True,exist_ok=True)
        if not q.exists(): shutil.copy2(p,q); q.chmod(stat.S_IREAD|stat.S_IWRITE)
        if sha(q)!=checksum: raise ValueError('Copy mismatch: '+relative)
        if kernel:
            if not kernel.SetFileAttributesW(str(p),attr|1): raise OSError('ReadOnly failed: '+relative)
            after=kernel.GetFileAttributesW(str(p)); readonly=bool(after&1)
        else:
            p.chmod(attr & ~0o222); after=stat.S_IMODE(p.stat().st_mode); readonly=not bool(after&0o222)
        if not readonly: raise ValueError('Original is not read-only')
        manifest.append(dict(path=relative,bytes=p.stat().st_size,sha256=checksum,
                             attributes_before=old.get(relative,{}).get('attributes_before',attr),attributes_after=after,read_only=True))
    previous.write_text(json.dumps(dict(source_root=str(source),copy_root=str(work),files=manifest),indent=2),encoding='utf-8')
    csvwrite(out/'source_manifest.csv',manifest)
    return manifest

def probe(video,target,ffprobe):
    entries='stream=codec_name,profile,width,height,pix_fmt,has_b_frames,r_frame_rate,avg_frame_rate,time_base,nb_frames,duration,bit_rate:format=format_name,duration,size,bit_rate:frame=pts_time,best_effort_timestamp_time,pict_type,key_frame'
    cmd=[ffprobe,'-v','warning','-threads','2','-select_streams','v:0','-show_streams','-show_format','-show_frames','-show_entries',entries,'-of','json',str(video)]
    with (target/'ffprobe.json').open('wb') as f, (target/'ffprobe.log').open('wb') as log:
        run=subprocess.run(cmd,stdout=f,stderr=log,timeout=180,check=False)
    if run.returncode: raise RuntimeError('ffprobe failed, exit='+str(run.returncode))
    data=json.loads((target/'ffprobe.json').read_text(encoding='utf-8'))
    (target/'ffprobe_command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
    return data

def save_clock_reference(directory,target):
    capture=json.loads((directory/'capture.json').read_text(encoding='utf-8'))
    packets=jsonl(directory/'packets.jsonl')
    metadata=dict(capture_started_s=capture['started'],capture_ended_s=capture['ended'],
                  parser_origin_s=packets[0]['t_parser_emit'],
                  units='PC perf_counter seconds; not camera capture time')
    (target/'clock_reference.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')

def audit_clip(directory,target,ffprobe):
    target.mkdir(parents=True,exist_ok=True)
    save_clock_reference(directory,target)
    capture=json.loads((directory/'capture.json').read_text(encoding='utf-8'))
    playback=json.loads((directory/'playback.json').read_text(encoding='utf-8'))
    packets=jsonl(directory/'packets.jsonl'); live=jsonl(directory/'frames.jsonl')
    if len(packets)!=capture['packets'] or len(live)!=capture['decoded_frames']: raise ValueError('Capture count mismatch')
    if sum(p['bytes'] for p in packets)!=(directory/'packets.h264').stat().st_size: raise ValueError('Packet file size mismatch')
    if len({p['tag'] for p in packets})!=len(packets) or len({p['tag'] for p in live})!=len(live): raise ValueError('Duplicate association tag')
    info=probe(directory/'video.mp4',target,ffprobe); stream=info['streams'][0]; fmt=info['format']
    pts=[float(f['best_effort_timestamp_time']) for f in info['frames']]
    times=[p['t_parser_emit'] for p in packets]; ready=[p['t_ready'] for p in live]
    timing=[]; events=[]
    for domain,values in (('mp4_decoded_frame_pts',pts),('pc_parser_emit',times),('pc_decode_ready',ready)):
        timing.append(dict(clip=directory.name,clock=domain,**interval_stats(values)))
        for i,(a,b) in enumerate(zip(values,values[1:])):
            if (b-a)*1000>50:
                events.append(dict(clip=directory.name,event='stall_ge100ms' if b-a>=.1 else 'gap_gt50ms',clock=domain,
                    index_before=i,index_after=i+1,start_relative_s=a-values[0],end_relative_s=b-values[0],interval_ms=(b-a)*1000,
                    tag_before=packets[i]['tag'] if domain=='pc_parser_emit' else live[i]['tag'] if domain=='pc_decode_ready' else '',
                    tag_after=packets[i+1]['tag'] if domain=='pc_parser_emit' else live[i+1]['tag'] if domain=='pc_decode_ready' else ''))
    # Direct encoded-slice comparison proves MP4 remux did not re-encode pictures.
    original_hashes=[]; original_tag=[]; packet_by_tag={r['tag']:r for r in packets}
    with (directory/'packets.h264').open('rb') as raw:
        for p in packets:
            if raw.tell()!=p['offset']: raise ValueError('Non-contiguous packet offsets')
            payload=raw.read(p['bytes']); digest=nal_digest(payload)
            if digest: original_hashes.append(digest); original_tag.append(p['tag'])
    mp4_hashes=[]; mp4_packet_times=[]; pts_to_tag={}; quality=[]; decode_errors=0
    av.logging.set_level(av.logging.ERROR)
    with av.logging.Capture(local=True) as logs:
        with av.open(str(directory/'video.mp4')) as container:
            video=container.streams.video[0]; video.codec_context.thread_count=2
            if (video.codec_context.extradata[4] & 3) + 1 != 4:
                raise ValueError('Unsupported AVC NAL length size (expected four bytes)')
            for packet in container.demux(video):
                if packet.size:
                    digest=nal_digest(bytes(packet),avcc=True)
                    if digest:
                        index=len(mp4_hashes); mp4_hashes.append(digest)
                        mp4_packet_times.append(float(packet.pts*packet.time_base))
                        if index<len(original_tag): pts_to_tag[packet.pts]=original_tag[index]
                try: frames=packet.decode()
                except av.error.FFmpegError: decode_errors+=1; continue
                for frame in frames:
                    tag=pts_to_tag.get(frame.pts); p=packet_by_tag.get(tag,{})
                    quality.append(dict(frame_index=len(quality),mp4_pts_s=float(frame.time),packet_tag=tag,
                        parser_relative_s=p.get('t_parser_emit',times[0])-times[0],corrupt=bool(frame.is_corrupt),key_frame=bool(frame.key_frame)))
    (target/'pyav_decode.log').write_text('\n'.join(str(x) for x in logs),encoding='utf-8')
    vcl_equal=original_hashes==mp4_hashes
    timing.append(dict(clip=directory.name,clock='mp4_synthetic_packet_pts',**interval_stats(mp4_packet_times)))
    decoded_tags={r['packet_tag'] for r in quality}
    omitted=[tag for tag in original_tag if tag not in decoded_tags]
    for tag in omitted:
        p=packet_by_tag[tag]
        events.append(dict(clip=directory.name,event='encoded_packet_no_offline_decoded_frame',clock='pc_parser_emit',
            index_before=packets.index(p),index_after='',start_relative_s=p['t_parser_emit']-times[0],end_relative_s='',interval_ms='',tag_before=tag,tag_after=''))
    csvwrite(target/'frame_quality.csv',quality)
    live_tags={r['tag'] for r in live}
    preroll=[p for p in packets if p['t_parser_emit']<capture['started']]
    missing=[p for p in packets if p['t_parser_emit']>=capture['started'] and p['tag'] not in live_tags]
    for p in missing:
        events.append(dict(clip=directory.name,event='poststart_tag_no_live_frame',clock='pc_parser_emit',index_before=packets.index(p),
             index_after='',start_relative_s=p['t_parser_emit']-times[0],end_relative_s='',interval_ms='',tag_before=p['tag'],tag_after=''))
    for f in quality:
        if f['corrupt']:
            events.append(dict(clip=directory.name,event='corrupt_decoded_frame',clock='mp4_decoded_frame_pts',index_before=f['frame_index'],
                index_after='',start_relative_s=f['mp4_pts_s'],end_relative_s='',interval_ms='',tag_before=f['packet_tag'],tag_after=''))
    log=(target/'ffprobe.log').read_text(encoding='utf-8',errors='replace')
    row=dict(clip=directory.name,kind=capture['kind'],container=fmt['format_name'],codec=stream['codec_name'],profile=stream['profile'],
        width=stream['width'],height=stream['height'],nominal_fps=stream['r_frame_rate'],mp4_avg_fps=stream['avg_frame_rate'],
        mp4_decoded_fps=(len(pts)-1)/(pts[-1]-pts[0]),pc_parser_fps=(len(times)-1)/(times[-1]-times[0]),
        pc_ready_fps=(len(ready)-1)/(ready[-1]-ready[0]),mp4_video_bitrate_bps=stream.get('bit_rate',''),mp4_container_bitrate_bps=fmt['bit_rate'],
        received_payload_bitrate_bps=sum(p['bytes'] for p in packets if p['t_parser_emit']>=capture['started'])*8/(capture['ended']-capture['started']),
        mp4_total_frames=len(pts),mp4_declared_frames=stream.get('nb_frames',''),pyav_decoded_frames=len(quality),
        capture_live_frames=len(live),packet_records=len(packets),mp4_duration_s=float(fmt['duration']),
        capture_wall_s=capture['ended']-capture['started'],parser_span_s=times[-1]-times[0],ready_span_s=ready[-1]-ready[0],
        preroll_packets=len(preroll),poststart_packets_without_live_frame=len(missing),mp4_synthetic_pts=True,
        compressed_vcl_equal=vcl_equal,raw_vcl_packets=len(original_hashes),mp4_vcl_packets=len(mp4_hashes),
        corrupt_decoded_frames=sum(r['corrupt'] for r in quality),decode_exceptions=decode_errors,
        encoded_packets_without_decoded_frame=len(omitted),
        ffprobe_error_lines=len(log.splitlines()),requested_bitrate=capture.get('requested_settings',{}).get('bitrate'),
        live_dimensions=json.dumps(sorted({(r['width'],r['height']) for r in live})),
        camera_timestamp_available=False,status='PASS' if vcl_equal and len(quality)==len(pts) else 'CHECK_NEEDED')
    return row,timing,events

def main():
    p=argparse.ArgumentParser(); p.add_argument('--recordings',required=True); p.add_argument('--work',required=True); p.add_argument('--output',required=True)
    p.add_argument('--ffprobe',default='ffprobe'); a=p.parse_args()
    source=pathlib.Path(a.recordings).resolve(); work=pathlib.Path(a.work).resolve(); out=pathlib.Path(a.output).resolve()
    if any(source==dest or source in dest.parents or dest in source.parents for dest in (work,out)):
        raise ValueError('Analysis output/copies must not overlap originals')
    out.mkdir(parents=True,exist_ok=True); manifest=protect_copy(source,work,out)
    rows=[]; timings=[]; events=[]
    for capture in sorted(work.rglob('capture.json')):
        row,t,e=audit_clip(capture.parent,out/'raw'/capture.parent.name,a.ffprobe); rows.append(row); timings+=t; events+=e
        print('C0_CLIP_DONE %s %sx%s frames=%s corrupt=%s vcl_equal=%s'%(row['clip'],row['width'],row['height'],row['mp4_total_frames'],row['corrupt_decoded_frames'],row['compressed_vcl_equal']),flush=True)
    csvwrite(out/'inventory.csv',rows); csvwrite(out/'timestamp_stats.csv',timings)
    csvwrite(out/'timing_events.csv',events,fields=['clip','event','clock','index_before','index_after','start_relative_s','end_relative_s','interval_ms','tag_before','tag_after'])
    unchanged=all(sha(source/r['path'])==r['sha256'] for r in manifest)
    passed=unchanged and all(r['status']=='PASS' for r in rows)
    warnings=any(r['corrupt_decoded_frames'] or r['encoded_packets_without_decoded_frame'] for r in rows)
    result=dict(status=('PASS_WITH_DATA_WARNINGS' if warnings else 'PASS') if passed else 'CHECK_NEEDED',
        clips=len(rows),files=len(manifest),source_bytes=sum(r['bytes'] for r in manifest),original_sha256_unchanged=unchanged,
        analysis_on_copies=True,reencoded=False,clips_with_corrupt_frames=sum(r['corrupt_decoded_frames']>0 for r in rows),
        timing_event_count=len(events),timestamp_limit='MP4 has synthetic constant-fps PTS; sidecars are PC parser/decoder clocks, not camera capture clocks')
    (out/'acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('C0_INVENTORY_FINISHED '+json.dumps(result),flush=True)

if __name__=='__main__': main()
