"""Run with Blender --python. Network work queues to Blender's main thread."""
import json
from pathlib import Path
import queue
import secrets
import socketserver
import sys
import threading
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from whiteblock.blender_operations import dispatch

session_path=Path(sys.argv[sys.argv.index('--')+1]);workspace=session_path.parent
session=json.loads(session_path.read_text(encoding='utf-8'));commands=queue.Queue()

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request=json.loads(self.rfile.readline(1_000_000))
            if not secrets.compare_digest(str(request.get('token','')),session['token']):raise ValueError('Unauthorized')
            result_queue=queue.Queue();commands.put((request,result_queue))
            response=result_queue.get(timeout=175)
        except Exception as exc:response={'error':str(exc)}
        self.wfile.write((json.dumps(response,ensure_ascii=False)+'\n').encode('utf-8'))

class Server(socketserver.ThreadingTCPServer):
    daemon_threads=True;allow_reuse_address=True

server=Server(('127.0.0.1',session['port']),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()

def tick():
    try:
        request,result_queue=commands.get_nowait()
        try:result={'result':dispatch(request['operation'],request.get('arguments',{}),str(workspace))}
        except Exception as exc:result={'error':str(exc)}
        result_queue.put(result)
    except queue.Empty:pass
    return .05

bpy.app.timers.register(tick,persistent=True)
session['ready']=True;session['version']=list(bpy.app.version)
session_path.write_text(json.dumps(session,ensure_ascii=False),encoding='utf-8')
print('WHITEBLOCK MCP READY',flush=True)
