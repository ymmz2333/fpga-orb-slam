"""Port three vendor diagnostic MD5 calls to OpenSSL 3 EVP; tensor code is unchanged."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

FILES={
    'cpu_task/ops/data-fix/data-fix.cpp':'8ba811e7d57a2cbda6dd23efb2940725638b6cf8d649a279b26cf410d18d32ce',
    'cpu_task/ops/data/data.cpp':'f80208a9ef8c5f84af57e659ea3d999b1303bccace35988f570906440f716525',
    'usefultools/src/xmodel_to_txt.cpp':'d021db16147e4c5200d471df6e3b3f35f894fc8a92ec321d34f9b2188acd0ac8',
}
INCLUDE='#include <openssl/md5.h>\n#include <openssl/evp.h>'


def replacements(name):
    source='val.data(), val.size()' if name.startswith('usefultools/') else 'val, size'
    before='  MD5((const unsigned char*)&val[0], val.size(), (unsigned char*)&result[0]);' if name.startswith('usefultools/') else '  MD5(val, size, (unsigned char*)&result[0]);'
    after='''  // OpenSSL 3 diagnostic digest API; exact MD5 bytes are retained.
  unsigned int digest_size = 0;
  CHECK_EQ(EVP_Digest('''+source+''', result.data(), &digest_size,
                      EVP_md5(), nullptr), 1);
  CHECK_EQ(digest_size, static_cast<unsigned int>(result.size()));'''
    return before,after


def main():
    source=Path(sys.argv[1])/'src/Vitis-AI-Library';run=Path(sys.argv[2]);run.mkdir(parents=True,exist_ok=True)
    prepared=[]
    for name,expected in FILES.items():
        path=source/name;text=path.read_text(encoding='utf-8');before,after=replacements(name)
        original=text.replace(INCLUDE,'#include <openssl/md5.h>',1).replace(after,before,1)
        if hashlib.sha256(original.encode()).hexdigest()!=expected:raise ValueError('Vendor source changed: '+name)
        if original.count(before)!=1:raise ValueError('Diagnostic call differs: '+name)
        patched=original.replace('#include <openssl/md5.h>',INCLUDE,1).replace(before,after,1)
        prepared.append((name,path,expected,patched))
    records=[]
    for index,(name,path,expected,patched) in enumerate(prepared):
        path.write_text(patched,encoding='utf-8')
        # Compile the actual modified helper, then compare its bytes with hashlib.
        helper=re.search(r'static std::string md5sum\([\s\S]*?\n}',patched).group()
        argument='value' if name.startswith('usefultools/') else 'reinterpret_cast<const unsigned char*>(value.data()), value.size()'
        program='\n'.join('#include <'+h+'>' for h in ('openssl/md5.h','openssl/evp.h','glog/logging.h','string','vector','sstream','iomanip','iostream'))
        program+='\n'+helper+'\nint main(){ for(size_t n : {0u,3u,256u,65537u}) {std::string value(n,0); for(size_t i=0;i<n;++i)value[i]=static_cast<char>(i%256);std::cout<<md5sum('+argument+')<<"\\n";} }\n'
        cpp=run/f'digest_{index}.cpp';binary=run/f'digest_{index}'
        cpp.write_text(program,encoding='utf-8')
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-lcrypto','-lglog','-o',str(binary)],check=True,timeout=60)
        values=subprocess.check_output([str(binary)],text=True,timeout=10).splitlines()
        wanted=[hashlib.md5(bytes(i%256 for i in range(n))).hexdigest() for n in (0,3,256,65537)]
        if values!=wanted:raise ValueError('Diagnostic digest changed: '+name)
        records.append({'file':name,'before_sha256':expected,'after_sha256':hashlib.sha256(patched.encode()).hexdigest(),'native_digest_cases':len(values)})
    (run/'provenance.json').write_text(json.dumps({'status':'OPENSSL3_DIAGNOSTIC_DIGEST_EQUIVALENCE_PASS','tensor_operators_changed':False,'files':records},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
