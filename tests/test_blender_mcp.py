import importlib.util
import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest


class BlenderMCPTests(unittest.TestCase):
    def test_stdio_mcp_initializes_lists_tools_and_calls_a_local_bridge(self):
        self.assertIsNotNone(importlib.util.find_spec('whiteblock.blender_mcp'),'The software needs its own MCP client/server')
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request=json.loads(self.rfile.readline())
                result={'objects':3} if request.get('token')=='test-token' else {'error':'unauthorized'}
                self.wfile.write((json.dumps({'result':result})+'\n').encode())
        server=socketserver.TCPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                session=Path(d)/'session.json';session.write_text(json.dumps({'host':'127.0.0.1','port':server.server_address[1],'token':'test-token'}))
                child=subprocess.Popen([sys.executable,'-m','whiteblock.blender_mcp','--session',str(session)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
                def rpc(i,method,params={}):
                    child.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n');child.stdin.flush()
                    return json.loads(child.stdout.readline())
                init=rpc(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
                self.assertIn('tools',init['result']['capabilities'])
                names=[t['name'] for t in rpc(2,'tools/list')['result']['tools']]
                self.assertIn('get_scene_summary',names);self.assertIn('set_ik_target',names)
                self.assertNotIn('execute_code',names)
                result=rpc(3,'tools/call',{'name':'get_scene_summary','arguments':{}})
                self.assertEqual(json.loads(result['result']['content'][0]['text'])['objects'],3)
                error=rpc(4,'tools/call',{'name':'execute_code','arguments':{'code':'print(1)'}})
                self.assertTrue(error['result']['isError'])
                child.stdin.close();child.wait(timeout=5);child.stdout.close();child.stderr.close()
        finally:server.shutdown();server.server_close()

    def test_agent_understands_blender_review_without_using_code_tools(self):
        from whiteblock.agent import ProjectAgent,AgentConfig
        events=[]
        agent=ProjectAgent({'blender_scene':lambda:events.append('scene'),'blender_check':lambda:events.append('check'),
                            'blender_render':lambda:events.append('render')},AgentConfig())
        result=agent.execute('检查穿模并重渲染')
        self.assertEqual([a['tool'] for a in result['actions']],['blender_check','blender_render'])
        self.assertEqual(events,['check','render'])

    def test_agent_can_request_a_hand_pose_in_plain_chinese(self):
        from whiteblock.agent import ProjectAgent,AgentConfig
        calls=[]
        agent=ProjectAgent({'blender_pose':lambda **args:calls.append(args)},AgentConfig())
        result=agent.execute('把 Actor_01 的左手放到胸前')
        self.assertEqual(calls,[{'actor':'Actor_01','limb':'left_hand','pose':'hand_chest'}])
        self.assertTrue(result['actions'][0]['ok'])

if __name__=='__main__':unittest.main()
