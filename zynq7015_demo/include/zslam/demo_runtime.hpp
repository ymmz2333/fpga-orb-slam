#pragma once
#include "demo_state.hpp"
#include "demo_store.hpp"
#include <chrono>
#include <condition_variable>
#include <deque>
#include <thread>

namespace demo {
inline bool readable(Socket s,unsigned milliseconds){fd_set set;FD_ZERO(&set);FD_SET(s,&set);timeval t{long(milliseconds/1000),long(milliseconds%1000)*1000};
    int rc=select(int(s)+1,&set,nullptr,nullptr,&t);if(rc<0)throw std::runtime_error("Socket select failed");return rc>0;}
class Runtime {
    State &state_;MapStore &store_;Socket control_=invalid_socket,stream_=invalid_socket,map_=invalid_socket;
    std::thread control_thread_,stream_thread_,map_thread_;std::atomic<bool> stopping_{false};
    std::condition_variable changed_;std::deque<Packet> queue_;bool connected_=false,drained_=false;
    std::string calibration_;uint64_t last_frame_=0,last_stamp_=0;unsigned high_=0;
    Socket active_control_=invalid_socket,active_stream_=invalid_socket,active_map_=invalid_socket;
    struct Active {
        State&s;Socket &slot;Active(State&state,Socket&where,Socket fd):s(state),slot(where){std::lock_guard<std::mutex>l(s.mutex);slot=fd;}
        ~Active(){std::lock_guard<std::mutex>l(s.mutex);slot=invalid_socket;}
    };
    void streamLoop(){while(!stopping_){try{
        if(!readable(stream_,100))continue;Connection peer(::accept(stream_,nullptr,nullptr));if(peer.fd==invalid_socket)continue;Active active(state_,active_stream_,peer.fd);peer.timeout(10);
        auto hello=peer.receive();if(hello.kind!=Hello||string(hello.body)!=store_.calibration())throw std::runtime_error("RK calibration handshake mismatch");
        peer.send(response(Hello,store_.calibration()+"\n"+profile+"\n"+calibration_));
        {std::lock_guard<std::mutex>l(state_.mutex);if(connected_)throw std::runtime_error("Only one RK stream owner is allowed");connected_=true;drained_=false;changed_.notify_all();}
        std::deque<Packet> pending;bool done=false;auto progress=std::chrono::steady_clock::now();
        while(!stopping_&&!done){Packet next;bool send=false,ending=false;uint64_t sid=0;
            {std::unique_lock<std::mutex>l(state_.mutex);changed_.wait_for(l,std::chrono::milliseconds(10),[&]{return stopping_||!queue_.empty()||state_.mode!=Mode::Mapping;});
                if(state_.mode==Mode::Fault||state_.mode==Mode::Stopped)break;
                if(!queue_.empty()&&pending.size()<3){next=std::move(queue_.front());queue_.pop_front();send=true;changed_.notify_all();}
                ending=state_.mode==Mode::Finalizing&&queue_.empty()&&pending.empty();sid=state_.session;}
            if(send){peer.send(next);if(pending.empty())progress=std::chrono::steady_clock::now();pending.push_back(std::move(next));std::lock_guard<std::mutex>l(state_.mutex);state_.sent++;}
            if(!pending.empty()&&readable(peer.fd,20)){auto ack=peer.receive();const auto &front=pending.front();
                if(ack.kind!=Ack||ack.session!=front.session||ack.frame!=front.frame||ack.stamp!=front.stamp||!ack.body.empty()||ack.flags)throw std::runtime_error("RK acknowledgment identity mismatch");
                pending.pop_front();progress=std::chrono::steady_clock::now();std::lock_guard<std::mutex>l(state_.mutex);state_.acknowledged++;changed_.notify_all();}
            else if(!pending.empty()){if(std::chrono::steady_clock::now()-progress>std::chrono::seconds(10))throw std::runtime_error("RK processing acknowledgment timeout");
                // receive timeout is bounded too; detect peer loss even when no new camera frame is admitted.
                if(pending.size()==3){auto ack=peer.receive();const auto &front=pending.front();
                    if(ack.kind!=Ack||ack.session!=front.session||ack.frame!=front.frame||ack.stamp!=front.stamp||!ack.body.empty()||ack.flags)throw std::runtime_error("RK acknowledgment mismatch");
                    pending.pop_front();progress=std::chrono::steady_clock::now();std::lock_guard<std::mutex>l(state_.mutex);state_.acknowledged++;}}
            if(ending){Packet end;end.kind=End;end.session=sid;end.frame=last_frame_;end.stamp=last_stamp_;peer.send(end);auto ack=peer.receive();
                if(ack.kind!=Ack||ack.session!=sid||ack.frame!=end.frame||ack.stamp!=end.stamp||!ack.body.empty())throw std::runtime_error("RK final drain not acknowledged");
                {std::lock_guard<std::mutex>l(state_.mutex);drained_=true;}done=true;}
            if(pending.empty()&&!send&&!ending&&readable(peer.fd,0))throw std::runtime_error("Unexpected/disconnected RK stream");
        }
        {std::lock_guard<std::mutex>l(state_.mutex);connected_=false;queue_.clear();changed_.notify_all();}
    }catch(const std::exception&e){state_.transportFailure(e.what());std::lock_guard<std::mutex>l(state_.mutex);connected_=false;queue_.clear();changed_.notify_all();}}}
    void controlLoop(Socket listener,bool mapsOnly){while(!stopping_){if(!readable(listener,100))continue;Connection peer(::accept(listener,nullptr,nullptr));if(peer.fd==invalid_socket)continue;Active active(state_,mapsOnly?active_map_:active_control_,peer.fd);peer.timeout(mapsOnly?120:5);
        bool transfer=false;try{for(;;){auto p=peer.receive();
            if(p.kind==Control&&!mapsOnly){auto action=string(p.body);
                if(action=="start"){{std::lock_guard<std::mutex>l(state_.mutex);if(!connected_)throw std::runtime_error("RK receiver must complete handshake first");}
                    uint64_t sid=uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count());bool started=state_.start(sid);
                    if(started){std::lock_guard<std::mutex>l(state_.mutex);drained_=false;queue_.clear();last_frame_=last_stamp_=0;}}
                else if(action=="finalize")state_.finalize();
                else if(action=="abort")state_.fault("RK controller reported mapping/handover failure");
                else if(action=="prepare"){std::lock_guard<std::mutex>l(state_.mutex);
                    if(!state_.hardware_verified||state_.hardware_fault||state_.mode==Mode::Mapping||state_.mode==Mode::Finalizing||state_.mode==Mode::Installing)throw std::runtime_error("Cannot prepare receiver in current hardware/mapping state");
                    state_.mode=Mode::Waiting;state_.ready=false;state_.consecutive=0;state_.failure.clear();queue_.clear();}
                else if(action=="stop"){std::lock_guard<std::mutex>l(state_.mutex);state_.mode=Mode::Stopped;state_.ready=false;state_.consecutive=0;state_.pending_version.clear();queue_.clear();}
                else if(action=="relocalize"){std::lock_guard<std::mutex>l(state_.mutex);if(state_.hardware_fault||state_.version.empty()||state_.mode==Mode::Mapping||state_.mode==Mode::Finalizing||state_.mode==Mode::Installing)throw std::runtime_error("No safe installed local map to relocalize");state_.pending_version=state_.version;state_.mode=Mode::Installing;state_.ready=false;}
                else if(action!="status")throw std::runtime_error("Unknown demo command");changed_.notify_all();peer.send(response(Status,status()));break;
            }else if(p.kind==MapBegin&&mapsOnly){{std::lock_guard<std::mutex>l(state_.mutex);if(state_.mode!=Mode::Finalizing||!drained_||state_.sent!=state_.acknowledged)throw std::runtime_error("Mapping must finish and drain before map transfer");state_.mode=Mode::Installing;}
                transfer=true;store_.begin(p.body);peer.send(response(Status,"{\"received\":\"manifest\"}"));}
            else if(p.kind==MapFile&&transfer){store_.file(p.body);peer.send(response(Status,"{\"received\":\"file\"}"));}
            else if(p.kind==MapCommit&&transfer){auto version=store_.prepare();{std::lock_guard<std::mutex>l(state_.mutex);if(state_.mode!=Mode::Installing)throw std::runtime_error("Map installation cancelled");state_.pending_version=version;state_.map_id=store_.manifest().map_id;}peer.send(response(Status,"{\"prepared_version\":"+jsonQuote(version)+"}"));break;}
            else throw std::runtime_error("Invalid control/map transfer order");
        }}catch(const std::exception&e){if(transfer){std::lock_guard<std::mutex>l(state_.mutex);if(state_.mode!=Mode::Stopped){state_.mode=Mode::Fault;state_.ready=false;state_.failure=std::string("Map installation failed: ")+e.what();}}try{peer.send(response(Error,e.what()));}catch(...){};}
    }}
public:
    Runtime(State&s,MapStore&m,const std::string&camera,unsigned stream_port,unsigned control_port,unsigned map_port=0):state_(s),store_(m),calibration_(string(readFile(camera,4096))){
        try{stream_=listenSocket(stream_port);control_=listenSocket(control_port);map_=listenSocket(map_port?map_port:control_port+1);stream_thread_=std::thread([this]{streamLoop();});control_thread_=std::thread([this]{controlLoop(control_,false);});map_thread_=std::thread([this]{controlLoop(map_,true);});}
        catch(...){stopping_=true;changed_.notify_all();if(stream_thread_.joinable())stream_thread_.join();if(control_thread_.joinable())control_thread_.join();if(stream_!=invalid_socket)closeSocket(stream_);if(control_!=invalid_socket)closeSocket(control_);if(map_!=invalid_socket)closeSocket(map_);throw;}}
    ~Runtime(){stopping_=true;changed_.notify_all();{std::lock_guard<std::mutex>l(state_.mutex);
        for(Socket s:{active_control_,active_stream_,active_map_})if(s!=invalid_socket)shutdown(s,2);}
        if(stream_thread_.joinable())stream_thread_.join();if(control_thread_.joinable())control_thread_.join();if(map_thread_.joinable())map_thread_.join();closeSocket(control_);closeSocket(stream_);closeSocket(map_);}
    void enqueue(Packet p){std::unique_lock<std::mutex>l(state_.mutex);changed_.wait(l,[&]{return stopping_||state_.mode!=Mode::Mapping||queue_.size()<3;});
        if(stopping_||state_.mode!=Mode::Mapping)return;p.session=state_.session;
        if(last_stamp_&&(p.frame<=last_frame_||p.stamp<=last_stamp_))throw std::runtime_error("Non-monotonic camera stream");last_frame_=p.frame;last_stamp_=p.stamp;
        queue_.push_back(std::move(p));high_=std::max(high_,unsigned(queue_.size()));changed_.notify_all();}
    std::string status()const{std::lock_guard<std::mutex>l(state_.mutex);std::ostringstream out;
        out<<"{\"mode\":"<<jsonQuote(name(state_.mode))<<",\"session\":"<<state_.session<<",\"map_id\":"<<state_.map_id<<",\"map_version\":"<<jsonQuote(state_.version)
           <<",\"calibration_sha256\":"<<jsonQuote(store_.calibration())<<",\"profile\":"<<jsonQuote(profile)<<",\"hardware_verified\":"<<(state_.hardware_verified?"true":"false")
           <<",\"hardware_fault\":"<<(state_.hardware_fault?"true":"false")<<",\"ready_to_disconnect\":"<<(state_.ready?"true":"false")<<",\"consecutive_valid\":"<<state_.consecutive
           <<",\"sent\":"<<state_.sent<<",\"acknowledged\":"<<state_.acknowledged<<",\"queue_high\":"<<high_<<",\"stream_connected\":"<<(connected_?"true":"false")
           <<",\"drained\":"<<(drained_?"true":"false")<<",\"cpu_orb_calls\":0,\"error\":"<<jsonQuote(state_.failure)<<"}";return out.str();}
};
} // namespace demo
