"""Copy loss-boundary PNGs without altering prepared images or the original bitstream."""
import argparse,json,pathlib,shutil
from analyze_c import read
def main():
    p=argparse.ArgumentParser(); p.add_argument('--report',type=pathlib.Path,required=True)
    p.add_argument('--datasets',type=pathlib.Path,required=True); a=p.parse_args()
    state=json.loads((a.report/'batch_state.json').read_text(encoding='utf-8'))
    for item in state['schedule']:
        folder=a.report/'raw'/item['folder']; path=folder/'loss_segments.csv'
        if not path.exists(): continue
        dataset=a.datasets/item['dataset']; frames=read(dataset/'frames.csv')
        for loss in read(path):
            output=a.report/'loss_images'/item['folder']/('segment_'+loss['segment']); output.mkdir(parents=True,exist_ok=True)
            indexes=set()
            for center in (int(loss['start_frame']),int(loss['end_frame'])+1): indexes.update(range(max(0,center-2),min(len(frames),center+3)))
            selected=[]
            for index in sorted(indexes):
                row=frames[index]; dest=output/('frame_%06d_%s.png'%(index,row['timestamp_ns']))
                shutil.copy2(dataset/row['image'],dest); selected.append(dict(row,output_image=dest.name))
            (output/'context.json').write_text(json.dumps(dict(loss=loss,frames=selected,visual_cause='未完成：等待人工图像审阅'),indent=2,ensure_ascii=False),encoding='utf-8')
    print('C_LOSS_BOUNDARY_IMAGES_EXPORTED')
if __name__=='__main__': main()
