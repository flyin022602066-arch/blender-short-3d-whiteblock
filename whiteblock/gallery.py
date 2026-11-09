"""Local whiteblock browser with an embedded, seekable video player."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from .config import load_config
from .library import load_library, refresh_library
from .pipeline import find_blender, media_tool

BG, PANEL, TEXT, MUTED, ACCENT = '#0d1217','#151c23','#edf5f7','#91a2ae','#b8e85b'


def clock_text(seconds):
    seconds=max(0,int(seconds))
    return f'{seconds//60:02d}:{seconds%60:02d}'


class VideoPreview(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, style='Panel.TFrame')
        self.capture=None;self.path=None;self.frame_index=0;self.playing=False
        self._timer=None;self._image=None;self._frame=None;self._updating=False
        self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0,height=180)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.canvas.bind('<Configure>',lambda e:self._draw())
        self.canvas.bind('<Button-1>',lambda e:(self.canvas.focus_set(),self.toggle()))
        self.canvas.bind('<space>',lambda e:self.toggle())
        self.canvas.bind('<Left>',lambda e:self.seek(self.frame_index/self.fps-1) if self.capture else None)
        self.canvas.bind('<Right>',lambda e:self.seek(self.frame_index/self.fps+1) if self.capture else None)
        bar=ttk.Frame(self,style='Panel.TFrame');bar.grid(row=1,column=0,sticky='ew',pady=(10,2))
        self.play_button=ttk.Button(bar,text='播放',style='Accent.TButton',command=self.toggle,state='disabled')
        self.play_button.pack(side='left')
        self.time_var=tk.StringVar(value='00:00 / 00:00')
        ttk.Label(bar,textvariable=self.time_var,style='PanelMuted.TLabel').pack(side='right')
        self.position=tk.DoubleVar(value=0)
        style=ttk.Style(self)
        style.configure('Preview.Horizontal.TScale',background=ACCENT,troughcolor='#344452',
                        bordercolor=PANEL,lightcolor=ACCENT,darkcolor=ACCENT,sliderlength=18)
        style.map('Preview.Horizontal.TScale',background=[('disabled','#52616d'),('active','#d5fa86')])
        self.slider=ttk.Scale(self,from_=0,to=1,variable=self.position,command=self.seek,style='Preview.Horizontal.TScale')
        self.slider.grid(row=2,column=0,sticky='ew',pady=(6,0));self.slider.state(['disabled'])
        self.slider.bind('<MouseWheel>',self._wheel_seek)
        self._draw()

    def load(self,path):
        self.close()
        import cv2
        cap=cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release();raise ValueError('视频无法打开，请刷新仓库或检查文件：'+str(path))
        self.capture=cap;self.path=str(path);self.fps=cap.get(cv2.CAP_PROP_FPS) or 24
        self.frame_count=max(1,int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.slider.configure(to=max(0,(self.frame_count-1)/self.fps));self.slider.state(['!disabled'])
        self.play_button.configure(state='normal',text='播放')
        self.seek(0)

    def _read(self,index):
        import cv2
        if self.capture is None:return
        index=max(0,min(self.frame_count-1,int(index)))
        current=int(self.capture.get(cv2.CAP_PROP_POS_FRAMES))
        if index!=current:self.capture.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,frame=self.capture.read()
        if not ok:
            self.pause();return
        self.frame_index=index
        self._frame=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        self._updating=True;self.position.set(index/self.fps);self._updating=False
        self.time_var.set(clock_text(index/self.fps)+' / '+clock_text(self.frame_count/self.fps))
        self._draw()

    def _draw(self):
        if not self.canvas.winfo_exists():return
        width,height=max(20,self.canvas.winfo_width()),max(20,self.canvas.winfo_height())
        self.canvas.delete('all')
        if self._frame is None:
            self.canvas.create_text(width/2,height/2,text='选择左侧白模查看预览',fill=MUTED,font=('Microsoft YaHei UI',11))
            return
        frame=self._frame.copy();frame.thumbnail((width-12,height-12),Image.Resampling.LANCZOS)
        self._image=ImageTk.PhotoImage(frame,master=self)
        self.canvas.create_image(width/2,height/2,image=self._image)

    def seek(self,seconds):
        if self._updating or self.capture is None:return
        self.pause();self._read(round(float(seconds)*self.fps))

    def _wheel_seek(self,event):
        if self.capture is not None and event.delta:
            steps=round(event.delta/120) or (1 if event.delta>0 else -1)
            self.seek(self.frame_index/self.fps+steps)
        return 'break'

    def toggle(self):
        if self.capture is None:return
        if self.playing:self.pause();return
        if self.frame_index>=self.frame_count-1:self._read(0)
        self.playing=True;self.play_button.configure(text='暂停')
        self._start=time.monotonic()-self.frame_index/self.fps
        self._tick()

    def _tick(self):
        self._timer=None
        if not self.playing:return
        target=min(self.frame_count-1,int((time.monotonic()-self._start)*self.fps))
        if target!=self.frame_index:self._read(target)
        if target>=self.frame_count-1:self.pause();return
        self._timer=self.after(15,self._tick)

    def pause(self):
        self.playing=False
        if self._timer:
            self.after_cancel(self._timer);self._timer=None
        if self.play_button.winfo_exists():self.play_button.configure(text='播放')

    def close(self):
        self.pause()
        if self.capture is not None:self.capture.release()
        self.capture=None;self.path=None;self._frame=None;self._image=None;self.frame_index=0
        if self.slider.winfo_exists():self.slider.state(['disabled'])
        if self.play_button.winfo_exists():self.play_button.configure(state='disabled')
        self.position.set(0);self.time_var.set('00:00 / 00:00');self._draw()

    def destroy(self):
        self.close();super().destroy()


class WhiteblockGallery(ttk.Frame):
    def __init__(self,master,workspace,run_async,open_project,open_live=None):
        super().__init__(master,style='Panel.TFrame')
        self.workspace=Path(workspace);self._run_async=run_async;self._open_project=open_project
        self._open_live=open_live
        self.entries=load_library(self.workspace);self.selected=None;self._refreshing=False;self._thumbs=[];self._pending_video=None
        self.columnconfigure(0,weight=1);self.rowconfigure(2,weight=1)
        header=ttk.Frame(self,style='Panel.TFrame');header.grid(row=0,column=0,sticky='ew',padx=22,pady=(20,10))
        ttk.Label(header,text='白模仓库',style='Title.TLabel').pack(side='left')
        self.summary=tk.StringVar(value='历史预览自动归档')
        ttk.Label(header,textvariable=self.summary,style='PanelMuted.TLabel').pack(side='left',padx=14)
        self.refresh_button=ttk.Button(header,text='刷新仓库',style='Quiet.TButton',command=self.refresh)
        self.refresh_button.pack(side='right')
        filters=ttk.Frame(self,style='Panel.TFrame');filters.grid(row=1,column=0,sticky='ew',padx=22,pady=(0,12))
        self.search=tk.StringVar();self.kind=tk.StringVar(value='完整视频')
        ttk.Label(filters,text='搜索',style='PanelMuted.TLabel').pack(side='left',padx=(0,8))
        entry=ttk.Entry(filters,textvariable=self.search,width=30);entry.pack(side='left',fill='x',expand=True)
        self.search.trace_add('write',lambda *args:self._render_entries())
        combo=ttk.Combobox(filters,textvariable=self.kind,values=['完整视频','单个镜头','全部'],state='readonly',width=10)
        combo.pack(side='left',padx=(12,0));combo.bind('<<ComboboxSelected>>',lambda e:self._render_entries())
        area=ttk.Frame(self,style='Panel.TFrame');area.grid(row=2,column=0,sticky='nsew',padx=22,pady=(0,18))
        area.columnconfigure(0,weight=4,minsize=300);area.columnconfigure(1,weight=6,minsize=320);area.rowconfigure(0,weight=1)
        left=ttk.Frame(area,style='Panel.TFrame');left.grid(row=0,column=0,sticky='nsew',padx=(0,16))
        left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1)
        self.tree=ttk.Treeview(left,columns=('info',),show='tree headings',style='Gallery.Treeview',selectmode='browse')
        self.tree.heading('#0',text='预览 / 原片');self.tree.heading('info',text='时长 / 版本')
        self.tree.column('#0',width=260,minwidth=190);self.tree.column('info',width=90,minwidth=80,stretch=False)
        self.tree.grid(row=0,column=0,sticky='nsew')
        scrollbar=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview);scrollbar.grid(row=0,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>',self._select);self.tree.bind('<Double-1>',lambda e:self.player.toggle())
        self.tree.bind('<MouseWheel>',lambda e:self.tree.yview_scroll(-int(e.delta/120),'units'))
        self.empty=ttk.Label(left,text='暂无白模；完成一键转换后会自动出现在这里。',style='PanelMuted.TLabel',wraplength=280)
        right=ttk.Frame(area,style='Panel.TFrame');right.grid(row=0,column=1,sticky='nsew')
        right.columnconfigure(0,weight=1);right.rowconfigure(2,weight=1)
        self.title=tk.StringVar(value='生成后的白模，都在这里')
        self.meta=tk.StringVar(value='选择预览，可直接播放、拖动进度并继续编辑工程。')
        title_label=ttk.Label(right,textvariable=self.title,style='Section.TLabel',wraplength=450)
        title_label.grid(row=0,column=0,sticky='w',pady=(0,6))
        meta_label=ttk.Label(right,textvariable=self.meta,style='PanelMuted.TLabel',wraplength=460)
        meta_label.grid(row=1,column=0,sticky='w',pady=(0,10))
        self.player=VideoPreview(right);self.player.grid(row=2,column=0,sticky='nsew')
        self.review=tk.StringVar(value='')
        review_label=ttk.Label(right,textvariable=self.review,foreground='#f0b35a',background=PANEL,font=('Microsoft YaHei UI',9),wraplength=460)
        review_label.grid(row=3,column=0,sticky='ew',pady=(10,8))
        right.bind('<Configure>',lambda e:[label.configure(wraplength=max(240,e.width-4))
                                         for label in (title_label,meta_label,review_label)])
        actions=ttk.Frame(right,style='Panel.TFrame');actions.grid(row=4,column=0,sticky='ew')
        self.action_buttons=[]
        for i,(label,command) in enumerate([('继续编辑项目',self.open_project),('打开 Blender 工程',self.open_blend),('打开文件夹',self.open_folder),('外部播放',self.external_play)]):
            actions.columnconfigure(i%2,weight=1)
            button=ttk.Button(actions,text=label,command=command,style='Quiet.TButton',state='disabled')
            button.grid(row=i//2,column=i%2,sticky='ew',padx=(0,6),pady=3);self.action_buttons.append(button)
        self._render_entries()
        if open_live:
            ttk.Button(actions,text='连接 Blender / Agent 修正',style='Accent.TButton',command=lambda:open_live(self.selected) if self.selected else None).grid(row=2,column=0,columnspan=2,sticky='ew',pady=(6,0))

    def refresh(self,select_video=None):
        if select_video:self._pending_video=select_video
        if self._refreshing:return
        self._refreshing=True;self.refresh_button.configure(state='disabled');self.summary.set('正在整理历史白模…')
        def done(result):
            if not self.winfo_exists():return
            self._refreshing=False;self.refresh_button.configure(state='normal')
            if isinstance(result,Exception):self.summary.set('刷新失败：'+str(result));return
            self.entries=result;self._render_entries()
            if self._pending_video:
                path=self._pending_video;self._pending_video=None;self.select_video(path)
        self._run_async(lambda:refresh_library(self.workspace),done)

    def _render_entries(self):
        selected=self.selected['id'] if self.selected else None
        self.tree.delete(*self.tree.get_children());self._thumbs=[]
        text=self.search.get().strip().lower();kind={'完整视频':'full','单个镜头':'shot'}.get(self.kind.get())
        entries=[e for e in self.entries if (kind is None or e['kind']==kind) and text in (e['source_name']+' '+e['project_id']+' '+e['name']).lower()]
        for e in entries:
            image=None
            if e.get('thumbnail') and Path(e['thumbnail']).is_file():
                try:
                    with Image.open(e['thumbnail']) as poster:
                        poster=poster.convert('RGB');poster.thumbnail((96,64),Image.Resampling.LANCZOS)
                        image=ImageTk.PhotoImage(poster,master=self);self._thumbs.append(image)
                except (OSError,ValueError):pass
            stem=Path(e['source_name']).stem;short=stem[:16]+'…' if len(stem)>17 else stem
            title=short+'\n'+e['name']+' · '+e['created_at'][5:]
            version='真人 · 待复核' if e.get('geometry_profile')=='human_v3' else '代理 · 待复核' if e.get('geometry_profile')=='mannequin_v2' else '早期版本'
            kwargs={'image':image} if image else {}
            self.tree.insert('','end',iid=e['id'],text=title,values=(clock_text(e['duration_seconds'])+'\n'+version,),**kwargs)
        self.summary.set(f"{sum(e['kind']=='full' for e in self.entries)} 个完整预览 · {sum(e['kind']=='shot' for e in self.entries)} 个镜头")
        if not entries:
            self.empty.grid(row=1,column=0,sticky='w',pady=12);self.player.close();self.selected=None
            self.title.set('没有匹配的白模');self.meta.set('尝试更换筛选条件，或完成一次一键转换。');self.review.set('')
            for button in self.action_buttons:button.configure(state='disabled')
            return
        self.empty.grid_remove()
        self.tree.selection_set(selected if selected and self.tree.exists(selected) else entries[0]['id'])

    def select_video(self,path):
        item=next((e for e in self.entries if Path(e['video']).resolve()==Path(path).resolve()),None)
        if item:
            self.search.set('');self.kind.set('完整视频' if item['kind']=='full' else '单个镜头');self._render_entries()
            self.tree.selection_set(item['id']);self.tree.see(item['id']);self._select()

    def _select(self,_event=None):
        selection=self.tree.selection()
        if not selection:return
        item=next((e for e in self.entries if e['id']==selection[0]),None)
        if item is None:return
        if self.selected and self.selected['id']==item['id'] and self.player.path==item['video']:return
        self.selected=item;self.title.set(item['source_name'])
        self.meta.set(f"{item['name']} · {item['width']} × {item['height']} · {item['fps']} fps · {clock_text(item['duration_seconds'])}\n{item['created_at']} · {item['size_bytes']/1048576:.1f} MB")
        notes=item['warnings']
        self.review.set('\n'.join(notes[:3]) if notes else '近似白模；请复核人物遮挡、接触、相机和场景。')
        try:self.player.load(item['video'])
        except Exception as exc:self.review.set(str(exc))
        for button in self.action_buttons:button.configure(state='normal')
        self.action_buttons[0].configure(state='normal' if item.get('project_path') else 'disabled')
        self.action_buttons[1].configure(state='normal' if item.get('blend') else 'disabled')

    def open_project(self):
        if self.selected and self.selected.get('project_path'):self._open_project(self.selected)

    def open_blend(self):
        if not self.selected:return
        executable=find_blender(self.selected.get('blender_path') or load_config().get('blender_path'))
        if executable and self.selected.get('blend'):
            subprocess.Popen([executable,self.selected['blend']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:self.review.set('未找到本地 Blender，请在连接与设置中配置。')

    def open_folder(self):
        if self.selected and Path(self.selected['directory']).is_dir():os.startfile(self.selected['directory'])

    def external_play(self):
        if not self.selected:return
        player=media_tool('ffplay')
        if player:subprocess.Popen([player,'-loglevel','error','-autoexit','-window_title','WHITEBLOCK / 白模预览',self.selected['video']],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:os.startfile(self.selected['video'])

    def destroy(self):
        self.player.close();super().destroy()
