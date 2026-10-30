#pragma once
// Original, portable bridge framing/hash utilities. No dependency on generated RTL.
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <unistd.h>
#include <cerrno>
#endif

namespace demo {
constexpr const char *profile="ORB60-A32-4PPC-150MHZ-V1";
constexpr uint32_t max_body=32*1024*1024,image_bytes=960*720;
enum Kind:uint32_t {Hello=1,Frame=2,Ack=3,End=4,Control=5,Status=6,MapBegin=7,MapFile=8,MapCommit=9,Error=10,Color=11};
constexpr uint32_t color_expected=1;
inline uint32_t get32(const uint8_t*p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
inline uint64_t get64(const uint8_t*p){return get32(p)|(uint64_t(get32(p+4))<<32);}
inline void put32(uint8_t*p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=uint8_t(v>>(i*8));}
inline void put64(uint8_t*p,uint64_t v){put32(p,uint32_t(v));put32(p+4,uint32_t(v>>32));}
inline uint32_t crc32(const uint8_t*p,size_t n){
    static const auto table=[](){std::array<std::array<uint32_t,256>,8>t{};for(unsigned v=0;v<256;v++){
        uint32_t x=v;for(unsigned b=0;b<8;b++)x=(x>>1)^((0u-(x&1))&0xedb88320u);t[0][v]=x;}
        for(unsigned i=1;i<8;i++)for(unsigned v=0;v<256;v++){uint32_t x=t[i-1][v];t[i][v]=(x>>8)^t[0][x&255];}return t;}();
    uint32_t c=~0u;while(n>=8){uint32_t a=c^get32(p),b=get32(p+4);
        c=table[7][a&255]^table[6][(a>>8)&255]^table[5][(a>>16)&255]^table[4][a>>24]
         ^table[3][b&255]^table[2][(b>>8)&255]^table[1][(b>>16)&255]^table[0][b>>24];p+=8;n-=8;}
    while(n--)c=(c>>8)^table[0][(c^*p++)&255];return ~c;
}
inline std::string sha256(const std::vector<uint8_t>&input){
    static constexpr uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
    0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
    0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    auto rr=[](uint32_t v,unsigned b){return (v>>b)|(v<<(32-b));};auto data=input;uint64_t bits=uint64_t(data.size())*8;
    data.push_back(128);while(data.size()%64!=56)data.push_back(0);for(int i=7;i>=0;i--)data.push_back(uint8_t(bits>>(8*i)));
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    for(size_t off=0;off<data.size();off+=64){uint32_t w[64];for(unsigned i=0;i<16;i++){w[i]=0;for(unsigned j=0;j<4;j++)w[i]=(w[i]<<8)|data[off+4*i+j];}
        for(unsigned i=16;i<64;i++)w[i]=w[i-16]+(rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10));
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],q=h[7];for(unsigned i=0;i<64;i++){
            uint32_t t=q+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^(~e&g))+k[i]+w[i];uint32_t u=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c));
            q=g;g=f;f=e;e=d+t;d=c;c=b;b=a;a=t+u;}uint32_t v[8]={a,b,c,d,e,f,g,q};for(unsigned i=0;i<8;i++)h[i]+=v[i];}
    std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto v:h)out<<std::setw(8)<<v;return out.str();
}
inline std::vector<uint8_t> bytes(const std::string&s){return {s.begin(),s.end()};}
inline std::string string(const std::vector<uint8_t>&v){return {v.begin(),v.end()};}
inline std::vector<uint8_t> readFile(const std::string&path,size_t bound=max_body){std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f)throw std::runtime_error("Cannot open "+path);auto n=f.tellg();if(n<0||uint64_t(n)>bound)throw std::runtime_error("File size exceeds bound");
    std::vector<uint8_t>v(static_cast<size_t>(n));f.seekg(0);if(n&&!f.read(reinterpret_cast<char*>(v.data()),n))throw std::runtime_error("File read failed");return v;}
struct Packet {
    uint32_t kind=Status;uint64_t session=0,frame=0,stamp=0;uint32_t count=0,aux=0,flags=0;std::vector<uint8_t> body;
    std::array<uint8_t,64> header()const{if(body.size()>max_body)throw std::runtime_error("Packet too large");std::array<uint8_t,64>h{};
        std::memcpy(h.data(),"ORB2DEMO",8);put32(h.data()+8,1);put32(h.data()+12,kind);put64(h.data()+16,session);put64(h.data()+24,frame);put64(h.data()+32,stamp);
        put32(h.data()+40,uint32_t(body.size()));put32(h.data()+44,count);put32(h.data()+48,aux);put32(h.data()+52,crc32(body.data(),body.size()));put32(h.data()+56,flags);return h;}
    static Packet parse(const std::array<uint8_t,64>&h){if(std::memcmp(h.data(),"ORB2DEMO",8)||get32(h.data()+8)!=1||get32(h.data()+60))throw std::runtime_error("Bridge ABI mismatch");
        Packet p;p.kind=get32(h.data()+12);if(p.kind<Hello||p.kind>Color||get32(h.data()+40)>max_body)throw std::runtime_error("Invalid packet bound/kind");
        p.session=get64(h.data()+16);p.frame=get64(h.data()+24);p.stamp=get64(h.data()+32);p.count=get32(h.data()+44);p.aux=get32(h.data()+48);p.flags=get32(h.data()+56);p.body.resize(get32(h.data()+40));return p;}
};
#if defined(_WIN32)
using Socket=SOCKET;constexpr Socket invalid_socket=INVALID_SOCKET;
inline void closeSocket(Socket s){closesocket(s);}inline void socketInit(){static bool ready=[](){WSADATA w;return WSAStartup(MAKEWORD(2,2),&w)==0;}();if(!ready)throw std::runtime_error("WSAStartup failed");}
#else
using Socket=int;constexpr Socket invalid_socket=-1;
inline void closeSocket(Socket s){::close(s);}inline void socketInit(){}
#endif
struct Connection {
    Socket fd=invalid_socket;
    explicit Connection(Socket s=invalid_socket):fd(s){if(s!=invalid_socket){int yes=1;setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&yes),sizeof(yes));}}
    ~Connection(){if(fd!=invalid_socket)closeSocket(fd);}Connection(const Connection&)=delete;Connection&operator=(const Connection&)=delete;
    Connection(Connection&&o)noexcept:fd(o.fd){o.fd=invalid_socket;}
    void transfer(uint8_t*p,size_t n,bool sending){while(n){int k;
#if defined(_WIN32)
        k=sending ? ::send(fd,reinterpret_cast<const char*>(p),int(n),0) : ::recv(fd,reinterpret_cast<char*>(p),int(n),0);
#else
        k=int(sending ? ::send(fd,p,n,MSG_NOSIGNAL) : ::recv(fd,p,n,0));if(k<0&&errno==EINTR)continue;
#endif
        if(k<=0)throw std::runtime_error("Bridge socket timeout/disconnected");p+=k;n-=size_t(k);}}
    Packet receive(){std::array<uint8_t,64>h;transfer(h.data(),h.size(),false);auto p=Packet::parse(h);transfer(p.body.data(),p.body.size(),false);
        if(crc32(p.body.data(),p.body.size())!=get32(h.data()+52))throw std::runtime_error("Bridge CRC mismatch");return p;}
    void send(const Packet&p){auto h=p.header();transfer(h.data(),h.size(),true);transfer(const_cast<uint8_t*>(p.body.data()),p.body.size(),true);}
    void timeout(unsigned seconds){
#if defined(_WIN32)
        DWORD v=seconds*1000;setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<const char*>(&v),sizeof(v));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,reinterpret_cast<const char*>(&v),sizeof(v));
#else
        timeval v{long(seconds),0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&v,sizeof(v));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&v,sizeof(v));
#endif
    }
};
inline Socket listenSocket(unsigned port){socketInit();Socket s=::socket(AF_INET,SOCK_STREAM,0);if(s==invalid_socket)throw std::runtime_error("socket failed");int yes=1;
    setsockopt(s,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&yes),sizeof(yes));sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(uint16_t(port));addr.sin_addr.s_addr=htonl(INADDR_ANY);
    if(::bind(s,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))||::listen(s,2)){closeSocket(s);throw std::runtime_error("Bridge port bind/listen failed");}return s;}
inline Packet response(uint32_t kind,const std::string&s){Packet p;p.kind=kind;p.body=bytes(s);return p;}
inline std::string jsonQuote(const std::string&s){std::string out="\"";for(unsigned char c:s){if(c=='"'||c=='\\')out+='\\';if(c>=32)out+=char(c);else out+=' ';}return out+'"';}
} // namespace demo
