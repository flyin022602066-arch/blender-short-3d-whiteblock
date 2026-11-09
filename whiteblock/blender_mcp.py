"""Dependency-free MCP stdio server and client for trusted local Blender tools."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading

def schema(properties=None,required=None):
    return {'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}

TOOLS=[
    {'name':'get_scene_summary','description':'读取当前 Blender 人物、骨架、镜头与帧范围。','inputSchema':schema()},
    {'name':'set_frame','description':'跳转到原片绝对帧，便于复核。','inputSchema':schema({'frame':{'type':'integer','minimum':1}},['frame'])},
    {'name':'get_preview','description':'渲染当前帧并返回本地 PNG 路径。','inputSchema':schema()},
    {'name':'check_intersections','description':'检查当前帧已变形的人物表面相交，报告检测范围。','inputSchema':schema()},
    {'name':'set_ik_target','description':'在当前帧调整手或脚的世界坐标 IK 目标；actor 可由场景查询获取。','inputSchema':schema({
        'actor':{'type':'string'},'limb':{'type':'string','enum':['left_hand','right_hand','left_foot','right_foot']},
        'position':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3}},['actor','limb','position'])},
    {'name':'set_camera','description':'调整当前镜头构图；scale 为正交相机画面高度。','inputSchema':schema({
        'scale':{'type':'number','minimum':.1,'maximum':100},'x':{'type':'number'},'z':{'type':'number'}})},
    {'name':'pose_preset','description':'在当前帧抬手、放下手或放到胸前；多人时必须指定 actor。','inputSchema':schema({
        'actor':{'type':'string'},'limb':{'type':'string','enum':['left_hand','right_hand']},
        'pose':{'type':'string','enum':['hand_chest','raise_hand','hand_down']}},['limb','pose'])},
    {'name':'set_body_template','description':'选择同拓扑成年人体轮廓；原动作和工程保留。','inputSchema':schema({
        'actor':{'type':'string'},'template':{'type':'string','enum':['neutral','male','female']},'role_name':{'type':'string','maxLength':80}},['actor','template'])},
    {'name':'save_revision','description':'将当前工程另存为独立修订，保留原版。','inputSchema':schema()},
]

def bridge_call(session_path,name,args):
    if name not in {t['name'] for t in TOOLS}:raise ValueError('未注册的 Blender 工具：'+name)
    session=json.loads(Path(session_path).read_text(encoding='utf-8'))
    if session.get('host','127.0.0.1')!='127.0.0.1':raise ValueError('Blender bridge must be local')
    with socket.create_connection(('127.0.0.1',session['port']),timeout=10) as connection:
        connection.settimeout(180)
        connection.sendall((json.dumps({'token':session['token'],'operation':name,'arguments':args},ensure_ascii=False)+'\n').encode('utf-8'))
        with connection.makefile('rb') as stream:response=json.loads(stream.readline(8_000_000))
    if response.get('error'):raise RuntimeError(response['error'])
    return response['result']


def serve(session_path):
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line);method=request.get('method');params=request.get('params',{})
            if 'id' not in request:continue
            if method=='initialize':
                result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'whiteblock-blender','version':'1.0'}}
            elif method=='tools/list':result={'tools':TOOLS}
            elif method=='ping':result={}
            elif method=='tools/call':
                try:
                    value=bridge_call(session_path,params['name'],params.get('arguments',{}))
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
                except Exception as exc:result={'content':[{'type':'text','text':str(exc)}],'isError':True}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
            print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result},ensure_ascii=False),flush=True)
        except Exception as exc:
            print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32600,'message':str(exc)}}),flush=True)


class BlenderMCPClient:
    def __init__(self,session_path):
        self._lock=threading.Lock();self._id=0;self._responses=queue.Queue()
        self.process=subprocess.Popen([sys.executable,'-m','whiteblock.blender_mcp','--session',str(session_path)],
             cwd=Path(__file__).resolve().parents[1],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
             text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def read():
            for line in self.process.stdout:
                try:self._responses.put(json.loads(line))
                except ValueError:pass
            self._responses.put({'error':{'message':'MCP process exited'}})
        threading.Thread(target=read,daemon=True).start()
        self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'Whiteblock Desktop','version':'3'}})
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');self.process.stdin.flush()
        self.tools=self.request('tools/list',{})['tools']

    def request(self,method,params):
        with self._lock:
            self._id+=1;self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self._id,'method':method,'params':params},ensure_ascii=False)+'\n');self.process.stdin.flush()
            try:response=self._responses.get(timeout=190)
            except queue.Empty:raise TimeoutError('Blender MCP 超时；请检查 Blender 窗口和日志')
            if 'error' in response:raise RuntimeError(response['error']['message'])
            return response['result']

    def call(self,name,**arguments):
        result=self.request('tools/call',{'name':name,'arguments':arguments})
        text=result['content'][0]['text']
        if result.get('isError'):raise RuntimeError(text)
        return json.loads(text)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
        self.process.stdout.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--session',required=True);args=parser.parse_args();serve(args.session)
