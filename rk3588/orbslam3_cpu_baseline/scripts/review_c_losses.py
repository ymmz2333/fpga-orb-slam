"""Build bounded contact sheets; apply explicit human observations to all losses."""
import argparse,csv,json,os,pathlib
from PIL import Image,ImageDraw,ImageFont

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=pathlib.Path,required=True)
    a=p.parse_args(); out=a.report/'loss_review';out.mkdir(exist_ok=True)
    font=ImageFont.truetype(str(pathlib.Path(os.environ['WINDIR'])/'Fonts/msyh.ttc'),16)
    contexts=sorted((a.report/'loss_images').glob('*/*/context.json')); rows=[]
    for start in range(0,len(contexts),6):
        selected=contexts[start:start+6]; sheet=Image.new('RGB',(960,284*len(selected)),'white');draw=ImageDraw.Draw(sheet)
        for k,path in enumerate(selected):
            c=json.loads(path.read_text(encoding='utf-8'));loss=c['loss'];frames=c['frames']
            before=min(frames,key=lambda f:abs(int(f['frame_index'])-(int(loss['start_frame'])-1)))
            onset=min(frames,key=lambda f:abs(int(f['frame_index'])-int(loss['start_frame'])))
            end=min(frames,key=lambda f:abs(int(f['frame_index'])-(int(loss['end_frame'])+1)))
            label=f"{start+k+1:02d} {path.parent.parent.name} / {path.parent.name} {float(loss['start_s']):.2f}–{float(loss['end_s']):.2f}s"
            draw.text((4,k*284),label,font=font,fill='black')
            for j,f in enumerate((before,onset,end)):
                im=Image.open(path.parent/f['output_image']).convert('RGB');im.thumbnail((320,240))
                sheet.paste(im,(j*320,k*284+24));draw.text((j*320+3,k*284+264),f"frame {f['frame_index']} | corrupt={f['corrupt']}",font=font,fill='black')
            rows.append(dict(review_id=start+k+1,run=path.parent.parent.name,segment=loss['segment'],start_s=loss['start_s'],end_s=loss['end_s'],duration_s=loss['duration_s'],recovered=loss['recovered'],same_map=loss['same_map'],actual_relocalization=loss['actual_relocalization'],context=str(path.relative_to(a.report)).replace('\\','/'),observation='',interpretation=''))
        sheet.save(out/f'contacts_{start//6+1:02d}.jpg',quality=92)
    target=out/'observations.csv'
    if not target.exists():
        with target.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    with target.open(encoding='utf-8',newline='') as f: annotations=list(csv.DictReader(f))
    for r in annotations:
        if not r['observation']:continue
        path=a.report/r['context'];c=json.loads(path.read_text(encoding='utf-8'))
        c['visual_cause']={'observation':r['observation'],'possible_factors':r['interpretation'],'method':'人工审阅丢失前、首个非OK帧、恢复或末尾帧；图像不能证明唯一原因'}
        path.write_text(json.dumps(c,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'LOSS_REVIEW segments={len(rows)} annotated={sum(bool(r["observation"]) for r in annotations)} sheets={(len(rows)+5)//6}')
if __name__=='__main__':main()
