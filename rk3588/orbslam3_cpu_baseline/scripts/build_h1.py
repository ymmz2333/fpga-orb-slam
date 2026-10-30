"""Isolated O3 H1 builds: retain original G1 objects/binaries, record every input."""
import argparse,concurrent.futures,difflib,hashlib,json,pathlib,re,shlex,shutil,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
HEADER=r'''#pragma once
#include <cstdlib>
#include <fstream>
#include <cstdint>
#include <opencv2/features2d.hpp>
#include <vector>
#include <set>
#include <algorithm>
#include <cmath>
namespace ORB_SLAM3 { namespace RelocDiagnostic {
struct Sink {
    std::ofstream stream; unsigned long frame=0;
    Sink(){const char* p=std::getenv("ORB_RELOC_DIAGNOSTICS"); if(p){stream.open(p);stream<<"frame_id,event,solver,outer_round,call_iteration,total_iteration,max_iterations,bNoMore,solver_inliers,refined_inliers,pose_inliers,matched\n";stream.flush();}}
};
inline Sink& sink(){static Sink s;return s;}
inline void frame(unsigned long n){sink().frame=n;}
inline void event(const char* stage,const void* solver,int outer,int local,int total,int maximum,int noMore,int inliers,int refined,int good,int matched){
    Sink& s=sink(); if(!s.stream.is_open())return;
    s.stream<<s.frame<<','<<stage<<','<<reinterpret_cast<uintptr_t>(solver)<<','<<outer<<','<<local<<','<<total<<','<<maximum<<','<<noMore<<','<<inliers<<','<<refined<<','<<good<<','<<matched<<'\n';s.stream.flush();
}
inline void selected(uint64_t ns,int role,int width,int height,int requested,float scaleFactor,const std::vector<float>& scales,const std::vector<cv::KeyPoint>& keys){
    static const char* path=std::getenv("ORB_SELECTED_STATS");if(!path)return;
    static std::ofstream f(path);static bool header=false;
    if(!header){f<<"timestamp_ns,role,level,width,height,native_formula_budget,selected,virtual_grid_cells,virtual_empty_cells\n";header=true;}
    std::vector<int> budgets(scales.size());float factor=1.0f/scaleFactor;
    float desired=requested*(1-factor)/(1-std::pow(factor,int(scales.size())));int used=0;
    for(size_t i=0;i+1<scales.size();++i){budgets[i]=cvRound(desired);used+=budgets[i];desired*=factor;}
    budgets.back()=std::max(0,requested-used);
    for(size_t l=0;l<budgets.size();++l){
        const int w=cvRound(width/scales[l]),h=cvRound(height/scales[l]),ew=w-32,eh=h-32,b=budgets[l];
        int side=1,cols=0,rows=0;if(b>0&&ew>0&&eh>0){side=std::max(1,int(std::sqrt(double(ew)*eh/b)));cols=std::max(1,ew/side);rows=std::max(1,eh/side);}
        size_t count=0;std::set<int> occupied;
        for(const auto& k:keys)if(k.octave==int(l)){
            ++count;if(cols&&rows){int x=cvRound(k.pt.x/scales[l])-16,y=cvRound(k.pt.y/scales[l])-16;
                x=std::max(0,std::min(cols-1,x/side));y=std::max(0,std::min(rows-1,y/side));occupied.insert(y*cols+x);}
        }
        f<<ns<<','<<role<<','<<l<<','<<w<<','<<h<<','<<b<<','<<count<<','<<cols*rows<<','<<(cols*rows-int(occupied.size()))<<'\n';
    }f.flush();
}
}}
'''
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def one(text,a,b):
    if text.count(a)!=1:raise ValueError('Patch anchor not unique: '+a[:90])
    return text.replace(a,b,1)
def instrument(name,text,fixed):
    text=one(text,'#include "'+('Tracking.h' if name=='Tracking.cc' else 'MLPnPsolver.h')+'"',
        '#include "'+('Tracking.h' if name=='Tracking.cc' else 'MLPnPsolver.h')+'"\n#include "RelocDiagnostic.h"')
    if name=='Tracking.cc':
        text=one(text,'    while(nCandidates>0 && !bMatch)',
            '    int diagnosticRound=0;\n    RelocDiagnostic::frame(mCurrentFrame.mnId);\n    while(nCandidates>0 && !bMatch)')
        text=one(text,'    while(nCandidates>0 && !bMatch)\n    {',
            '    while(nCandidates>0 && !bMatch)\n    {\n        ++diagnosticRound;')
        anchor='            bool bTcw = pSolver->iterate(5,bNoMore,vbInliers,nInliers, eigTcw);'
        text=one(text,anchor,anchor+'\n            RelocDiagnostic::event("outer_solver",pSolver,diagnosticRound,5,-1,-1,bNoMore,nInliers,-1,-1,bTcw);')
        anchor='                int nGood = Optimizer::PoseOptimization(&mCurrentFrame);'
        text=one(text,anchor,anchor+'\n                RelocDiagnostic::event("pose_optimization",pSolver,diagnosticRound,-1,-1,-1,bNoMore,nInliers,-1,nGood,bMatch);')
        anchor='                // If the pose is supported by enough inliers stop ransacs and continue'
        text=one(text,anchor,'                RelocDiagnostic::event("outer_final",pSolver,diagnosticRound,-1,-1,-1,bNoMore,nInliers,-1,nGood,bMatch);\n'+anchor)
    else:
        anchor='\t        mnIterations++;'
        text=one(text,anchor,anchor+'\n            RelocDiagnostic::event("inner_begin",this,-1,nCurrentIterations,mnIterations,mRansacMaxIts,bNoMore,mnInliersi,-1,-1,0);')
        anchor='\t        CheckInliers();'
        text=one(text,anchor,anchor+'\n            RelocDiagnostic::event("inner_inliers",this,-1,nCurrentIterations,mnIterations,mRansacMaxIts,bNoMore,mnInliersi,-1,-1,0);')
        anchor='\t                Tout = mRefinedTcw;\n\t                return true;'
        replacement='\t                Tout = mRefinedTcw;\n'
        if fixed:replacement+='                // Exhaustion must be propagated even when refinement returns a pose.\n                bNoMore = mnIterations >= mRansacMaxIts;\n'
        replacement+='                RelocDiagnostic::event("refine_return",this,-1,nCurrentIterations,mnIterations,mRansacMaxIts,bNoMore,mnInliersi,mnRefinedInliers,-1,1);\n\t                return true;'
        text=one(text,anchor,replacement)
    return text
def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['diagnostic','fixed'],required=True);p.add_argument('--build-name');a=p.parse_args()
    if a.build_name and not re.fullmatch('[A-Za-z0-9_-]+',a.build_name):raise ValueError('Unsafe build name')
    old=PROJECT/'.work/golden/slam_source';base=PROJECT/'.work/golden_h1'/(a.build_name or a.mode)
    if a.mode=='fixed':
        evidence=json.loads((PROJECT/'orb_frontend_golden/decision/H1_counter_probe_20261006_01/diagnosis.json').read_text())
        if evidence['status']!='CONFIRMED':raise ValueError('Counter data did not confirm the unbounded retry hypothesis; stop before fixing')
    out=base/'slam_source';out.mkdir(parents=True,exist_ok=False)
    (out/'src').mkdir();(out/'include').mkdir();(out/'lib').mkdir();(out/'Examples/Monocular').mkdir(parents=True)
    (base/'opencv-install').symlink_to(PROJECT/'.work/golden/opencv-install',target_is_directory=True)
    header=out/'include/RelocDiagnostic.h';header.write_text(HEADER)
    provenance={'mode':a.mode,'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
        'old_binary_sha256':sha(old/'Examples/Monocular/mono_euroc'),'old_library_sha256':sha(old/'lib/libORB_SLAM3.so'),
        'modified_sources':{},'reused_objects':{},'commands':[]}
    patches=[]
    for name in ['Tracking.cc','MLPnPsolver.cpp']:
        original=(old/'src'/name).read_text();new=instrument(name,original,a.mode=='fixed');path=out/'src'/name;path.write_text(new)
        provenance['modified_sources'][name]=sha(path)
        patches+=list(difflib.unified_diff(original.splitlines(True),new.splitlines(True),fromfile='a/src/'+name,tofile='b/src/'+name))
    names=['Tracking.cc','MLPnPsolver.cpp']
    if a.mode=='fixed':
        names.append('FeatureIO.cc');original=(old/'src/FeatureIO.cc').read_text()
        new=one(original,'#include "FeatureIO.h"','#include "FeatureIO.h"\n#include "RelocDiagnostic.h"')
        new=one(new,'    stats.count=keys.size(); return mono_left;',
            '    RelocDiagnostic::selected(stats.timestamp_ns,role,image.cols,image.rows,extractor->GetFeatures(),extractor->GetScaleFactor(),extractor->GetScaleFactors(),keys);\n    stats.count=keys.size(); return mono_left;')
        (out/'src/FeatureIO.cc').write_text(new);provenance['modified_sources']['FeatureIO.cc']=sha(out/'src/FeatureIO.cc')
        observation=''.join(difflib.unified_diff(original.splitlines(True),new.splitlines(True),fromfile='a/src/FeatureIO.cc',tofile='b/src/FeatureIO.cc'))
        (ROOT/'patches/0015-selected-feature-observability.patch').write_text(observation)
        before=instrument('MLPnPsolver.cpp',(old/'src/MLPnPsolver.cpp').read_text(),False)
        after=instrument('MLPnPsolver.cpp',(old/'src/MLPnPsolver.cpp').read_text(),True)
        (ROOT/'patches/0014-relocation-exhaustion.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/src/MLPnPsolver.cpp',tofile='b/src/MLPnPsolver.cpp')))
    patch=ROOT/'patches'/('0013-relocation-counters.patch' if a.mode=='diagnostic' else '0014-relocation-exhaustion-with-counters.patch')
    # Patched source is always reconstructed from the original G1 source, never a previous modified tree.
    patches+=list(difflib.unified_diff([],HEADER.splitlines(True),fromfile='/dev/null',tofile='b/include/RelocDiagnostic.h'))
    patch.write_text(''.join(patches));(out/'source.patch').write_text(''.join(patches))
    (out/'RelocDiagnostic.h').write_text(HEADER)
    (ROOT/'patches/RelocDiagnostic.h').write_text(HEADER)
    flags=(old/'build/CMakeFiles/ORB_SLAM3.dir/flags.make').read_text()
    arguments=[]
    for key in ['CXX_FLAGS','CXX_DEFINES','CXX_INCLUDES']:
        arguments+=shlex.split(re.search(r'^'+key+r' = (.*)$',flags,re.M)[1])
    assert '-O3' in arguments and '-std=c++14' in arguments and '-march=native' in arguments
    def compile(name):
        cmd=['/usr/bin/c++','-I'+str(out/'include'),*arguments,'-c',str(out/'src'/name),'-o',str(out/(name+'.o'))]
        with (out/(name+'.build.log')).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        return cmd
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:provenance['commands']+=list(pool.map(compile,names))
    def link(target,dest):
        command=shlex.split((old/'build/CMakeFiles'/target/'link.txt').read_text())
        for i,t in enumerate(command):
            if t.startswith('CMakeFiles/') or t.startswith('../'):command[i]=str((old/'build'/t).resolve())
            if '/CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o' in command[i]:command[i]=str(out/'Tracking.cc.o')
            if '/CMakeFiles/ORB_SLAM3.dir/src/MLPnPsolver.cpp.o' in command[i]:command[i]=str(out/'MLPnPsolver.cpp.o')
            if a.mode=='fixed' and '/CMakeFiles/ORB_SLAM3.dir/src/FeatureIO.cc.o' in command[i]:command[i]=str(out/'FeatureIO.cc.o')
            if command[i].endswith('.o') and not command[i].startswith(str(out)):provenance['reused_objects'][command[i]]=sha(pathlib.Path(command[i]))
            if command[i]==str(old/'lib/libORB_SLAM3.so'):command[i]=str(out/'lib/libORB_SLAM3.so')
            if command[i].startswith('-Wl,-rpath,'):command[i]=command[i].replace(str(old/'lib'),str(out/'lib'))
        command[command.index('-o')+1]=str(dest)
        with (out/(target+'.link.log')).open('w') as log:subprocess.run(command,cwd=old/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        provenance['commands'].append(command)
    link('ORB_SLAM3.dir',out/'lib/libORB_SLAM3.so');link('mono_euroc.dir',out/'Examples/Monocular/mono_euroc')
    provenance['new_binary_sha256']=sha(out/'Examples/Monocular/mono_euroc');provenance['new_library_sha256']=sha(out/'lib/libORB_SLAM3.so')
    (out/'build_manifest.json').write_text(json.dumps(provenance,indent=2));print('H1_ISOLATED_BUILD_PASS',a.mode,flush=True)
if __name__=='__main__':main()
