import json, tempfile, unittest
from pathlib import Path
from whiteblock.agent import AgentConfig, ProjectAgent
from whiteblock.pipeline import build_seedance_request, create_project, sha256

class AgentTests(unittest.TestCase):
    def test_local_agent_can_list_and_open_the_whiteblock_library(self):
        agent=ProjectAgent({'list_whiteblocks':lambda:{'count':3},'open_whiteblock_library':lambda:'opened'},AgentConfig())
        result=agent.execute('查看白模仓库并打开白模仓库')
        self.assertEqual([x['tool'] for x in result['actions']],['list_whiteblocks','open_whiteblock_library'])
        self.assertTrue(all(x['ok'] for x in result['actions']))

    def test_local_agent_only_executes_registered_tools(self):
        calls = []
        agent = ProjectAgent({"project_status": lambda: {"status": "ready"}, "save_project": lambda: calls.append("save")}, AgentConfig())
        result = agent.execute("查看项目状态并保存")
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(calls, ["save"])
        self.assertNotIn("coding", agent.tool_names())

    def test_execute_reports_progress_events_in_order(self):
        events = []
        agent = ProjectAgent({"project_status": lambda: {"status": "ready"}}, AgentConfig())
        result = agent.execute("查看项目状态", progress=events.append)
        self.assertEqual([event["event"] for event in events], ["planning", "planned", "tool_start", "tool_done", "completed"])
        self.assertEqual(events[1]["count"], 1)
        self.assertEqual(events[2]["tool"], "project_status")
        self.assertTrue(events[3]["ok"])
        self.assertTrue(events[4]["ok"])
        self.assertEqual(result["actions"][0]["tool"], "project_status")

    def test_blender_is_an_explicit_registered_operation(self):
        agent = ProjectAgent({"run_blender": lambda: "done"}, AgentConfig())
        result = agent.execute("执行 Blender")
        self.assertEqual(result["actions"][0]["tool"], "run_blender")

    def test_local_agent_can_manage_shot_tools(self):
        calls = []
        agent = ProjectAgent({"add_shot": lambda: calls.append("add"), "remove_shot": lambda: calls.append("remove")}, AgentConfig())
        result = agent.execute("新增镜头，然后删除镜头")
        self.assertEqual([x["tool"] for x in result["actions"]], ["add_shot", "remove_shot"])
        self.assertEqual(calls, ["add", "remove"])

    def test_import_path_is_passed_as_a_tool_argument(self):
        agent = ProjectAgent({"import_source": lambda path: path}, AgentConfig())
        result = agent.execute("导入视频 S:/素材/episode01.mp4")
        self.assertEqual(result["actions"][0]["result"], "S:/素材/episode01.mp4")

    def test_seedance_request_keeps_native_content_and_no_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / "video.mp4"; source.write_bytes(b"fixture")
            project = create_project(source, "p1", end_frame=30, workspace=root)
            out = root / "exports"; shot = project["shots"][0]
            result = build_seedance_request(project, shot, out)
            request = result["request"]
            self.assertEqual([item["type"] for item in request["content"]], ["text", "video_url"])
            self.assertEqual(request["content"][1]["role"], "reference_video")
            self.assertFalse(request["api_key_included"])
            self.assertEqual(json.loads(Path(result["path"]).read_text(encoding="utf-8"))["offline"], True)

if __name__ == "__main__": unittest.main()
