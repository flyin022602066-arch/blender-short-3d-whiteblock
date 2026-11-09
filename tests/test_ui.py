import unittest
from unittest.mock import patch
from whiteblock.ui import WhiteblockApp


class DesktopTests(unittest.TestCase):
    def test_agent_template_choice_selects_requested_shot_for_next_render(self):
        import tempfile
        from pathlib import Path
        from whiteblock.pipeline import save_project,load_project
        project={'schema_version':'1.0','project_id':'fixture','blender_version':'5.1.2',
                 'source':{'path':'C:/fixture/source.mp4','readonly':True},
                 'shots':[{'shot_id':sid,'start_frame':i+1,'end_frame':i+1,'fps':24,'actors':[{'id':'Actor_01'}]}
                          for i,sid in enumerate(('shot_001','shot_002'))]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'project.json';save_project(path,project)
            self.app.project,self.app.project_path,self.app.selected_shot=project,path,'shot_001'
            self.app.agent_set_actor_template('Actor_01','female','shot_002')
            self.assertEqual(self.app.selected_shot,'shot_002')
            saved=load_project(path)
            self.assertNotIn('body_template',saved['shots'][0]['actors'][0])
            self.assertEqual(saved['shots'][1]['actors'][0]['body_template'],'female')

    def test_actor_template_page_saves_only_selected_character(self):
        self.assertIn('actors',self.app.pages)
        import tempfile
        from pathlib import Path
        from whiteblock.pipeline import save_project,load_project
        project={'schema_version':'1.0','project_id':'fixture','blender_version':'5.1.2','source':{'path':'C:/fixture/source.mp4','readonly':True},
                 'media':{'width':720,'height':1280,'fps':24},'shots':[{'shot_id':'shot_001','start_frame':1,'end_frame':2,'fps':24,
                    'actors':[{'id':'Actor_01','poses':[]},{'id':'Actor_02','poses':[]}]}]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'project.json';save_project(path,project)
            self.app.project,self.app.project_path,self.app.selected_shot=project,path,'shot_001'
            self.app.geometry('1020x680');self.app.show_page('actors');self.app.update()
            self.app.actor_tree.selection_set('Actor_02');self.app._actor_selected()
            self.app.actor_template_var.set('女型');self.app.actor_role_var.set('角色乙')
            self.app.actor_apply_button.invoke();self.app.update()
            saved=load_project(path)['shots'][0]['actors']
            self.assertNotIn('body_template',saved[0])
            self.assertEqual(saved[1]['body_template'],'female')
            self.assertTrue(saved[1]['template_confirmed'])
            self.assertTrue(saved[1]['template_needs_render'])
            self.assertTrue(self.app.actor_render_button.winfo_viewable())
            button=self.app.actor_render_button
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())

    def test_library_opens_blender_with_the_selected_project_configuration(self):
        gallery=self.app.gallery
        gallery.selected={'blend':'S:/fixture/shot_001.blend','blender_path':'D:/CustomBlender/blender.exe'}
        with patch('whiteblock.gallery.find_blender',return_value='D:/CustomBlender/blender.exe') as resolve, \
             patch('whiteblock.gallery.subprocess.Popen') as launch:
            gallery.open_blend()
        resolve.assert_called_once_with('D:/CustomBlender/blender.exe')
        self.assertEqual(launch.call_args.args[0],['D:/CustomBlender/blender.exe','S:/fixture/shot_001.blend'])

    def test_library_navigation_can_seek_and_play_an_existing_video(self):
        self.assertIn('library',self.app.pages,'A visible repository navigation item is required.')
        import tempfile,cv2,numpy as np
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'预览.mp4'
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),12,(64,96))
            for color in [0]*6+[255]*6:writer.write(np.full((96,64,3),color,dtype=np.uint8))
            writer.release()
            player=self.app.gallery.player
            player.load(video);player.seek(0.6)
            self.assertEqual(player.frame_index,7)
            self.assertGreater(player._frame.getpixel((10,10))[0],200)
            player.toggle();self.assertTrue(player.playing)
            self.app.show_page('overview')
            self.assertFalse(player.playing)
            cap=player.capture;player.close()
            self.assertFalse(cap.isOpened())

    def setUp(self):
        self.app = WhiteblockApp()

    def tearDown(self):
        self.app.update_idletasks()
        self.app.destroy()

    def test_one_click_failure_restores_button_and_shows_failure_state(self):
        self.app._conversion_running = True
        self.app._busy = True
        self.app.convert_button.configure(state='disabled')
        with patch('whiteblock.ui.messagebox.showerror'):
            self.app._one_click_done(ValueError('E_LOCAL_ANALYSIS: unavailable'))
        self.assertFalse(self.app._busy)
        self.assertFalse(self.app._conversion_running)
        self.assertFalse(self.app.convert_button.instate(['disabled']))
        self.assertEqual(self.app._vars['status'].get(), '转换失败')

    def test_loaded_project_does_not_clip_shot_and_output_counts(self):
        self.app.project = {'project_id':'344534535_EP1__1_20261008_164438_253821', 'status':'needs_review',
                            'source':{'path':'C:/fixture/344534535_EP1_分镜1_原片.mp4'},
                            'media':{'width':720,'height':1280,'fps':24}, 'shots':[]}
        self.app._vars['shot_count'].set('10')
        self.app._vars['outputs'].set('41')
        self.app._vars['source'].set('344534535_EP1_分镜1_原片.mp4')
        self.app._vars['media'].set('720 × 1280 / 24.0 fps')
        self.app._vars['status'].set('needs_review')
        self.app.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        for key in ('shot_count','outputs'):
            label = next(w for w in descendants(self.app) if 'textvariable' in w.keys()
                         and str(w.cget('textvariable')) == str(self.app._vars[key]))
            self.assertGreaterEqual(label.winfo_width(), label.winfo_reqwidth(), key+' must remain readable')


if __name__ == '__main__': unittest.main()
