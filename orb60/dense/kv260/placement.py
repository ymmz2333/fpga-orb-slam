"""Inspect compiled XIR graph; fail closed on unintended CPU neural kernels."""
from .common import digest,save
from .preflight import fingerprints as read_fingerprints

CPU_ALLOWED={'data','const','fix','float2fix','fix2float','resize','upsample','reshape','transpose','concat','identity','upload','download'}

def validate_placement(subgraphs,approved_extra_ops=None):
    if not subgraphs or not any(s['device']=='DPU' for s in subgraphs):raise ValueError('No DPU subgraph')
    illegal=[];conv_count=0
    approved={(o['name'],o['type']) for o in (approved_extra_ops or [])};used=set()
    if any(kind!='relu' for _,kind in approved):raise ValueError('Only explicitly reviewed ReLU boundaries are supported by this policy')
    for s in subgraphs:
        if s['device'] not in {'DPU','CPU','USER'}:raise ValueError('Unknown subgraph device')
        for op in s['ops']:
            kind=op['type'].lower();kind=kind[:-4] if kind.endswith('-fix') else kind
            if 'conv' in op['type'].lower():
                conv_count+=1
                if s['device']!='DPU':illegal.append(op)
            if s['device']!='DPU' and kind not in CPU_ALLOWED:
                identity=(op['name'],op['type'])
                if identity in approved:used.add(identity)
                else:illegal.append(op)
    if illegal:raise ValueError('Disallowed CPU operations: '+str(illegal))
    if conv_count<1:raise ValueError('No convolution found in compiled graph')
    if used!=approved:raise ValueError('PS operator policy does not exactly match compiled extras')
    return {'dpu_subgraphs':sum(s['device']=='DPU' for s in subgraphs),'convolutions':conv_count,
            'ps_operations':[o for s in subgraphs if s['device']!='DPU' for o in s['ops']]}

def inspect_xmodel(model,output,source=None,family='midas',ps_policy=None):
    import xir
    graph=xir.Graph.deserialize(str(model));root=graph.get_root_subgraph()
    def children(s):return [s] if s.is_leaf else list(s.toposort_child_subgraph())
    groups=[];fingerprints=read_fingerprints(root.get_attrs());resizes=[];target_names=set();dpu_attrs=[]
    for s in children(root):
        attrs=s.get_attrs();fingerprints.update(read_fingerprints(attrs))
        dpu_attrs.append({'subgraph':s.get_name(),'attrs':{k:v for k,v in attrs.items() if 'fingerprint' in k or k in {'dpu_name','device','target','runner'}}})
        if s.has_attr('dpu_name'):target_names.add(str(s.get_attr('dpu_name')))
        for op in s.get_ops():
            if any(k in op.get_type().lower() for k in ['resize','upsample']):
                attrs=op.get_attrs()
                resizes.append({'name':op.get_name(),'type':op.get_type(),
                                'align_corners':attrs.get('align_corners'),'half_pixel_centers':attrs.get('half_pixel_centers'),
                                'mode':attrs.get('mode'),'scale':attrs.get('scale'),
                                'device':str(s.get_attr('device')) if s.has_attr('device') else 'USER'})
        groups.append({'name':s.get_name(),'device':str(s.get_attr('device')).upper() if s.has_attr('device') else 'USER',
                       'ops':[{'name':o.get_name(),'type':o.get_type()} for o in sorted(s.get_ops(),key=lambda x:x.get_name())]})
    record={'status':'PLACEMENT_REVIEW','model_sha256':digest(model),'subgraphs':groups,'fingerprints':sorted(fingerprints),'dpu_attrs':dpu_attrs,
            'target_names':sorted(target_names),'resize_semantics':resizes,'hardware_inference_verified':False}
    save(output,record)
    approved=None
    if ps_policy:
        if ps_policy.get('model_sha256')!=digest(model) or not source or ps_policy.get('source_model_sha256')!=digest(source):raise ValueError('PS policy belongs to another model')
        approved=ps_policy['approved_extra_ops']
    try:result=validate_placement(groups,approved)
    except Exception as e:
        save(output,{**record,'status':'PLACEMENT_FAILED','error':str(e)});raise
    if not fingerprints:raise ValueError('Compiled graph has no DPU fingerprint')
    source_resizes=[]
    if source:
        source_graph=xir.Graph.deserialize(str(source))
        for op in source_graph.get_root_subgraph().get_ops():
            if any(k in op.get_type().lower() for k in ['resize','upsample']):
                attrs=op.get_attrs();source_resizes.append({'name':op.get_name(),'mode':attrs.get('mode'),'align_corners':attrs.get('align_corners'),
                                                           'half_pixel_centers':attrs.get('half_pixel_centers')})
        if family=='midas' and (len(source_resizes)!=5 or sum(x['align_corners'] is True for x in source_resizes)!=4 or sum(x['half_pixel_centers'] is True for x in source_resizes)!=1):
            raise ValueError('Source XIR Resize semantics differ from frozen model')
        if family=='fastdepth' and (len(source_resizes)!=5 or any(x['mode']!='NEAREST' or x['align_corners'] is True or x['half_pixel_centers'] is True for x in source_resizes)):
            raise ValueError('FastDepth must retain five nearest/asymmetric upsampling operations')
    lowered=family=='midas' and bool(source_resizes) and len(resizes)==4 and all(x['align_corners'] is True for x in resizes)
    if family=='midas' and not lowered and (len(resizes)!=5 or sum(x['align_corners'] is True for x in resizes)!=4):
        raise ValueError('Compiled Resize semantics require explicit review')
    for op in resizes:
        if family=='fastdepth':
            if op['mode']!='NEAREST' or op['align_corners'] is True or op['half_pixel_centers'] is True:raise ValueError('FastDepth compiled upsample semantics changed')
            continue
        if op['align_corners'] is True and op['half_pixel_centers'] not in {False,0}:
            raise ValueError('align_corners Resize has ambiguous half-pixel behavior')
        if op['align_corners'] is not True and op['half_pixel_centers'] is not True:
            raise ValueError('Final Resize must preserve half_pixel coordinates')
    save(output,{'status':'COMPILE_PLACEMENT_PASS','model_sha256':digest(model),'subgraphs':groups,**result,
                 'hardware_inference_verified':False,'fingerprints':sorted(fingerprints),'target_names':sorted(target_names),'resize_semantics':resizes,
                 'source_resize_semantics':source_resizes,'final_half_pixel_resize_lowered_into_dpu':lowered,
                 'compiler_lowering_numerical_gate':'BOARD_REQUIRED','explicit_ps_operator_policy':ps_policy})
    return result
