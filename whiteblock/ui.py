"""Tkinter desktop control room for the offline whiteblock workflow."""
from __future__ import annotations
import json, os, queue, re, subprocess, threading, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .agent import AgentConfig, ProjectAgent
from .config import load_config, load_secrets, save_config
from .pipeline import (build_seedance_request, create_project, ensure_workspace, find_blender, load_project,
                       default_workspace, log_event, run, run_blender_script, save_project, set_status,
                       one_click_convert as convert_video, media_tool)
from .provider import probe_pricing
from .gallery import WhiteblockGallery
from .blender_session import BlenderSession
from .blender_mcp import TOOLS as BLENDER_TOOLS
from .actor_profiles import TEMPLATE_LABELS,template_profile,actor_profiles,update_actor_template

BG, PANEL, PANEL_2, PANEL_3, TEXT, MUTED, ACCENT, ACCENT_HOVER, INFO, AMBER, RED = "#0d1217", "#151c23", "#202b35", "#2b3945", "#edf5f7", "#91a2ae", "#b8e85b", "#d5fa86", "#69d4e8", "#f0b35a", "#ef6b73"

class WhiteblockApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WHITEBLOCK / 短剧三维反推工作台")
        self.geometry("1280x820"); self.minsize(1020, 680); self.configure(bg=BG)
        self.project: dict | None = None; self.project_path: Path | None = None; self.selected_shot = ""
        self.app_config = load_config(); self.app_secrets = load_secrets()
        self._queue: queue.Queue = queue.Queue(); self._busy = False; self._agent_running = False; self._agent_log_lines: list[str] = []
        self._conversion_running = False; self._conversion_log = []; self._poll_timer = None
        self.blender_session=BlenderSession();self._blender_project_path=None;self._blender_shot_id=None
        self._vars = {k: tk.StringVar(value=v) for k, v in {"project":"未打开项目", "status":"待开始", "source":"未导入视频", "media":"等待探测", "shot_count":"0", "outputs":"0", "agent":"离线工具模式", "agent_status":"空闲"}.items()}
        self._style(); self._layout(); self._agent = ProjectAgent(self._agent_tools(), AgentConfig.from_env()); self._vars["agent"].set("离线工具模式 · Blender " + ("已检测" if find_blender() else "未检测")); self._poll_queue()
        mapping={'get_scene_summary':'blender_scene','set_frame':'blender_set_frame','get_preview':'blender_preview',
                 'check_intersections':'blender_check','set_ik_target':'blender_set_ik','set_camera':'blender_set_camera',
                 'save_revision':'blender_save_revision','pose_preset':'blender_pose','set_body_template':'blender_template'}
        self._agent.tool_schemas={mapping[t['name']]:{**t,'name':mapping[t['name']]} for t in BLENDER_TOOLS}
        self._agent.tool_schemas['set_actor_template']={
            'name':'set_actor_template','description':'按用户明确提供的角色资料保存人物渲染模板，选择指定镜头；之后连接 Blender 并重渲染。不得从画面推断性别。',
            'inputSchema':{'type':'object','properties':{
                'actor':{'type':'string','description':'当前镜头人物编号，如 Actor_01'},
                'template':{'type':'string','enum':['male','female','neutral']},
                'shot_id':{'type':'string','description':'可选镜头编号；省略则使用当前镜头'},
                'role_name':{'type':'string','maxLength':80,'description':'用户提供的角色名称'}},
                'required':['actor','template'],'additionalProperties':False}}
        self._agent.context_provider=self.blender_agent_context

    def _style(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("TFrame", background=BG); s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        s.configure("Muted.TLabel", foreground=MUTED, background=BG, font=("Microsoft YaHei UI", 9))
        s.configure("PanelMuted.TLabel", foreground=MUTED, background=PANEL, font=("Microsoft YaHei UI", 9))
        s.configure("Title.TLabel", foreground=TEXT, background=BG, font=("Bahnschrift", 20, "bold"))
        s.configure("Section.TLabel", foreground=TEXT, background=PANEL, font=("Microsoft YaHei UI", 12, "bold"))
        s.configure("Accent.TButton", background=ACCENT, foreground="#11170d", padding=(14, 8), font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0, relief="flat", lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ACCENT)
        s.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", "#9bc63e")], foreground=[("disabled", "#506044")])
        s.configure("Quiet.TButton", background=PANEL_2, foreground=TEXT, padding=(12, 7), borderwidth=0, relief="flat", lightcolor=PANEL_2, darkcolor=PANEL_2, focuscolor=PANEL_2)
        s.map("Quiet.TButton", background=[("active", PANEL_3), ("pressed", "#344452"), ("disabled", "#1a2229")], foreground=[("active", TEXT), ("disabled", "#52616b")])
        s.configure("Nav.TButton", background=PANEL, foreground=TEXT, padding=(12, 9), borderwidth=0, relief="flat", lightcolor=PANEL, darkcolor=PANEL, focuscolor=PANEL)
        s.map("Nav.TButton", background=[("active", PANEL_2), ("pressed", PANEL_3)], foreground=[("active", ACCENT_HOVER)])
        s.configure("NavActive.TButton", background=PANEL_3, foreground=ACCENT_HOVER, padding=(12, 9), borderwidth=0, relief="flat", lightcolor=PANEL_3, darkcolor=PANEL_3, focuscolor=PANEL_3)
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=32, borderwidth=0)
        s.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED, relief="flat", font=("Microsoft YaHei UI", 9, "bold"))
        s.configure("Gallery.Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=82, borderwidth=0, font=("Microsoft YaHei UI", 9))
        s.map("Gallery.Treeview", background=[("selected", "#354532")], foreground=[("selected", "#f7ffe8")])
        s.map("Treeview", background=[("selected", "#354532")], foreground=[("selected", "#f7ffe8")])
        s.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=TEXT, borderwidth=1, relief="flat", lightcolor="#3d5260", darkcolor="#3d5260", bordercolor="#3d5260", padding=(8, 5))
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 9), padding=4)
        s.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", ACCENT_HOVER)])
        s.configure("Vertical.TScrollbar", background=PANEL_3, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED, relief="flat", width=12)
        s.configure("Horizontal.TScrollbar", background=PANEL_3, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED, relief="flat", width=12)
        s.configure("Agent.Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL_2, bordercolor=PANEL_2, lightcolor=ACCENT, darkcolor=ACCENT)
        s.configure("TSeparator", background="#34424d")
        s.configure("TNotebook", background=BG, borderwidth=0); s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(12, 7))

    def _layout(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=26, pady=(20, 10))
        ttk.Label(top, text="WHITEBLOCK", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  /  短剧三维反推工作台", style="Muted.TLabel").pack(side="left", pady=(7, 0))
        ttk.Label(top, textvariable=self._vars["project"], style="Muted.TLabel").pack(side="right", padx=(0, 16))
        ttk.Button(top, text="Agent 控制台", style="Accent.TButton", command=self.show_agent).pack(side="right")
        body = ttk.Frame(self); body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        nav = ttk.Frame(body, style="Panel.TFrame", width=188); nav.pack(side="left", fill="y", padx=(0, 12)); nav.pack_propagate(False)
        ttk.Label(nav, text="工作流", style="Section.TLabel").pack(anchor="w", padx=16, pady=(18, 12))
        self.nav_buttons = {}
        for label, page in (("概览", "overview"), ("视频与镜头", "shots"), ("人物与模板", "actors"), ("白模生成", "whiteblock"), ("白模仓库", "library"), ("导出与请求包", "package"), ("连接与设置", "settings")):
            button = tk.Button(nav, text=label, bg=PANEL, fg=TEXT, activebackground=PANEL_2, activeforeground=ACCENT_HOVER, relief="flat", bd=0, highlightthickness=0, font=("Microsoft YaHei UI", 10), cursor="hand2", command=lambda p=page: self.show_page(p)); button.pack(fill="x", padx=12, pady=3, ipady=7); self.nav_buttons[page] = button
        ttk.Separator(nav).pack(fill="x", padx=16, pady=18)
        ttk.Button(nav, text="新建项目", style="Accent.TButton", command=self.new_project).pack(fill="x", padx=12, pady=4)
        ttk.Button(nav, text="打开项目", style="Quiet.TButton", command=self.open_project).pack(fill="x", padx=12, pady=4)
        ttk.Button(nav, text="保存项目", style="Quiet.TButton", command=self.save_current).pack(fill="x", padx=12, pady=4)
        ttk.Label(nav, textvariable=self._vars["agent"], style="PanelMuted.TLabel", wraplength=150).pack(side="bottom", anchor="w", padx=16, pady=18)
        self.content = ttk.Frame(body); self.content.pack(side="left", fill="both", expand=True)
        self.pages = {k: ttk.Frame(self.content, style="Panel.TFrame") for k in ("overview", "shots", "actors", "whiteblock", "package", "settings")}
        self.gallery=WhiteblockGallery(self.content,default_workspace(),self._run_async,self._open_library_project,self.connect_library_blender)
        self.pages['library']=self.gallery
        self._build_overview(); self._build_shots(); self._build_actor_templates(); self._build_whiteblock(); self._build_package(); self._build_settings(); self.show_page("overview")
        self.statusbar = ttk.Label(self, text="离线模式：不会上传素材或调用远程模型", style="Muted.TLabel", anchor="w"); self.statusbar.pack(fill="x", padx=26, pady=(0, 12))

    def _clear_page(self, page):
        for child in page.winfo_children(): child.destroy()

    def _build_overview(self):
        page = self.pages["overview"]; self._clear_page(page)
        ttk.Label(page, text="项目概览", style="Title.TLabel").pack(anchor="w", padx=26, pady=(24, 4))
        ttk.Label(page, text="从源视频到可执行白模脚本，再到离线请求包，所有阶段都保留可追溯产物。", style="Muted.TLabel").pack(anchor="w", padx=26, pady=(0, 18))
        cards = ttk.Frame(page); cards.pack(fill="x", padx=26)
        for index, (title, key) in enumerate((("项目状态", "status"), ("源视频", "source"), ("媒体信息", "media"), ("镜头数", "shot_count"), ("输出数", "outputs"))):
            cards.columnconfigure(index, weight=1, uniform="summary")
            box = ttk.Frame(cards, style="Panel.TFrame"); box.grid(row=0, column=index, sticky="nsew", padx=(0, 8), ipadx=4, ipady=12)
            ttk.Label(box, text=title, style="Muted.TLabel").pack(anchor="w", padx=12, pady=(10, 5)); ttk.Label(box, textvariable=self._vars[key], style="Section.TLabel", wraplength=150).pack(anchor="w", padx=12, pady=(0, 10))
        flow = ttk.Frame(page, style="Panel.TFrame"); flow.pack(fill="both", expand=True, padx=26, pady=20)
        ttk.Label(flow, text="连续工作流", style="Section.TLabel").pack(anchor="w", padx=18, pady=(18, 6))
        self.flow_text = tk.Text(flow, height=12, bg=PANEL, fg=TEXT, relief="flat", bd=0, padx=18, pady=10, font=("Consolas", 10), state="disabled")
        self.flow_text.pack(fill="both", expand=True, padx=8, pady=(0, 14))
        actions = ttk.Frame(page); actions.pack(fill="x", padx=26, pady=(0, 8))
        self.convert_button = ttk.Button(actions, text="一键转换白模", style="Accent.TButton", command=self.one_click_convert)
        self.convert_button.pack(side="left")
        ttk.Button(actions, text="导入 / 探测视频", style="Quiet.TButton", command=self.new_project).pack(side="left", padx=8)
        ttk.Button(actions, text="生成白模脚本", style="Quiet.TButton", command=self.build_whiteblock).pack(side="left")
        ttk.Button(actions, text="打开 Agent", style="Quiet.TButton", command=self.show_agent).pack(side="right")
        outputs = ttk.Frame(page); outputs.pack(fill="x", padx=26, pady=(0, 18))
        ttk.Button(outputs, text="播放白模预览", style="Quiet.TButton", command=self.open_whiteblock_preview).pack(side="left")
        ttk.Button(outputs, text="打开输出文件夹", style="Quiet.TButton", command=self.open_output_folder).pack(side="left", padx=8)

    def _build_shots(self):
        page = self.pages["shots"]; self._clear_page(page)
        ttk.Label(page, text="视频与镜头", style="Title.TLabel").pack(anchor="w", padx=26, pady=(24, 4)); ttk.Label(page, text="源视频只读；镜头边界、角色和道具修改写入项目 JSON。", style="Muted.TLabel").pack(anchor="w", padx=26, pady=(0, 12))
        toolbar = ttk.Frame(page); toolbar.pack(fill="x", padx=26, pady=(0, 10)); ttk.Button(toolbar, text="导入 / 替换源视频", style="Accent.TButton", command=self.import_video).pack(side="left"); ttk.Button(toolbar, text="新增镜头", style="Quiet.TButton", command=self.add_shot).pack(side="left", padx=8); ttk.Button(toolbar, text="删除镜头", style="Quiet.TButton", command=self.remove_shot).pack(side="left")
        area = ttk.Frame(page); area.pack(fill="both", expand=True, padx=26, pady=(0, 22)); left = ttk.Frame(area, style="Panel.TFrame"); left.pack(side="left", fill="both", expand=True, padx=(0, 10)); self.shot_tree = ttk.Treeview(left, columns=("name", "range", "fps", "status"), show="headings", selectmode="browse");
        for col, text, width in (("name", "镜头", 170), ("range", "帧范围", 130), ("fps", "FPS", 70), ("status", "状态", 110)): self.shot_tree.heading(col, text=text); self.shot_tree.column(col, width=width, anchor="w")
        self.shot_tree.pack(fill="both", expand=True, padx=12, pady=12); self.shot_tree.bind("<<TreeviewSelect>>", self.on_shot_select)
        right = ttk.Frame(area, style="Panel.TFrame", width=300); right.pack(side="right", fill="y"); right.pack_propagate(False); ttk.Label(right, text="镜头参数", style="Section.TLabel").pack(anchor="w", padx=18, pady=(18, 15))
        self.shot_fields = {}
        for key, label in (("shot_id", "ID"), ("name", "名称"), ("start_frame", "起始帧"), ("end_frame", "结束帧"), ("fps", "帧率")):
            row = ttk.Frame(right, style="Panel.TFrame"); row.pack(fill="x", padx=16, pady=5); ttk.Label(row, text=label, style="Muted.TLabel", width=9).pack(side="left"); var = tk.StringVar(); self.shot_fields[key] = var; ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(right, text="应用镜头修改", style="Accent.TButton", command=self.update_shot).pack(fill="x", padx=16, pady=(18, 5))
        ttk.Button(right,text='确认人物男型 / 女型',style='Quiet.TButton',command=lambda:self.show_page('actors')).pack(fill='x',padx=16,pady=5)

    def _build_actor_templates(self):
        page=self.pages['actors']
        ttk.Label(page,text='人物与模板',style='Title.TLabel').pack(anchor='w',padx=24,pady=(20,4))
        ttk.Label(page,text='按角色资料确认男型 / 女型；选择随工程保存，未确认时使用中性模板。',style='PanelMuted.TLabel').pack(anchor='w',padx=24,pady=(0,12))
        toolbar=ttk.Frame(page,style='Panel.TFrame');toolbar.pack(fill='x',padx=24,pady=(0,12))
        ttk.Label(toolbar,text='当前镜头',style='PanelMuted.TLabel').pack(side='left',padx=(0,8))
        self.actor_shot_var=tk.StringVar();self.actor_shot_combo=ttk.Combobox(toolbar,textvariable=self.actor_shot_var,state='readonly',width=12)
        self.actor_shot_combo.pack(side='left');self.actor_shot_combo.bind('<<ComboboxSelected>>',lambda e:(self.agent_select(self.actor_shot_var.get()),self._refresh_all()))
        self.actor_summary=tk.StringVar(value='请先打开项目')
        ttk.Label(toolbar,textvariable=self.actor_summary,style='PanelMuted.TLabel').pack(side='left',padx=14)
        area=ttk.Frame(page,style='Panel.TFrame');area.pack(fill='both',expand=True,padx=24,pady=(0,18))
        area.columnconfigure(0,weight=1,minsize=270);area.columnconfigure(1,weight=1,minsize=310);area.rowconfigure(0,weight=1)
        left=ttk.Frame(area,style='Panel.TFrame');left.grid(row=0,column=0,sticky='nsew',padx=(0,16));left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1)
        self.actor_tree=ttk.Treeview(left,columns=('role','template','state'),show='tree headings',selectmode='browse')
        self.actor_tree.heading('#0',text='人物编号');self.actor_tree.column('#0',width=100,minwidth=95)
        for name,label,width in [('role','角色名称',105),('template','模板',55),('state','状态',90)]:
            self.actor_tree.heading(name,text=label);self.actor_tree.column(name,width=width,minwidth=45)
        self.actor_tree.grid(row=0,column=0,sticky='nsew');self.actor_tree.bind('<<TreeviewSelect>>',self._actor_selected)
        scroll=ttk.Scrollbar(left,orient='vertical',command=self.actor_tree.yview);scroll.grid(row=0,column=1,sticky='ns');self.actor_tree.configure(yscrollcommand=scroll.set)
        ttk.Label(left,text='编号按镜头独立；请逐镜头确认。',style='PanelMuted.TLabel').grid(row=1,column=0,sticky='w',pady=(10,0))
        right=ttk.Frame(area,style='Panel.TFrame');right.grid(row=0,column=1,sticky='nsew');right.columnconfigure(0,weight=1);right.rowconfigure(1,weight=1)
        self.actor_reference_var=tk.StringVar(value='选择左侧人物查看原片参照')
        ttk.Label(right,textvariable=self.actor_reference_var,style='PanelMuted.TLabel',wraplength=300).grid(row=0,column=0,sticky='ew',pady=(0,6))
        self.actor_canvas=tk.Canvas(right,bg=BG,highlightthickness=0,height=160);self.actor_canvas.grid(row=1,column=0,sticky='nsew',pady=(0,10))
        self._actor_reference=None;self._actor_reference_key=None;self.actor_canvas.bind('<Configure>',lambda e:self._draw_actor_reference())
        fields=ttk.Frame(right,style='Panel.TFrame');fields.grid(row=2,column=0,sticky='ew');fields.columnconfigure(1,weight=1)
        ttk.Label(fields,text='角色名称',style='PanelMuted.TLabel').grid(row=0,column=0,sticky='w',padx=(0,10),pady=5)
        self.actor_role_var=tk.StringVar();ttk.Entry(fields,textvariable=self.actor_role_var).grid(row=0,column=1,sticky='ew',pady=5)
        ttk.Label(fields,text='白模模板',style='PanelMuted.TLabel').grid(row=1,column=0,sticky='w',padx=(0,10),pady=5)
        self.actor_template_var=tk.StringVar(value=TEMPLATE_LABELS['neutral'])
        self.actor_template_combo=ttk.Combobox(fields,textvariable=self.actor_template_var,values=list(TEMPLATE_LABELS.values()),state='readonly')
        self.actor_template_combo.grid(row=1,column=1,sticky='ew',pady=5)
        self.actor_apply_button=ttk.Button(right,text='保存人物模板',style='Quiet.TButton',command=self.save_actor_template)
        self.actor_apply_button.grid(row=3,column=0,sticky='ew',pady=(8,6))
        self.actor_render_button=ttk.Button(right,text='应用并重渲染当前镜头',style='Accent.TButton',command=self.render_actor_template)
        self.actor_render_button.grid(row=4,column=0,sticky='ew',pady=(0,8))
        self.actor_template_note=tk.StringVar(value='改变模板后需重渲染；已有视频会保留。')
        ttk.Label(right,textvariable=self.actor_template_note,style='PanelMuted.TLabel',wraplength=300).grid(row=5,column=0,sticky='ew')

    def _refresh_actor_templates(self):
        if not hasattr(self,'actor_tree'):return
        selected=self.actor_tree.selection();previous=selected[0] if selected else None
        self.actor_tree.delete(*self.actor_tree.get_children())
        shots=(self.project or {}).get('shots',[]);self.actor_shot_combo.configure(values=[s['shot_id'] for s in shots])
        if not self.project or not shots:
            self.actor_summary.set('请先打开项目');return
        sid=self.selected_shot or shots[0]['shot_id'];self.actor_shot_var.set(sid)
        profiles=actor_profiles(self.project,sid);pending=sum(not a['template_confirmed'] for a in profiles)
        self.actor_summary.set(f'{len(profiles)} 个人物 · {pending} 个待确认')
        for actor in profiles:
            state='待重渲染' if actor['template_needs_render'] else '已确认' if actor['template_confirmed'] else '待确认'
            self.actor_tree.insert('','end',iid=actor['id'],text=actor['id'],values=(actor['role_name'],TEMPLATE_LABELS[actor['body_template']],state))
        enabled=bool(profiles)
        for button in (self.actor_apply_button,self.actor_render_button):button.configure(state='normal' if enabled else 'disabled')
        if profiles:self.actor_tree.selection_set(previous if previous and self.actor_tree.exists(previous) else profiles[0]['id'])
        else:
            self._actor_reference=None;self._actor_reference_key=None;self.actor_reference_var.set('此镜头无可靠人物轨迹，场景或局部人物待补充');self._draw_actor_reference()

    def _actor_selected(self,event=None):
        selected=self.actor_tree.selection()
        if not selected or not self.project:return
        shot=next(s for s in self.project['shots'] if s['shot_id']==self.actor_shot_var.get())
        actor=next(a for a in shot.get('actors',[]) if a['id']==selected[0]);profile=template_profile(actor)
        self.actor_role_var.set(profile['role_name']);self.actor_template_var.set(TEMPLATE_LABELS[profile['body_template']])
        self.actor_template_note.set('模板已修改，点击上方按钮生成新修订。' if profile['template_needs_render'] else '根据角色资料确认模板；不从外观自动判定性别。')
        poses=actor.get('poses',[]);sample=max(poses,key=lambda p:p.get('confidence',0)) if poses else {'frame':shot['start_frame']}
        frame=sample['frame'];source=Path(self.project['source']['path']);key=(str(source),shot['shot_id'],actor['id'],frame)
        self.actor_reference_var.set(f'{actor["id"]} · 原片第 {frame} 帧')
        if self._actor_reference_key==key:return
        self._actor_reference_key=key;self._actor_reference=None
        if source.is_file():
            import cv2
            from PIL import Image,ImageDraw
            cap=cv2.VideoCapture(str(source))
            try:
                cap.set(cv2.CAP_PROP_POS_FRAMES,frame-1);ok,picture=cap.read()
                if ok:
                    image=Image.fromarray(cv2.cvtColor(picture,cv2.COLOR_BGR2RGB));points=sample.get('landmarks',[])
                    if len(points)==33:
                        x,y=points[0][:2];radius=max(8,int(image.width*.025))
                        ImageDraw.Draw(image).ellipse((x*image.width-radius,y*image.height-radius,x*image.width+radius,y*image.height+radius),outline=ACCENT,width=4)
                    self._actor_reference=image
            finally:cap.release()
        self._draw_actor_reference()

    def _draw_actor_reference(self):
        if not hasattr(self,'actor_canvas') or not self.actor_canvas.winfo_exists():return
        canvas=self.actor_canvas;canvas.delete('all');width,height=max(20,canvas.winfo_width()),max(20,canvas.winfo_height())
        if self._actor_reference is None:
            canvas.create_text(width/2,height/2,text='暂无原片参照',fill=MUTED);return
        from PIL import Image,ImageTk
        image=self._actor_reference.copy();image.thumbnail((width-10,height-10),Image.Resampling.LANCZOS)
        self._actor_reference_photo=ImageTk.PhotoImage(image,master=self);canvas.create_image(width/2,height/2,image=self._actor_reference_photo)

    def save_actor_template(self):
        if self._busy or self._agent_running:return self._notice('当前任务正在运行，请等待完成')
        selected=self.actor_tree.selection()
        if not selected:return
        template=next(k for k,v in TEMPLATE_LABELS.items() if v==self.actor_template_var.get())
        try:
            result=self.agent_set_actor_template(selected[0],template,self.actor_shot_var.get(),self.actor_role_var.get())
            self._refresh_actor_templates();self.actor_template_note.set('已保存；点击“应用并重渲染当前镜头”生成新修订。');return result
        except Exception as error:self._notice(str(error))

    def render_actor_template(self):
        if self._busy or self._agent_running:return self._notice('当前任务正在运行，请等待完成')
        if not self.save_actor_template():return
        self.actor_template_note.set('正在应用人物模板并重渲染…')
        self.blender_button_task(lambda:(self.agent_blender_connect(),self.agent_blender_render())[1])

    def _build_whiteblock(self):
        page = self.pages["whiteblock"]; self._clear_page(page)
        ttk.Label(page, text="白模生成", style="Title.TLabel").pack(anchor="w", padx=26, pady=(24, 4)); ttk.Label(page, text="生成场景规格与 Blender 5.1.2 Python 脚本；默认不启动 Blender。", style="Muted.TLabel").pack(anchor="w", padx=26, pady=(0, 16))
        panel = ttk.Frame(page, style="Panel.TFrame"); panel.pack(fill="x", padx=26, pady=(0, 12)); ttk.Label(panel, text="执行范围", style="Section.TLabel").pack(anchor="w", padx=18, pady=(18, 6)); self.whiteblock_scope = tk.StringVar(); self.whiteblock_scope.set("当前项目全部镜头"); ttk.Label(panel, textvariable=self.whiteblock_scope, style="Muted.TLabel").pack(anchor="w", padx=18, pady=(0, 18)); buttons = ttk.Frame(panel, style="Panel.TFrame"); buttons.pack(anchor="w", padx=18, pady=(0, 18)); ttk.Button(buttons, text="生成白模脚本与场景规格", style="Accent.TButton", command=self.build_whiteblock).pack(side="left"); ttk.Button(buttons, text="运行本地 Blender 创建 .blend", style="Quiet.TButton", command=self.run_blender_current).pack(side="left", padx=10)
        self.build_log = tk.Text(page, height=16, bg=PANEL, fg=TEXT, relief="flat", bd=0, padx=18, pady=12, state="disabled", font=("Consolas", 10)); self.build_log.pack(fill="both", expand=True, padx=26, pady=(0, 22))
        live=ttk.Frame(panel,style='Panel.TFrame');live.pack(fill='x',padx=18,pady=(0,12))
        for label,command in [('连接 Blender / MCP',lambda:self.blender_button_task(self.agent_blender_connect)),('检查当前帧穿模',lambda:self.blender_button_task(self.agent_blender_check)),('重渲染并另存',lambda:self.blender_button_task(self.agent_blender_render))]:
            ttk.Button(live,text=label,style='Quiet.TButton',command=command).pack(side='left',padx=(0,8))
        self.mcp_status=tk.StringVar(value='MCP 未连接 · 仿真人白模支持骨架与 IK 修正')
        ttk.Label(panel,textvariable=self.mcp_status,style='PanelMuted.TLabel').pack(anchor='w',padx=18,pady=(0,12))

    def _build_package(self):
        page = self.pages["package"]; self._clear_page(page)
        ttk.Label(page, text="导出与请求包", style="Title.TLabel").pack(anchor="w", padx=26, pady=(24, 4)); ttk.Label(page, text="仅生成离线 JSON，不上传媒体、不提交任务、不读取 API Key。", style="Muted.TLabel").pack(anchor="w", padx=26, pady=(0, 15))
        panel = ttk.Frame(page, style="Panel.TFrame"); panel.pack(fill="x", padx=26, pady=(0, 12)); ttk.Label(panel, text="Seedance 提示词", style="Section.TLabel").pack(anchor="w", padx=18, pady=(16, 6)); self.prompt = tk.Text(panel, height=4, bg=PANEL_2, fg=TEXT, relief="flat", bd=0, padx=10, pady=8); self.prompt.insert("1.0", "保持角色、场景、道具和镜头运动一致"); self.prompt.pack(fill="x", padx=18, pady=(0, 12)); ttk.Button(panel, text="生成离线请求包", style="Accent.TButton", command=self.build_package).pack(anchor="w", padx=18, pady=(0, 17))
        self.package_log = tk.Text(page, height=16, bg=PANEL, fg=TEXT, relief="flat", bd=0, padx=18, pady=12, state="disabled", font=("Consolas", 10)); self.package_log.pack(fill="both", expand=True, padx=26, pady=(0, 22))

    def _build_settings(self):
        page = self.pages["settings"]; self._clear_page(page)
        ttk.Label(page, text="连接与设置", style="Title.TLabel").pack(anchor="w", padx=26, pady=(24, 4))
        ttk.Label(page, text="一次填写，后续项目自动复用。API Key 保存在当前 Windows 用户的加密存储中，不写入项目 JSON。", style="PanelMuted.TLabel").pack(anchor="w", padx=26, pady=(0, 15))
        self.settings_vars = {}
        cfg = self.app_config; secrets = self.app_secrets
        canvas = tk.Canvas(page, bg=PANEL, highlightthickness=0); scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview); canvas.configure(yscrollcommand=scroll.set); scroll.pack(side="right", fill="y", padx=(0, 18), pady=18); canvas.pack(side="left", fill="both", expand=True, padx=26, pady=(0, 18)); form = ttk.Frame(canvas, style="Panel.TFrame"); canvas.create_window((0, 0), window=form, anchor="nw"); form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        # Tkinter does not scroll a Canvas with the mouse wheel unless it is explicitly bound.
        def wheel(event):
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            else:
                delta = int(event.delta / 120) if event.delta else 0
                if delta: canvas.yview_scroll(-3 * delta, "units")
            return "break"
        def bind_wheel(widget):
            widget.bind("<MouseWheel>", wheel, add="+")
            widget.bind("<Button-4>", wheel, add="+")
            widget.bind("<Button-5>", wheel, add="+")
            for child in widget.winfo_children(): bind_wheel(child)
        bind_wheel(canvas); bind_wheel(form)

        def section(title): ttk.Label(form, text=title, style="Section.TLabel").pack(anchor="w", padx=20, pady=(20, 8))
        def field(key, label, value, secret=False, width=54):
            row = ttk.Frame(form, style="Panel.TFrame"); row.pack(fill="x", padx=20, pady=5); ttk.Label(row, text=label, style="PanelMuted.TLabel", width=18).pack(side="left"); var = tk.StringVar(value=value); self.settings_vars[key] = var; ttk.Entry(row, textvariable=var, show="●" if secret else "", width=width).pack(side="left", fill="x", expand=True); return var
        section("Eggfans / Seedance")
        field("eggfans_base_url", "Base URL", cfg["eggfans"].get("base_url", "https://api.eggfans.com"))
        field("eggfans_pricing", "模型/计价路径", cfg["eggfans"].get("pricing_endpoint", "/api/pricing"))
        field("eggfans_agent_endpoint", "Agent 对话路径", cfg["eggfans"].get("agent_endpoint", "/v1/chat/completions"))
        field("eggfans_model", "默认模型 ID", cfg["eggfans"].get("model", "seedance-2.5"))
        field("eggfans_agent_model", "Agent 对话模型", cfg["eggfans"].get("agent_model", "gpt-6-astra"))
        field("eggfans_header", "API Key 请求头", cfg["eggfans"].get("auth_header", "Authorization"))
        field("eggfans_prefix", "请求头前缀", cfg["eggfans"].get("auth_prefix", "Bearer"))
        field("eggfans_key", "Eggfans API Key", secrets.get("eggfans_api_key", ""), secret=True)
        egg_buttons = ttk.Frame(form, style="Panel.TFrame"); egg_buttons.pack(fill="x", padx=20, pady=(6, 2)); ttk.Button(egg_buttons, text="测试 /api/pricing 连接", style="Quiet.TButton", command=self.test_eggfans).pack(side="left"); self.egg_status = tk.StringVar(value="未测试"); ttk.Label(egg_buttons, textvariable=self.egg_status, style="PanelMuted.TLabel").pack(side="left", padx=12)
        section("Agent 操作员（复用 Eggfans 通道）")
        self.settings_vars["agent_online"] = tk.BooleanVar(value=bool(cfg["agent"].get("online", False)))
        ttk.Checkbutton(form, text="启用在线 Agent（使用上方 Eggfans API Key 和模型）", variable=self.settings_vars["agent_online"]).pack(anchor="w", padx=20, pady=4)
        ttk.Label(form, text="Agent 不再使用独立 OpenAI 通道；Base URL、API Key、鉴权头和模型均复用 Eggfans 配置。", style="PanelMuted.TLabel", wraplength=700).pack(anchor="w", padx=20, pady=(0, 8))
        section("本地 Blender")
        ttk.Label(form, text="用途：白模脚本生成后，软件会调用这个本机 Blender 创建真正的 .blend 工程。这里不是 Eggfans 配置。", style="PanelMuted.TLabel", wraplength=760).pack(anchor="w", padx=20, pady=(0, 8))
        blender_row = ttk.Frame(form, style="Panel.TFrame"); blender_row.pack(fill="x", padx=20, pady=5); ttk.Label(blender_row, text="Blender 可执行文件", style="PanelMuted.TLabel", width=18).pack(side="left"); self.settings_vars["blender_path"] = tk.StringVar(value=cfg.get("blender_path", "")); ttk.Entry(blender_row, textvariable=self.settings_vars["blender_path"]).pack(side="left", fill="x", expand=True); ttk.Button(blender_row, text="浏览选择", style="Quiet.TButton", command=self.browse_blender).pack(side="left", padx=(8, 0)); ttk.Button(blender_row, text="自动检测", style="Quiet.TButton", command=self.detect_blender).pack(side="left", padx=(6, 0))
        self.blender_status = tk.StringVar(value="未配置：一键转换会先生成脚本，不能创建 .blend")
        ttk.Label(form, textvariable=self.blender_status, style="PanelMuted.TLabel", wraplength=760).pack(anchor="w", padx=20, pady=(2, 6))
        section('白模质量')
        quality=cfg.get('whiteblock',{})
        for key,label,values,default in [('geometry_profile','人物模型',['human_v3','mannequin_v2'],'human_v3'),('render_engine','渲染引擎',['eevee','cycles','workbench'],'eevee')]:
            row=ttk.Frame(form,style='Panel.TFrame');row.pack(fill='x',padx=20,pady=5)
            ttk.Label(row,text=label,style='PanelMuted.TLabel',width=18).pack(side='left')
            self.settings_vars[key]=tk.StringVar(value=quality.get(key,default))
            ttk.Combobox(row,textvariable=self.settings_vars[key],values=values,state='readonly',width=18).pack(side='left')
        ttk.Label(form,text='human_v3：连续真人轮廓＋蒙皮骨架（推荐）；EEVEE：带灯光的白模预览；Cycles：更慢的精细渲染。',style='PanelMuted.TLabel',wraplength=700).pack(anchor='w',padx=20,pady=7)
        self.settings_vars["offline"] = tk.BooleanVar(value=bool(cfg.get("offline_by_default", True))); ttk.Checkbutton(form, text="默认离线（推荐）：只生成本地白模和请求包，不上传素材", variable=self.settings_vars["offline"]).pack(anchor="w", padx=20, pady=7)
        ttk.Label(form, text="操作顺序：选择 blender.exe → 保存设置 → 回到概览 → 点击“一键转换白模”。", style="PanelMuted.TLabel", wraplength=760).pack(anchor="w", padx=20, pady=(0, 12))
        buttons = ttk.Frame(form, style="Panel.TFrame"); buttons.pack(fill="x", padx=20, pady=(18, 25)); ttk.Button(buttons, text="保存设置", style="Accent.TButton", command=self.save_settings).pack(side="left"); ttk.Button(buttons, text="恢复默认", style="Quiet.TButton", command=self.reset_settings).pack(side="left", padx=10)
        # Bind again after all form controls exist so wheel works over entries and checkboxes too.
        bind_wheel(form)
        self.detect_blender(silent=True)

    def save_settings(self):
        try:
            config = {"eggfans": {"base_url": self.settings_vars["eggfans_base_url"].get().strip(), "pricing_endpoint": self.settings_vars["eggfans_pricing"].get().strip() or "/api/pricing", "agent_endpoint": self.settings_vars["eggfans_agent_endpoint"].get().strip() or "/v1/chat/completions", "model": self.settings_vars["eggfans_model"].get().strip() or "seedance-2.5", "agent_model": self.settings_vars["eggfans_agent_model"].get().strip() or "gpt-6-astra", "auth_header": self.settings_vars["eggfans_header"].get().strip() or "Authorization", "auth_prefix": self.settings_vars["eggfans_prefix"].get().strip()}, "agent": {"online": bool(self.settings_vars["agent_online"].get())}, "blender_path": self.settings_vars["blender_path"].get().strip(), "offline_by_default": bool(self.settings_vars["offline"].get())}
            config['whiteblock']={key:self.settings_vars[key].get() for key in ('geometry_profile','render_engine')};config['whiteblock']['preview_max_edge']=1280
            save_config(config, self.settings_vars["eggfans_key"].get()); self.app_config = load_config(); self.app_secrets = load_secrets(); self._agent.config = AgentConfig.from_env();
            if self.project:
                self.project.setdefault("settings", {}).update({"eggfans_base_url": config["eggfans"]["base_url"], "pricing_endpoint": config["eggfans"]["pricing_endpoint"], "agent_endpoint": config["eggfans"]["agent_endpoint"], "eggfans_model": config["eggfans"]["model"], "eggfans_agent_model": config["eggfans"]["agent_model"], "blender_path": config["blender_path"]}); self.save_current()
            self._vars["agent"].set(("在线 Agent" if self._agent.config.enabled and self._agent.config.api_key else "离线工具模式") + " · Blender " + ("已检测" if find_blender(config["blender_path"] or None) else "未检测")); self.detect_blender(silent=True); self._log("设置已保存，API Key 已进入 Windows 加密存储")
        except Exception as exc: messagebox.showerror("保存设置失败", str(exc))

    def reset_settings(self):
        self.app_config = load_config()
        for key, value in (("eggfans_base_url", "https://api.eggfans.com"), ("eggfans_pricing", "/api/pricing"), ("eggfans_agent_endpoint", "/v1/chat/completions"), ("eggfans_model", "seedance-2.5"), ("eggfans_agent_model", "gpt-6-astra"), ("eggfans_header", "Authorization"), ("eggfans_prefix", "Bearer"), ("blender_path", "")):
            self.settings_vars[key].set(value)
        self.settings_vars["eggfans_key"].set(""); self.settings_vars["agent_online"].set(False); self.settings_vars["offline"].set(True); self._log("已恢复界面默认值，点击保存后生效")
        self.settings_vars['geometry_profile'].set('human_v3');self.settings_vars['render_engine'].set('eevee')

    def browse_blender(self):
        path = filedialog.askopenfilename(title="选择本地 Blender 可执行文件", filetypes=(("Blender", "blender.exe"), ("All", "*.*")))
        if path:
            self.settings_vars["blender_path"].set(path)
            self.detect_blender(silent=True)

    def detect_blender(self, silent: bool = False):
        configured = self.settings_vars.get("blender_path", tk.StringVar()).get().strip() or None
        found = find_blender(configured)
        if found:
            self.settings_vars["blender_path"].set(found)
            self.blender_status.set("已找到本地 Blender：" + found)
            if not silent: self._log("已检测到本地 Blender，请点击保存设置")
        else:
            self.blender_status.set("未找到 Blender：请点击“浏览选择”选中 blender.exe，或先安装 Blender 5.1.2")
            if not silent: self._notice("没有找到本地 Blender，请先安装 Blender 或手动选择 blender.exe")

    def test_eggfans(self):
        base_url = self.settings_vars["eggfans_base_url"].get().strip(); endpoint = self.settings_vars["eggfans_pricing"].get().strip() or "/pricing"; key = self.settings_vars["eggfans_key"].get(); header = self.settings_vars["eggfans_header"].get().strip() or "Authorization"; prefix = self.settings_vars["eggfans_prefix"].get().strip()
        self.egg_status.set("测试中…"); self._run_async(lambda: probe_pricing(base_url, endpoint, key, header, prefix), self._pricing_done)

    def _pricing_done(self, result):
        if isinstance(result, Exception): self.egg_status.set("失败：" + str(result)); return
        if result.get("ok"):
            self.egg_status.set("连接成功 · HTTP " + str(result.get("status", "-")))
        else:
            self.egg_status.set("失败：" + result.get("error", "HTTP " + str(result.get("status", "-"))))

    def one_click_convert(self):
        if self._busy: return self._notice("当前任务正在运行，请等待完成")
        source_value = filedialog.askopenfilename(title="选择视频并一键转换白模", filetypes=(("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", "*.*")))
        if not source_value: return
        source = Path(source_value).resolve()
        blender_path = self.settings_vars["blender_path"].get().strip() or find_blender()
        settings = {"preview_max_edge":1280,"eggfans_base_url": self.app_config["eggfans"].get("base_url", "https://api.eggfans.com"),
                    "eggfans_model": self.app_config["eggfans"].get("model", "seedance-2.5"),
                    'geometry_profile':self.settings_vars['geometry_profile'].get(),'render_engine':self.settings_vars['render_engine'].get()}
        self._conversion_running = True; self._conversion_log = []
        self.convert_button.configure(state="disabled"); self._set_busy(True)
        self._vars["source"].set(source.name)
        self._one_click_progress({"stage": "analyzing", "frame": 0, "total": 0})
        self._run_async(lambda: convert_video(source, default_workspace(), blender_path, settings,
                            progress=lambda event: self._queue.put((self._one_click_progress, event))), self._one_click_done)

    def _one_click_progress(self, event):
        stage = event.get("stage")
        if stage == "analyzing":
            text = f"正在分析视频 · {event.get('frame', 0)}/{event.get('total', 0)} 帧 · {event.get('shots', 0)} 个镜头"
        elif stage == "analysis_done":
            text = f"分析完成 · {event.get('shots', 0)} 个镜头 · {event.get('pose_samples', 0)} 组人物姿态"
        elif stage == "rendering":
            text = f"Blender 正在渲染 {event.get('shot', '')} · {event.get('frames', 0)}/{event.get('total', 0)} 帧"
        elif stage == 'geometry_check': text='正在逐帧复核与修正穿模 · '+event.get('shot','')+' · '+str(event.get('frames',0))+'/'+str(event.get('total',0))
        elif stage == "encoding": text = "正在编码镜头视频 · " + event.get("shot", "")
        elif stage == "assembling": text = "正在合并完整白模预览并校验时长"
        elif stage == "cataloging": text = "正在归档到白模仓库并生成缩略图"
        elif stage == "completed": text = "白模预览已生成 · 请复核遮挡、相机和场景"
        else: return
        self._vars["status"].set(text); self._log(text)
        self._conversion_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self._conversion_log = self._conversion_log[-60:]
        self._set_text(self.flow_text, "\n".join(self._conversion_log)); self.flow_text.see("end")
        self._set_text(self.build_log, "\n".join(self._conversion_log))

    def _one_click_done(self, result):
        self._conversion_running = False
        self.convert_button.configure(state="normal")
        self._set_busy(False)
        if isinstance(result, Exception):
            self._vars["status"].set("转换失败")
            self._log("一键转换失败：" + str(result))
            messagebox.showerror("一键转换失败", str(result))
            return
        self.project, self.project_path, manifest = result["project"], result["project_path"], result["manifest"]
        self.selected_shot = self.project["shots"][0]["shot_id"]
        self._vars["outputs"].set(str(len(manifest.get("outputs", []))))
        self._refresh_all()
        self._log("白模预览已生成：" + result["video"])
        missing = self.project.get("analysis", {}).get("shots_without_pose", [])
        review = "\n无可靠完整人体姿态的镜头：" + "、".join(missing) + "（场景或人物局部待补充）" if missing else ""
        self._set_text(self.flow_text, "\n".join(self._conversion_log[-10:]) + "\n\n预览：" + result["video"] +
                       "\n\n" + "\n".join(self.project.get("analysis", {}).get("limitations", [])) + review)
        self.show_page('library')
        self.gallery.refresh(select_video=result['video'])
        self._log('新白模已加入仓库，可直接播放和继续编辑；遮挡、接触、相机和场景仍需复核。')

    def open_whiteblock_preview(self):
        value = (self.project or {}).get("whiteblock_preview_path")
        if not value or not Path(value).is_file(): return self._notice("当前项目尚未生成完整白模预览，请先一键转换")
        self.show_page('library')
        self.gallery.select_video(value)
        if self.gallery.player.path==value:self.gallery.player.toggle()
        else:self.gallery.refresh(select_video=value)

    def open_output_folder(self):
        if not self.project: return self._notice("请先打开项目")
        self.agent_open_exports()


    def show_page(self, name):
        if hasattr(self,'gallery') and name!='library':self.gallery.player.pause()
        for page in self.pages.values(): page.pack_forget()
        for key, button in self.nav_buttons.items():
            active = key == name
            button.configure(bg=PANEL_3 if active else PANEL, fg=ACCENT_HOVER if active else TEXT, activebackground=PANEL_3 if active else PANEL_2)
        self.pages[name].pack(fill="both", expand=True); self._refresh_all()
        if name=='library':self.gallery.refresh()

    def _open_library_project(self, entry):
        if self._busy:return self._notice('当前任务正在运行，请等待完成后再切换项目')
        try:
            path=Path(entry['project_path']);project=load_project(path)
            self.project,self.project_path=project,path
            self.selected_shot=entry.get('shot_id') or project['shots'][0]['shot_id']
            self._vars['outputs'].set(str(len(project.get('last_manifest',{}).get('outputs',[]))))
            self.show_page('shots');self._log('已加载仓库中的项目，可修改镜头或在 Blender 中继续编辑。')
        except Exception as exc:self._notice('项目打开失败：'+str(exc))

    def _set_text(self, widget, text):
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("end", text); widget.configure(state="disabled")

    def _refresh_all(self):
        if not self.project:
            self._vars["project"].set("未打开项目"); self._vars["status"].set("待开始"); self._vars["source"].set("未导入视频"); self._vars["media"].set("等待探测"); self._vars["shot_count"].set("0"); return
        p = self.project; self._vars["project"].set(p["project_id"])
        status = p.get("status", "ready")
        self._vars["status"].set({"ready": "就绪", "needs_review": "待复核", "analyzing": "分析中", "exporting": "渲染中", "exported": "已导出", "failed": "失败", "packaged": "已生成请求包"}.get(status, status))
        self._vars["source"].set(Path(p["source"]["path"]).name); media = p.get("media", {}); self._vars["media"].set(f"{media.get('width') or '?'} × {media.get('height') or '?'} / {media.get('fps', '?')} fps"); self._vars["shot_count"].set(str(len(p.get("shots", []))))
        self._refresh_shots();self._refresh_actor_templates(); history = p.get("history", []); lines = [f"[{h.get('status')}] {h.get('message', '')}" for h in history[-8:]]; self._set_text(self.flow_text, "\n".join(lines) or "等待操作")

    def _refresh_shots(self):
        if not hasattr(self, "shot_tree"): return
        for item in self.shot_tree.get_children(): self.shot_tree.delete(item)
        for shot in (self.project or {}).get("shots", []): self.shot_tree.insert("", "end", iid=shot["shot_id"], values=(shot.get("name", shot["shot_id"]), f"{shot['start_frame']} - {shot['end_frame']}", shot.get("fps", 30), shot.get("status", "ready")))
        if self.selected_shot and self.shot_tree.exists(self.selected_shot): self.shot_tree.selection_set(self.selected_shot)

    def on_shot_select(self, _event=None):
        selected = self.shot_tree.selection()
        if not selected or not self.project: return
        self.selected_shot = selected[0]; shot = next((s for s in self.project["shots"] if s["shot_id"] == self.selected_shot), None)
        if shot:
            for key, var in self.shot_fields.items(): var.set(str(shot.get(key, "")))
            self._refresh_actor_templates()

    def new_project(self):
        source = filedialog.askopenfilename(title="选择短剧源视频", filetypes=(("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", "*.*")))
        if not source: return
        project_id = simpledialog.askstring("新建项目", "项目 ID（英文、数字、下划线）：", initialvalue="project_001", parent=self)
        if not project_id: return
        workspace = filedialog.askdirectory(title="选择项目工作区", initialdir=str(Path(source).parent))
        if not workspace: return
        try:
            self.project = create_project(Path(source), project_id, workspace=Path(workspace)); self.project_path = Path(workspace) / "projects" / (project_id + ".json"); save_project(self.project_path, self.project); self.selected_shot = "shot_001"; self._log("项目已创建：" + str(self.project_path)); self._refresh_all()
        except Exception as exc: messagebox.showerror("创建失败", str(exc))

    def open_project(self):
        path = filedialog.askopenfilename(title="打开项目 JSON", filetypes=(("Project JSON", "*.json"), ("All", "*.*")))
        if not path: return
        try: self.project_path = Path(path); self.project = load_project(self.project_path); self.selected_shot = self.project["shots"][0]["shot_id"]; self._log("已打开项目：" + path); self._refresh_all()
        except Exception as exc: messagebox.showerror("打开失败", str(exc))

    def save_current(self):
        if not self.project: return self._notice("请先打开项目")
        if not self.project_path: self.project_path = Path(self.project["workspace_root"]) / "projects" / (self.project["project_id"] + ".json")
        save_project(self.project_path, self.project); self._log("项目已保存")

    def import_video(self):
        if not self.project: return self.new_project()
        source = filedialog.askopenfilename(title="替换源视频", filetypes=(("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", "*.*")))
        if not source: return
        try:
            replacement = create_project(Path(source), self.project["project_id"], workspace=Path(self.project["workspace_root"])); self.project["source"], self.project["media"] = replacement["source"], replacement["media"]; self.project["shots"][0].update({"end_frame": replacement["shots"][0]["end_frame"], "fps": replacement["shots"][0]["fps"]}); set_status(self.project, "ready", "已替换源视频并重新计算媒体信息"); self.save_current(); self._refresh_all()
        except Exception as exc: messagebox.showerror("导入失败", str(exc))

    def add_shot(self):
        if not self.project: return self._notice("请先打开项目")
        index = len(self.project["shots"]) + 1; sid = f"shot_{index:03d}"; previous = self.project["shots"][-1]; self.project["shots"].append({"shot_id": sid, "name": f"镜头 {index:03d}", "start_frame": previous["end_frame"] + 1, "end_frame": previous["end_frame"] + 90, "fps": previous.get("fps", 30), "revision": 1, "status": "ready", "actors": [], "props": []}); self.selected_shot = sid; self.save_current(); self._refresh_all()

    def remove_shot(self):
        if not self.project or len(self.project["shots"]) <= 1: return self._notice("至少保留一个镜头")
        sid = self.selected_shot; self.project["shots"] = [s for s in self.project["shots"] if s["shot_id"] != sid]; self.selected_shot = self.project["shots"][0]["shot_id"]; self.save_current(); self._refresh_all()

    def update_shot(self):
        if not self.project or not self.selected_shot: return
        shot = next(s for s in self.project["shots"] if s["shot_id"] == self.selected_shot); old_id = shot["shot_id"]
        try:
            for key in ("start_frame", "end_frame", "fps"): shot[key] = int(self.shot_fields[key].get())
            shot["name"] = self.shot_fields["name"].get().strip() or old_id; set_status(self.project, "needs_review", f"已人工修改 {old_id}"); self.save_current(); self._refresh_all()
        except Exception as exc: self._notice("镜头参数无效：" + str(exc))

    def build_whiteblock(self):
        if not self.project or not self.project_path: return self._notice("请先打开或新建项目")
        out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; set_status(self.project, "exporting", "正在生成场景规格和 Blender 脚本"); self.save_current(); self._set_busy(True)
        self._run_async(lambda: run(self.project_path, out), lambda result: self._build_done(result, out))

    def _build_done(self, result, out):
        if isinstance(result, Exception): set_status(self.project, "failed", str(result)); self._log("白模生成失败：" + str(result)); messagebox.showerror("白模生成失败", str(result))
        else: self.project["last_manifest"] = result; set_status(self.project, "exported", f"已生成 {len(result.get('outputs', []))} 个文件"); self.save_current(); self._log("白模生成完成：" + str(out)); self._vars["outputs"].set(str(len(result.get("outputs", []))))
        self._set_busy(False); self._refresh_all()

    def run_blender_current(self):
        if not self.project: return self._notice("请先打开项目")
        shot = next((s for s in self.project["shots"] if s["shot_id"] == self.selected_shot), self.project["shots"][0]); out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; script = out / (shot["shot_id"] + ".blender.py")
        if not script.exists():
            self.build_whiteblock(); return
        blender_bin = self.project.get("settings", {}).get("blender_path") or os.getenv("BLENDER_BIN") or find_blender()
        if not blender_bin: return self._notice("未检测到本地 Blender。请设置 BLENDER_BIN，或让 Agent 执行：设置 Blender 路径 <路径>")
        set_status(self.project, "exporting", "正在调用本地 Blender 创建 .blend"); self.save_current(); self._set_busy(True)
        self._run_async(lambda: run_blender_script(script, blender_bin=blender_bin), lambda result: self._blender_done(result, blender_bin))

    def _blender_done(self, result, blender_bin):
        if isinstance(result, Exception): set_status(self.project, "failed", str(result)); self._log("本地 Blender 执行失败：" + str(result)); messagebox.showerror("Blender 执行失败", str(result))
        else: set_status(self.project, "exported", "已由本地 Blender 创建白模工程"); self.save_current(); self._log("本地 Blender 已执行：" + blender_bin)
        self._set_busy(False); self._refresh_all()

    def build_package(self):
        if not self.project: return self._notice("请先打开项目")
        shot = next((s for s in self.project["shots"] if s["shot_id"] == self.selected_shot), self.project["shots"][0]); self.project.setdefault("settings", {}).update({"eggfans_base_url": self.app_config["eggfans"].get("base_url", "https://api.eggfans.com"), "eggfans_model": self.app_config["eggfans"].get("model", "seedance-2.5")}); out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; prompt = self.prompt.get("1.0", "end").strip() or "保持角色、场景、道具和镜头运动一致"
        self._set_busy(True); self._run_async(lambda: build_seedance_request(self.project, shot, out, prompt), lambda result: self._package_done(result))

    def _package_done(self, result):
        if isinstance(result, Exception): self._log("请求包失败：" + str(result)); messagebox.showerror("请求包失败", str(result))
        else: set_status(self.project, "packaged", "已生成离线 Seedance 请求包"); self.save_current(); self._set_text(self.package_log, json.dumps(result["request"], ensure_ascii=False, indent=2) + "\n\n文件：" + result["path"]); self._log("请求包已生成（仍需渲染/确认后才能上传）")
        self._set_busy(False); self._refresh_all()

    def _agent_tools(self):
        return {"project_status": self.agent_status, "import_source": self.agent_import_source, "build_whiteblock": self.agent_build, "run_blender": self.agent_run_blender, "package_seedance": self.agent_package, "save_project": self.agent_save, "select_shot": self.agent_select, "update_shot": self.agent_update_shot, "add_shot": self.agent_add_shot, "remove_shot": self.agent_remove_shot, "set_blender_path": self.agent_set_blender_path, "open_exports": self.agent_open_exports,
                'list_whiteblocks':self.agent_list_whiteblocks,'open_whiteblock_library':self.agent_open_library,
                'list_actor_profiles':self.agent_actor_profiles,'set_actor_template':self.agent_set_actor_template,
                'blender_connect':self.agent_blender_connect,'blender_scene':self.agent_blender_scene,'blender_check':self.agent_blender_check,
                'blender_preview':lambda:self.blender_session.call('get_preview'),'blender_set_frame':lambda frame:self.blender_session.call('set_frame',frame=frame),
                'blender_set_ik':lambda actor,limb,position:self.blender_session.call('set_ik_target',actor=actor,limb=limb,position=position),
                'blender_set_camera':lambda **args:self.blender_session.call('set_camera',**args),
                'blender_pose':lambda **args:self.blender_session.call('pose_preset',**args),
                'blender_template':self.agent_blender_template,
                'blender_save_revision':lambda:self.blender_session.call('save_revision'),'blender_render':self.agent_blender_render}

    def connect_library_blender(self,item):
        if not item or not item.get('project_path'):return self._notice('此历史预览缺少可编辑项目')
        self._open_library_project(item)
        if not item.get('shot_id'):
            shot=next((s for s in self.project['shots'] if s.get('actors')),self.project['shots'][0]);self.selected_shot=shot['shot_id']
        self.show_page('whiteblock');self.blender_button_task(self.agent_blender_connect)

    def blender_button_task(self,work):
        if self._busy:return self._notice('当前任务运行中，请等待完成')
        self._set_busy(True);self.mcp_status.set('Blender MCP 正在执行…')
        self._run_async(work,self._blender_live_done)

    def _blender_live_done(self,result):
        self._set_busy(False)
        if isinstance(result,Exception):self.mcp_status.set('Blender MCP：'+str(result));self._log(str(result));return
        self.mcp_status.set('Blender MCP 已连接 · 修订会另存，旧版保留')
        self._set_text(self.build_log,json.dumps(result,ensure_ascii=False,indent=2));self._log('Blender 操作完成')

    def agent_blender_connect(self):
        if not self.project:raise ValueError('请先打开仓库中的项目')
        shot=next((s for s in self.project['shots'] if s['shot_id']==self.selected_shot),self.project['shots'][0])
        blend=shot.get('whiteblock_blend_path') or str(Path(self.project['workspace_root'])/'exports'/self.project['project_id']/(shot['shot_id']+'.blend'))
        key=(str(self.project_path),shot['shot_id'])
        if key!=(self._blender_project_path,self._blender_shot_id):self.blender_session.close()
        result=self.blender_session.start(blend,self.project.get('settings',{}).get('blender_path'))
        actual={a['id']:a for a in result['actors']}
        for profile in actor_profiles(self.project,shot['shot_id']):
            current=actual.get(profile['id'])
            if profile['template_confirmed'] and current and any(current.get(key)!=profile[key] for key in ('body_template','template_confirmed','role_name')):
                self.blender_session.call('set_body_template',actor=profile['id'],template=profile['body_template'],role_name=profile['role_name'])
        result=self.blender_session.call('get_scene_summary')
        self._blender_project_path,self._blender_shot_id=key
        self._queue.put((lambda _:self.mcp_status.set('Blender MCP 已连接 · '+shot['shot_id']),None))
        return result

    def agent_blender_scene(self):return self.blender_session.call('get_scene_summary')
    def blender_agent_context(self):
        context={'project':self.project.get('project_id') if self.project else None,'shot':self.selected_shot}
        if self.project and self.selected_shot:context['actor_templates']=actor_profiles(self.project,self.selected_shot)
        if self.blender_session.client:
            try:context['blender']=self.agent_blender_scene()
            except Exception as exc:context['blender_error']=str(exc)
        return context
    def agent_blender_check(self):return self.blender_session.call('check_intersections')
    def agent_blender_render(self):
        if not self.project:raise ValueError('请先打开项目')
        self.agent_blender_connect()
        result=self.blender_session.render_revision(self._blender_project_path,self._blender_shot_id,
             progress=lambda e:self._queue.put((lambda event:self._append_agent_log('Blender 渲染：'+str(event)),e)))
        self._queue.put((lambda value:(self.show_page('library'),self.gallery.refresh(select_video=value['video'])),result))
        return result

    def agent_actor_profiles(self):
        if not self.project:raise ValueError('请先打开项目')
        return {'shot_id':self.selected_shot,'actors':actor_profiles(self.project,self.selected_shot)}

    def agent_set_actor_template(self,actor,template,shot_id=None,role_name=None):
        if not self.project:raise ValueError('请先打开项目')
        sid=shot_id or self.selected_shot
        result=update_actor_template(self.project,sid,actor,template,role_name)
        self.selected_shot=sid;self.agent_save()
        self._queue.put((lambda _:self._refresh_actor_templates(),None));return result

    def agent_blender_template(self,actor,template,role_name=None):
        if (str(self.project_path),self.selected_shot)!=(self._blender_project_path,self._blender_shot_id):self.agent_blender_connect()
        result=self.blender_session.call('set_body_template',actor=actor,template=template,role_name=role_name)
        self.agent_set_actor_template(actor,template,self.selected_shot,role_name);return result

    def agent_list_whiteblocks(self):
        from .library import load_library
        entries=load_library(default_workspace())
        return {'count':len(entries),'videos':[{key:e.get(key) for key in ('source_name','name','video','geometry_profile')} for e in entries]}

    def agent_open_library(self):
        self._queue.put((lambda _:self.show_page('library'),None))
        return {'page':'白模仓库'}

    def agent_status(self): return {"project": self.project.get("project_id") if self.project else None, "status": self.project.get("status") if self.project else "待开始", "shots": len(self.project.get("shots", [])) if self.project else 0, "blender": find_blender(self.project.get("settings", {}).get("blender_path")) if self.project else find_blender()}
    def agent_import_source(self, path: str):
        source = Path(path).expanduser().resolve()
        project_id = self.project["project_id"] if self.project else source.stem.replace(" ", "_")[:40] or "project_001"
        workspace = Path(self.project["workspace_root"]) if self.project else default_workspace()
        replacement = create_project(source, project_id, workspace=workspace)
        if self.project:
            self.project["source"], self.project["media"] = replacement["source"], replacement["media"]; self.project["shots"][0].update({"end_frame": replacement["shots"][0]["end_frame"], "fps": replacement["shots"][0]["fps"]}); set_status(self.project, "ready", "Agent 已替换源视频")
        else:
            self.project = replacement; self.project_path = workspace / "projects" / (project_id + ".json"); self.selected_shot = "shot_001"
        save_project(self.project_path or (workspace / "projects" / (project_id + ".json")), self.project); return {"project": project_id, "source": str(source)}
    def agent_build(self):
        if not self.project_path: raise ValueError("请先打开项目")
        out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; result = run(self.project_path, out); self.project["last_manifest"] = result; set_status(self.project, "exported", "Agent 已生成白模脚本"); save_project(self.project_path, self.project); return {"outputs": len(result["outputs"]), "directory": str(out)}
    def agent_package(self):
        if not self.project: raise ValueError("请先打开项目")
        shot = next((s for s in self.project["shots"] if s["shot_id"] == self.selected_shot), self.project["shots"][0]); out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; result = build_seedance_request(self.project, shot, out); set_status(self.project, "packaged", "Agent 已生成离线请求包"); save_project(self.project_path, self.project); return {"path": result["path"], "media_status": result["request"]["media_status"]}
    def agent_run_blender(self):
        if not self.project: raise ValueError("请先打开项目")
        out = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; shot = next((s for s in self.project["shots"] if s["shot_id"] == self.selected_shot), self.project["shots"][0]); script = out / (shot["shot_id"] + ".blender.py"); blender_bin = self.project.get("settings", {}).get("blender_path") or os.getenv("BLENDER_BIN") or find_blender()
        if not blender_bin: raise FileNotFoundError("E_BLENDER_NOT_FOUND: set BLENDER_BIN or use set_blender_path")
        result = run_blender_script(script, blender_bin=blender_bin); set_status(self.project, "exported", "Agent 已执行 Blender 脚本"); save_project(self.project_path, self.project); return result
    def agent_save(self):
        if not self.project: raise ValueError("请先打开项目")
        path = self.project_path or (Path(self.project["workspace_root"]) / "projects" / (self.project["project_id"] + ".json"))
        save_project(path, self.project); self.project_path = path; return "saved"
    def agent_select(self, shot_id: str):
        value = str(shot_id).lower().replace("-", "_"); normalized = value if value.startswith("shot_") else f"shot_{int(value):03d}"
        if not self.project or not any(s["shot_id"] == normalized for s in self.project["shots"]): raise ValueError("不存在镜头 " + normalized)
        self.selected_shot = normalized; return normalized
    def agent_update_shot(self, shot_id: str, start_frame: int | None = None, end_frame: int | None = None, fps: int | None = None, name: str | None = None):
        normalized = shot_id if str(shot_id).startswith("shot_") else f"shot_{int(shot_id):03d}"
        if not self.project: raise ValueError("请先打开项目")
        shot = next((s for s in self.project["shots"] if s["shot_id"] == normalized), None)
        if not shot: raise ValueError("不存在镜头 " + normalized)
        if start_frame is not None: shot["start_frame"] = int(start_frame)
        if end_frame is not None: shot["end_frame"] = int(end_frame)
        if fps is not None: shot["fps"] = int(fps)
        if name is not None: shot["name"] = str(name)
        set_status(self.project, "needs_review", f"Agent 已修改 {normalized}"); save_project(self.project_path, self.project); return shot
    def agent_add_shot(self):
        if not self.project: raise ValueError("请先打开项目")
        index = len(self.project["shots"]) + 1; sid = f"shot_{index:03d}"; previous = self.project["shots"][-1]
        self.project["shots"].append({"shot_id": sid, "name": f"镜头 {index:03d}", "start_frame": previous["end_frame"] + 1, "end_frame": previous["end_frame"] + 90, "fps": previous.get("fps", 30), "revision": 1, "status": "ready", "actors": [], "props": []})
        self.selected_shot = sid; save_project(self.project_path, self.project); return sid
    def agent_remove_shot(self):
        if not self.project or len(self.project["shots"]) <= 1: raise ValueError("至少保留一个镜头")
        removed = self.selected_shot; self.project["shots"] = [s for s in self.project["shots"] if s["shot_id"] != removed]; self.selected_shot = self.project["shots"][0]["shot_id"]; save_project(self.project_path, self.project); return removed
    def agent_set_blender_path(self, path: str):
        if not self.project: raise ValueError("请先打开项目")
        self.project.setdefault("settings", {})["blender_path"] = str(Path(path).expanduser().resolve()); save_project(self.project_path, self.project); return self.project["settings"]["blender_path"]
    def agent_open_exports(self):
        if not self.project: raise ValueError("请先打开项目")
        path = Path(self.project["workspace_root"]) / "exports" / self.project["project_id"]; path.mkdir(parents=True, exist_ok=True); os.startfile(path); return str(path)

    def show_agent(self):
        if hasattr(self, "agent_window") and self.agent_window.winfo_exists(): self.agent_window.deiconify(); self.agent_window.lift(); return
        win = self.agent_window = tk.Toplevel(self); win.title("Agent 控制台"); win.geometry("440x600"); win.configure(bg=PANEL); win.attributes("-topmost", True)
        bar = tk.Frame(win, bg=PANEL_2, height=40); bar.pack(fill="x"); tk.Label(bar, text="  AGENT / 项目操作员", bg=PANEL_2, fg=TEXT, font=("Bahnschrift", 11, "bold")).pack(side="left", pady=10); tk.Button(bar, text="×", command=win.withdraw, bg=PANEL_2, fg=MUTED, relief="flat", font=("Arial", 16)).pack(side="right", padx=8)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        drag = {"x": 0, "y": 0}
        bar.bind("<ButtonPress-1>", lambda e: drag.update(x=e.x_root - win.winfo_x(), y=e.y_root - win.winfo_y())); bar.bind("<B1-Motion>", lambda e: win.geometry(f"+{e.x_root-drag['x']}+{e.y_root-drag['y']}"))
        status_row = tk.Frame(win, bg=PANEL); status_row.pack(fill="x", padx=14, pady=(10, 2))
        self.agent_status_label = tk.Label(status_row, textvariable=self._vars["agent_status"], bg=PANEL, fg=ACCENT, anchor="w", font=("Microsoft YaHei UI", 10, "bold")); self.agent_status_label.pack(side="left")
        tk.Label(status_row, textvariable=self._vars["agent"], bg=PANEL, fg=MUTED, anchor="e", font=("Microsoft YaHei UI", 8)).pack(side="right")
        self.agent_progress = ttk.Progressbar(win, style="Agent.Horizontal.TProgressbar", mode="indeterminate", length=410)
        self.agent_progress.pack(fill="x", padx=14, pady=(2, 5))
        tk.Label(win, text="运行日志", bg=PANEL, fg=MUTED, anchor="w", padx=14, font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x", pady=(2, 0))
        log = tk.Text(win, height=5, bg=PANEL_2, fg=TEXT, relief="flat", bd=0, wrap="word", padx=10, pady=7, state="disabled", font=("Consolas", 8)); log.pack(fill="x", padx=12, pady=(2, 6)); self.agent_log = log
        self._render_agent_log()
        chat = tk.Text(win, bg=BG, fg=TEXT, relief="flat", bd=0, wrap="word", padx=14, pady=12, state="disabled"); chat.pack(fill="both", expand=True, padx=12, pady=8); self.agent_chat = chat
        entry = tk.Entry(win, bg=PANEL_2, fg=TEXT, insertbackground=TEXT, relief="flat"); entry.pack(fill="x", padx=12, pady=(0, 8), ipady=9); self.agent_entry = entry; entry.bind("<Return>", lambda _e: self.send_agent())
        self.agent_send_button = tk.Button(win, text="执行", command=self.send_agent, bg=ACCENT, fg="#101510", relief="flat", font=("Microsoft YaHei UI", 10, "bold")); self.agent_send_button.pack(anchor="e", padx=12, pady=(0, 12), ipadx=16, ipady=6)
        self._agent_append("系统", "我可以直接操控项目流程，但不具备编码工具。当前：" + ("在线模型已启用" if self._agent.config.enabled and self._agent.config.api_key else "离线工具模式"))
        self._set_agent_running(self._agent_running, self._vars["agent_status"].get())

    def send_agent(self):
        text = self.agent_entry.get().strip() if hasattr(self, "agent_entry") else ""
        if not text: return
        if self._agent_running:
            self._append_agent_log("已有任务运行中，请等待当前任务完成")
            return
        self.agent_entry.delete(0, "end"); self._agent_append("你", text); self._set_agent_running(True, "正在运行 · 正在规划")
        self._append_agent_log("正在规划请求")
        self._run_async(lambda: self._agent.execute(text, progress=lambda event: self._queue.put((self._agent_progress_event, event))), self._agent_done)

    def _agent_progress_event(self, event):
        kind = event.get("event")
        if kind == "planning":
            self._set_agent_running(True, "正在运行 · 正在规划")
            self._append_agent_log("正在规划请求")
        elif kind == "planned":
            count = int(event.get("count", 0))
            self._set_agent_running(True, "正在运行 · " + ("正在执行" if count else "正在处理"))
            self._append_agent_log(f"已识别 {count} 个操作")
        elif kind == "tool_start":
            tool = str(event.get("tool", "未知工具"))
            self._set_agent_running(True, f"正在运行 · 正在执行：{tool}")
            self._append_agent_log(f"开始执行：{tool}")
        elif kind == "tool_done":
            tool = str(event.get("tool", "未知工具")); ok = bool(event.get("ok"))
            self._append_agent_log(("完成：" if ok else "失败：") + tool + ("" if ok else " · " + str(event.get("error", "未知错误"))))
        elif kind == "completed":
            ok = bool(event.get("ok"))
            self._set_agent_running(False, "已完成" if ok else "执行失败")
            self._append_agent_log("Agent 执行完成" if ok else "Agent 执行失败")

    def _set_agent_running(self, running: bool, status: str):
        self._agent_running = bool(running)
        self._vars["agent_status"].set(status)
        self._busy = bool(running) or self._conversion_running
        if hasattr(self, "statusbar"):
            self.statusbar.configure(text=f"Agent：{status}" if running or status != "空闲" else "离线模式：不会上传素材或调用远程模型")
        if hasattr(self, "agent_progress") and self.agent_progress.winfo_exists():
            if running: self.agent_progress.start(12)
            else: self.agent_progress.stop()
        if hasattr(self, "agent_send_button") and self.agent_send_button.winfo_exists():
            self.agent_send_button.configure(state="disabled" if running else "normal")
        if hasattr(self, "agent_entry") and self.agent_entry.winfo_exists():
            self.agent_entry.configure(state="disabled" if running else "normal")

    def _append_agent_log(self, message: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self._agent_log_lines.append(line)
        self._agent_log_lines = self._agent_log_lines[-80:]
        self._render_agent_log()

    def _render_agent_log(self):
        if not hasattr(self, "agent_log") or not self.agent_log.winfo_exists():
            return
        self.agent_log.configure(state="normal")
        self.agent_log.delete("1.0", "end")
        self.agent_log.insert("end", "\n".join(self._agent_log_lines))
        self.agent_log.see("end")
        self.agent_log.configure(state="disabled")

    def _agent_done(self, result):
        if isinstance(result, Exception):
            self._set_agent_running(False, "执行失败")
            self._append_agent_log("Agent 执行失败：" + str(result))
            self._agent_append("Agent", "执行失败：" + str(result))
        else:
            lines = [result["reply"]]
            for item in result["actions"]: lines.append(("✓ " if item["ok"] else "× ") + item["tool"] + "：" + json.dumps(item.get("result", item.get("error")), ensure_ascii=False))
            self._agent_append("Agent", "\n".join(lines)); self._refresh_all()
            ok = all(item.get("ok", False) for item in result.get("actions", []))
            self._set_agent_running(False, "已完成" if ok else "执行失败")

    def _agent_append(self, who, text):
        if not hasattr(self, "agent_chat"): return
        self.agent_chat.configure(state="normal"); self.agent_chat.insert("end", f"{who}\n{text}\n\n"); self.agent_chat.see("end"); self.agent_chat.configure(state="disabled")
    def _log(self, text): self.statusbar.configure(text=text); 
    def _notice(self, text): self._log(text); messagebox.showinfo("提示", text)
    def _set_busy(self, busy): self._busy = busy; self.statusbar.configure(text="处理中…" if busy else "离线模式：不会上传素材或调用远程模型")
    def _run_async(self, work, done):
        def runner():
            try: value = work()
            except Exception as exc: value = exc
            self._queue.put((done, value))
        threading.Thread(target=runner, daemon=True).start()
    def _poll_queue(self):
        try:
            while True: callback, value = self._queue.get_nowait(); callback(value)
        except queue.Empty: pass
        self._poll_timer = self.after(100, self._poll_queue)

    def destroy(self):
        self.blender_session.close()
        if self._poll_timer:
            self.after_cancel(self._poll_timer);self._poll_timer=None
        super().destroy()

def main():
    app = WhiteblockApp(); app.mainloop()

if __name__ == "__main__": main()
