"""Local HTTP integration of observation persistence; no visual approval claims."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from review_player import serve,validate

class ReviewServerTests(unittest.TestCase):
    def test_http_observation_resume_hash_checks_and_completed_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);entries=[]
            for i in range(2):
                path=root/(str(i)+'.gif');Image.new('RGB',(10,10),(i*255,0,0)).save(path)
                entries.append({'path':str(path),'variant':str(i),'clip_duration_ms':20,
                    'check_replay_boundary':False,'instruction':'Controlled HTTP fixture'})
            request=root/'request.json';request.write_text(json.dumps({'diagnostic':{'playback':entries}}))
            output=root/'session';events=[]
            def start(previous_url=None):
                def worker():
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):events.append(serve(request,output,.75))
                    except TimeoutError:events.append('timed_out')
                thread=threading.Thread(target=worker,daemon=True);thread.start()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    session=output/'session.json'
                    if session.exists():
                        url=json.loads(session.read_text())['url']
                        if url!=previous_url:return thread,url
                    time.sleep(.005)
                self.fail('Review server did not start')
            def get(url):
                with urlopen(url,timeout=2) as response:return response.read()
            def post(url,index,full=True):
                body=json.dumps({'index':index,'elapsed_ms':100,'full_clip_observed':full,
                    'reason':'HTTP protocol test; not a production observation'}).encode()
                try:
                    with urlopen(Request(url,body,{'Content-Type':'application/json'}),timeout=2) as response:
                        return json.load(response)
                except HTTPError as exc:
                    message=exc.read().decode();exc.close()
                    raise HTTPError(exc.url,exc.code,str(exc.reason)+': '+message,exc.headers,None) from None
            first,url=start();base,token=url.split('/?')
            get(base+'/asset/0?'+token);time.sleep(.06)
            with self.assertRaises(HTTPError):post(base+'/observe?'+token,0,False)
            self.assertFalse((output/'observations.json').exists())
            self.assertEqual(post(base+'/observe?'+token,0)['next_index'],1)
            first.join(2);self.assertFalse(first.is_alive())
            self.assertEqual(json.loads((output/'observations.json').read_text())['status'],'in_progress')
            second,url2=start(url);base,token=url2.split('/?')
            self.assertIn(b'index=1,elapsed',get(url2))
            get(base+'/asset/1?'+token);time.sleep(.06)
            original=Path(entries[1]['path']).read_bytes()
            Image.new('RGB',(10,10),'blue').save(entries[1]['path'])
            with self.assertRaises(HTTPError):post(base+'/observe?'+token,1)
            Path(entries[1]['path']).write_bytes(original)
            get(base+'/asset/1?'+token);time.sleep(.06)
            self.assertIsNone(post(base+'/observe?'+token,1)['next_index'])
            second.join(2);self.assertFalse(second.is_alive())
            record=json.loads((output/'observations.json').read_text());validate(record,entries)
            with patch('review_player.HTTPServer',side_effect=AssertionError('Completed review must not reopen server')):
                self.assertEqual(serve(request,output,.3)['status'],'complete')
