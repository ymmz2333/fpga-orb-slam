"""Offline analysis of a completed recording from the TT live viewer."""
import argparse
import json
from pathlib import Path

import av
import cv2
import numpy as np
from tt_latency_recording import DICTIONARY


def analyze(directory):
    directory = Path(directory)
    capture = json.loads((directory/'capture.json').read_text())
    if not capture.get('closed'): raise ValueError('Recording is not closed')
    frames = {row['tag']:row for row in
              (json.loads(line) for line in (directory/'frames.jsonl').read_text().splitlines())}
    patterns = [json.loads(line) for line in (directory/'pattern.jsonl').read_text().splitlines()]
    issued = {row['id']:row['t_submit'] for row in patterns}
    if len(issued)!=len(patterns): raise ValueError('Duplicate marker IDs in recording')
    codec = av.CodecContext.create('h264','r');codec.thread_count=1
    detector = cv2.aruco.ArucoDetector(DICTIONARY);cv2.setNumThreads(1)
    headers = (directory/'codec_headers.h264').read_bytes()
    samples=[];errors=0;seen_keyframe=False;matched_frames=0
    with (directory/'packets.h264').open('rb') as raw:
        for line in (directory/'packets.jsonl').read_text().splitlines():
            row=json.loads(line);raw.seek(row['offset']);payload=raw.read(row['bytes'])
            if len(payload)!=row['bytes']: raise ValueError('Truncated packet recording')
            packet=av.Packet(headers+payload);headers=b''
            packet.pts=row['tag'];packet.dts=row['tag']
            try:
                decoded=codec.decode(packet)
            except av.error.FFmpegError:
                errors+=1;continue
            for frame in decoded:
                seen_keyframe=seen_keyframe or frame.key_frame
                if not seen_keyframe or frame.pts not in frames: continue
                matched_frames+=1
                gray=frame.to_ndarray(format='gray')
                small=cv2.resize(gray,(gray.shape[1]//2,gray.shape[0]//2),interpolation=cv2.INTER_AREA)
                corners,ids,_=detector.detectMarkers(small)
                if ids is None: continue
                # The live preview may itself contain a delayed image of the
                # target. Prefer the largest marker to avoid picture-in-picture.
                chosen=max(range(len(corners)),key=lambda i:cv2.contourArea(corners[i].reshape(-1,2)))
                for code in [ids.flatten()[chosen]]:
                    if int(code) not in issued: continue
                    start=issued[int(code)];end=frames[frame.pts]['t_ready']
                    if not 0<end-start<10: continue
                    samples.append(dict(packet_tag=frame.pts,marker=int(code),
                        t_submit=start,t_frame_ready=end,delay_ms=(end-start)*1000))
                    if len(samples) in (1,20,80):
                        cv2.imwrite(str(directory/f'measured_{len(samples):03d}.png'),frame.to_ndarray(format='bgr24'))
    result=dict(sample_count=len(samples),matched_frames_after_keyframe=matched_frames,
        replay_errors_before_or_after_keyframe=errors,samples=samples,
        definition='Screen pattern software submission to BGR frame ready in a separate receive/decode process',
        limitations=['Source screen presentation/scanout is not independently measured.',
                     'Pattern hold duration contributes sampling uncertainty.',
                     'Receiver screen scanout is excluded; this is not photon-to-photon latency.',
                     'Synthetic PTS tags associate frames only; they are not camera timestamps.'])
    if samples:
        values=[x['delay_ms'] for x in samples]
        result['latency_ms']={key:float(np.percentile(values,q)) for key,q in
            [('min',0),('p10',10),('p50',50),('p95',95),('max',100)]}
    if len(patterns)>1:
        gaps=np.diff([x['t_submit'] for x in patterns])*1000
        result['pattern_update_ms']={key:float(np.percentile(gaps,q)) for key,q in [('p50',50),('p95',95),('max',100)]}
    result['enough_samples_for_preliminary_summary']=len(samples)>=20
    (directory/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory')
    analyze(parser.parse_args().directory)
