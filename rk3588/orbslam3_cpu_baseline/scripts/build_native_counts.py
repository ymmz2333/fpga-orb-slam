"""Compile the isolated read-only extractor counter against actual G1 headers."""
import hashlib,json,pathlib,re,shlex,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
old=PROJECT/'.work/golden/slam_source';out=PROJECT/'.work/golden_h2/native_counts';out.mkdir(parents=True,exist_ok=False)
flags=(old/'build/CMakeFiles/ORB_SLAM3.dir/flags.make').read_text();args=[]
for key in ['CXX_FLAGS','CXX_DEFINES','CXX_INCLUDES']:args+=shlex.split(re.search(r'^'+key+r' = (.*)$',flags,re.M)[1])
prefix=PROJECT/'.work/golden/opencv-install/lib';source=ROOT/'scripts/native_selected_counts.cpp'
command=['g++',*args,str(source),'-o',str(out/'native_selected_counts'),'-L'+str(old/'lib'),'-lORB_SLAM3','-L'+str(prefix),'-lopencv_imgcodecs','-lopencv_core','-Wl,-rpath,'+str(old/'lib')+':'+str(prefix),'-Wl,-rpath-link,'+str(prefix)]
with (out/'build.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
(out/'build.json').write_text(json.dumps(dict(command=command,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),binary_sha256=hashlib.sha256((out/'native_selected_counts').read_bytes()).hexdigest()),indent=2))
print('NATIVE_COUNT_BUILD_PASS')
