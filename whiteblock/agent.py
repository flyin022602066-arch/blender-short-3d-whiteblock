"""Project operator agent: strict tools, routed through the configured Eggfans channel."""
from __future__ import annotations
import inspect,json, os, re, urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from .config import load_config, load_secrets

Tool = Callable[..., Any]

@dataclass
class AgentConfig:
    enabled: bool = False
    base_url: str = "https://api.eggfans.com"
    endpoint: str = "/v1/chat/completions"
    model: str = "seedance-2.5"
    api_key: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"

    @classmethod
    def from_env(cls) -> "AgentConfig":
        config = load_config(); eggfans = config.get("eggfans", {}); agent = config.get("agent", {})
        secrets = load_secrets()
        return cls(enabled=os.getenv("WHITEBLOCK_AGENT_ONLINE", "1" if agent.get("online") else "0") == "1",
                   base_url=os.getenv("EGGFANS_BASE_URL", eggfans.get("base_url", "https://api.eggfans.com")).rstrip("/"),
                   endpoint=os.getenv("EGGFANS_AGENT_ENDPOINT", eggfans.get("agent_endpoint", "/v1/chat/completions")),
                   model=os.getenv("EGGFANS_AGENT_MODEL", eggfans.get("agent_model", "gpt-6-astra")),
                   api_key=os.getenv("EGGFANS_API_KEY", secrets.get("eggfans_api_key", "")),
                   auth_header=eggfans.get("auth_header", "Authorization"), auth_prefix=eggfans.get("auth_prefix", "Bearer"))

class ProjectAgent:
    """Executes only registered project tools; arbitrary Python/code is never accepted."""
    def __init__(self, tools: dict[str, Tool], config: AgentConfig | None = None):
        self.tools = tools
        self.config = config or AgentConfig.from_env()
        self.last_actions: list[dict] = []
        self.tool_schemas={};self.context_provider=None

    def tool_names(self) -> list[str]: return sorted(self.tools)

    def _local_plan(self, text: str) -> tuple[str, list[dict]]:
        t = text.strip(); actions: list[dict] = []
        if any(k in t for k in ("状态", "进度", "现在什么", "项目情况")):
            actions.append({"tool": "project_status", "args": {}})
        if any(k in t for k in ("生成白模", "构建白模", "导出白模", "转换白模")):
            actions.append({"tool": "build_whiteblock", "args": {}})
        if "blender" in t.lower() and any(k in t for k in ("运行", "执行", "启动")):
            actions.append({"tool": "run_blender", "args": {}})
        if any(k in t for k in ("请求包", "seedance", "Seedance", "打包")):
            actions.append({"tool": "package_seedance", "args": {}})
        if any(k in t for k in ("保存", "落盘")):
            actions.append({"tool": "save_project", "args": {}})
        match = re.search(r"(?:选择|切换到|使用)\s*(?:镜头)?\s*(shot[_-]?\d+|\d+)", t, re.I)
        if match: actions.append({"tool": "select_shot", "args": {"shot_id": match.group(1)}})
        source_match = re.search(r"(?:导入视频|打开视频)\s+(.+)$", t, re.I)
        if source_match: actions.append({"tool": "import_source", "args": {"path": source_match.group(1).strip().strip('"') }})
        if any(k in t for k in ("新增镜头", "添加镜头")):
            actions.append({"tool": "add_shot", "args": {}})
        if any(k in t for k in ("删除镜头", "移除镜头")):
            actions.append({"tool": "remove_shot", "args": {}})
        if '白模仓库' in t:
            if any(k in t for k in ('查看','有哪些','列表')):actions.append({'tool':'list_whiteblocks','args':{}})
            if any(k in t for k in ('打开','显示','进入')):actions.append({'tool':'open_whiteblock_library','args':{}})
        if any(k in t for k in ('连接 Blender','连接blender','打开 Blender 编辑','连接三维编辑')):
            actions.append({'tool':'blender_connect','args':{}})
        if any(k in t for k in ('查看场景','读取场景')):actions.append({'tool':'blender_scene','args':{}})
        if any(k in t for k in ('检查穿模','复核穿模','检测碰撞')):actions.append({'tool':'blender_check','args':{}})
        role=re.search(r'Actor_\d+',t,re.I)
        template='female' if any(k in t for k in ('女型','女性','女角色')) else 'male' if any(k in t for k in ('男型','男性','男角色')) else 'neutral' if any(k in t for k in ('中性模板','中性白模')) else None
        if template is not None:
            if any(k in t for k in ('识别','判断','是不是','是否','不要','不能','不许','别把')):
                return '人物模板需按你提供的角色资料明确确认；询问或否定不会修改人物。可以说：把 Actor_01 设为男型。',[]
            if len(set(re.findall(r'Actor_\d+',t,re.I)))>1:
                return '请逐个人物确认模板，例如：把 Actor_01 设为男型。全部保存后可一起重渲染当前镜头。',[]
            if role is None:return '请指定当前镜头的人物编号，例如：把 Actor_01 设为男型。',[]
            template_args={'actor':role.group().title(),'template':template}
            shot_match=re.search(r'(?:镜头|shot)\s*[_-]?(\d+)',t,re.I)
            if shot_match:template_args['shot_id']='shot_'+shot_match.group(1).zfill(3)
            actions.append({'tool':'set_actor_template','args':template_args})
            if any(k in t for k in ('重渲染','重新渲染')) and not any(a['tool']=='blender_connect' for a in actions):actions.append({'tool':'blender_connect','args':{}})
        if any(k in t for k in ('人物模板','角色模板','有哪些人物')) and any(k in t for k in ('查看','列表','有哪些')):actions.append({'tool':'list_actor_profiles','args':{}})
        if any(k in t for k in ('重渲染','重新渲染')):actions.append({'tool':'blender_render','args':{}})
        if any(k in t for k in ('左手','右手')):
            pose='hand_chest' if '胸前' in t else 'raise_hand' if any(k in t for k in ('抬','举')) else 'hand_down' if any(k in t for k in ('放下','垂下')) else None
            if pose:
                args={'limb':'left_hand' if '左手' in t else 'right_hand','pose':pose}
                match=re.search(r'Actor_\d+',t,re.I)
                if match:args['actor']=match.group()
                actions.append({'tool':'blender_pose','args':args})
        if not actions and any(k in t for k in ("帮助", "能做什么", "功能")):
            return "我可以操控项目状态、镜头选择、白模生成、离线请求包、保存和打开输出目录。编码权限不在工具列表中。", []
        if not actions: return "我没有识别出可执行动作。可以说：生成白模、查看状态、选择镜头 shot_001、生成 Seedance 请求包、保存项目。", []
        return "已识别操作：" + "、".join(a["tool"] for a in actions), actions

    def _remote_plan(self, text: str) -> tuple[str, list[dict]]:
        definitions=[]
        for name,tool in self.tools.items():
            if name in self.tool_schemas:definitions.append(self.tool_schemas[name]);continue
            signature=inspect.signature(tool)
            definitions.append({'name':name,'parameters':[{'name':p.name,'required':p.default is inspect.Parameter.empty}
                for p in signature.parameters.values() if p.kind not in (inspect.Parameter.VAR_POSITIONAL,inspect.Parameter.VAR_KEYWORD)]})
        context=self.context_provider() if self.context_provider else {}
        system = ("你是短剧3D白模项目操作助手。只能输出JSON，不得写代码。inputSchema 是 args 的约束。Blender 工具必须先连接；多人时指定人物编号，无法确定时请求说明，不猜测。男型/女型是用户确认的渲染模板，不是从脸、服装或体型推断的性别。未确认的角色先请用户提供模板。询问是不是某模板、要求根据画面识别、否定设置均不授权修改模板。设置模板后重渲染时，先set_actor_template，再blender_connect，再blender_render。可用工具：" + json.dumps(definitions,ensure_ascii=False)+
                  '。当前场景：'+json.dumps(context,ensure_ascii=False)+
                  "。格式：{\"reply\":\"中文说明\",\"actions\":[{\"tool\":\"工具名\",\"args\":{}}]}。只使用可用工具。")
        payload = json.dumps({"model": self.config.model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}, ensure_ascii=False).encode("utf-8")
        auth_value = (self.config.auth_prefix + " " + self.config.api_key).strip()
        request = urllib.request.Request(self.config.base_url.rstrip("/") + "/" + self.config.endpoint.lstrip("/"), data=payload, headers={"Content-Type": "application/json", self.config.auth_header: auth_value}, method="POST")
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        if not match: raise ValueError("E_AGENT_SCHEMA: model response is not JSON")
        result = json.loads(match.group(0)); actions = []
        for action in result.get("actions", []):
            if action.get("tool") in self.tools: actions.append({"tool": action["tool"], "args": action.get("args") or {}})
        return result.get("reply", "已完成解析"), actions

    def plan(self, text: str) -> tuple[str, list[dict]]:
        if self.config.enabled and self.config.api_key:
            try: return self._remote_plan(text)
            except Exception as exc: return "在线模型调用失败，已回退本地指令解析：" + str(exc), self._local_plan(text)[1]
        return self._local_plan(text)

    def execute(self, text: str, progress=None) -> dict:
        def emit(event, **data):
            if progress:
                progress({"event": event, **data})
        emit("planning", text=text)
        reply, actions = self.plan(text); results = []
        emit("planned", count=len(actions))
        for action in actions:
            emit("tool_start", tool=action["tool"])
            try:
                value = self.tools[action["tool"]](**action["args"])
                results.append({"tool": action["tool"], "ok": True, "result": value})
                emit("tool_done", tool=action["tool"], ok=True)
            except Exception as exc:
                results.append({"tool": action["tool"], "ok": False, "error": str(exc)})
                emit("tool_done", tool=action["tool"], ok=False, error=str(exc))
                reply += "。此操作失败，后续操作已停止，请修正后重试。"
                break
        self.last_actions = results
        emit("completed", ok=all(item["ok"] for item in results))
        return {"reply": reply, "actions": results}
