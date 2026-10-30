"""Decode immutable C0 copies to lossless grayscale PNGs with PC parser timestamps."""
import argparse,csv,hashlib,json,pathlib
from decimal import Decimal,ROUND_HALF_EVEN
import av,cv2

ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def relative_ns(clock,origin):
    return 1_000_000_000+int(((clock-origin)*Decimal(10**9)).to_integral_value(rounding=ROUND_HALF_EVEN))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=pathlib.Path,default=ROOT/'reports/c0')
    p.add_argument('--output',type=pathlib.Path,required=True); a=p.parse_args()
    if a.output.exists(): raise SystemExit('Refusing existing dataset directory')
    manifest=json.loads((a.audit/'source_manifest.json').read_text(encoding='utf-8'))
    source=pathlib.Path(manifest['copy_root'])
    checksums={str(pathlib.Path(r['path'])):r['sha256'] for r in manifest['files']}
    a.output.mkdir(parents=True); clips=[]
    for cap in sorted(source.rglob('capture.json')):
        directory=cap.parent; clip=directory.name; target=a.output/clip
        for name in ('capture.json','packets.jsonl','video.mp4'):
            if sha(directory/name)!=checksums[str((directory/name).relative_to(source))]: raise ValueError('C0 copy changed')
        capture=json.loads(cap.read_text(),parse_float=Decimal)
        packets={p['tag']:p for p in (json.loads(line,parse_float=Decimal) for line in (directory/'packets.jsonl').read_text().splitlines())}
        with (a.audit/'raw'/clip/'frame_quality.csv').open(newline='',encoding='utf-8') as f: quality=list(csv.DictReader(f))
        selected=[q for q in quality if packets[int(q['packet_tag'])]['t_parser_emit']>=capture['started']]
        if not selected: raise ValueError('No post-start decoded frames')
        origin=packets[int(selected[0]['packet_tag'])]['t_parser_emit']
        images=target/'mav0/cam0/data'; images.mkdir(parents=True)
        rows=[]; decoded=0
        with av.open(str(directory/'video.mp4')) as container:
            stream=container.streams.video[0]; stream.codec_context.thread_count=2
            width,height=stream.codec_context.width,stream.codec_context.height
            for packet in container.demux(stream):
                try: frames=packet.decode()
                except av.error.FFmpegError: continue
                for frame in frames:
                    q=quality[decoded]; decoded+=1
                    if abs(float(frame.time)-float(q['mp4_pts_s']))>1e-6 or bool(frame.is_corrupt)!=(q['corrupt']=='True'):
                        raise ValueError('Decoder frame mapping differs from C0')
                    tag=int(q['packet_tag']); clock=packets[tag]['t_parser_emit']
                    if clock<capture['started']: continue
                    ns=relative_ns(clock,origin)
                    if rows and ns<=rows[-1]['timestamp_ns']: raise ValueError('Non-increasing parser clock; decision needed')
                    gray=frame.to_ndarray(format='gray')
                    if gray.shape!=(height,width): raise ValueError('Unexpected resolution')
                    path=images/(str(ns)+'.png')
                    if not cv2.imwrite(str(path),gray,[cv2.IMWRITE_PNG_COMPRESSION,3]): raise ValueError('PNG write failed')
                    rows.append(dict(frame_index=len(rows),timestamp_ns=ns,image=str(path.relative_to(target)).replace('\\','/'),
                        source_frame_index=int(q['frame_index']),packet_tag=tag,parser_clock_s=str(clock),
                        capture_relative_s=str(clock-capture['started']),mp4_pts_s=q['mp4_pts_s'],
                        corrupt=q['corrupt'],sha256=sha(path)))
        if decoded!=len(quality) or len(rows)!=len(selected): raise ValueError('Decode coverage mismatch')
        with (target/'frames.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        (target/'timestamps.txt').write_text(''.join(str(r['timestamp_ns'])+'\n' for r in rows),encoding='ascii',newline='\n')
        item=dict(clip=clip,dataset=clip,expected_frames=len(rows),width=width,height=height,
            duration_s=(rows[-1]['timestamp_ns']-rows[0]['timestamp_ns'])/1e9,
            excluded_preroll_frames=len(quality)-len(rows),corrupt_frames=sum(r['corrupt']=='True' for r in rows),
            timestamps='PC parser availability clock, relative integer nanoseconds + 1 second',
            no_reencoding=True,pixel_conversion='FFmpeg decoded 8-bit grayscale; lossless PNG',
            original_mp4_sha256=checksums[str((directory/'video.mp4').relative_to(source))],
            timestamps_sha256=sha(target/'timestamps.txt'),frames_csv_sha256=sha(target/'frames.csv'),
            intrinsics_label='临时内参，待标定后重跑',settings='configs/c/tello_oafd_960x720_provisional.yaml')
        (target/'dataset.json').write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding='utf-8')
        clips.append(item)
        print('C1_PREPARED %s frames=%d duration=%.3fs corrupt=%d'%(clip,len(rows),item['duration_s'],item['corrupt_frames']),flush=True)
    (a.output/'manifest.json').write_text(json.dumps(dict(version=1,clips=clips),indent=2,ensure_ascii=False),encoding='utf-8')
    print('C1_DATASET_COMPLETE clips=%d'%len(clips))
if __name__=='__main__': main()
