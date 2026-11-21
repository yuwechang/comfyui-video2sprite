import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import generate


class WaitingTests(unittest.TestCase):
    def test_single_call_owns_polling_and_transient_connection_retries(self):
        now=[0.0];delays=[]
        def sleep(seconds):delays.append(seconds);now[0]+=seconds
        with tempfile.TemporaryDirectory() as folder:
            state={'prompt_id':'existing','status':'waiting'};path=Path(folder)/'job.json'
            stdout=io.StringIO()
            with patch.object(generate.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(generate.time,'sleep',side_effect=sleep), \
                 patch.object(generate,'history_result',side_effect=[OSError('temporary'),None,{'done':True}]) as history, \
                 patch.object(generate,'request') as submit,contextlib.redirect_stdout(stdout):
                result=generate.wait_for_result('local','existing',None,100,path,state)
            self.assertEqual(result,{'done':True})
            self.assertEqual(history.call_count,3)
            self.assertEqual(delays,[15,15])
            submit.assert_not_called()
            self.assertEqual(stdout.getvalue(),'')
            self.assertEqual(json.loads(path.read_text())['wait']['history_checks'],3)

    def test_completion_event_returns_without_waiting_for_next_history_interval(self):
        ws=Mock();ws.recv.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'existing'}})
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate.time,'monotonic',return_value=0), \
             patch.object(generate,'history_result',side_effect=[None,{'done':True}]) as history, \
             patch.object(generate.time,'sleep') as sleep:
            generate.wait_for_result('local','existing',ws,100,Path(folder)/'job.json',{})
            self.assertEqual(history.call_count,2)
            ws.settimeout.assert_called_once_with(60)
            sleep.assert_not_called()

    def test_disconnected_socket_falls_back_inside_same_call(self):
        ws=Mock();ws.recv.side_effect=OSError('disconnected')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate.time,'monotonic',return_value=0), \
             patch.object(generate,'history_result',side_effect=[None,{'done':True}]) as history:
            state={}
            result=generate.wait_for_result('local','existing',ws,100,Path(folder)/'job.json',state)
            self.assertEqual(result,{'done':True})
            self.assertEqual(history.call_count,2)
            self.assertEqual(state['wait']['transport'],'history')

    def test_timeout_preserves_id_and_resume_uses_same_job(self):
        now=[0.0]
        def sleep(seconds):now[0]+=seconds
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'job.json';state={'prompt_id':'existing','status':'waiting'}
            with patch.object(generate.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(generate.time,'sleep',side_effect=sleep), \
                 patch.object(generate,'history_result',return_value=None), \
                 patch.object(generate,'request') as submit:
                with self.assertRaises(TimeoutError):
                    generate.wait_for_result('local','existing',None,20,path,state)
                saved=json.loads(path.read_text())
                self.assertEqual(saved['prompt_id'],'existing')
                self.assertTrue(saved['wait']['timed_out'])
                with patch.object(generate,'history_result',return_value={'done':True}):
                    self.assertEqual(generate.wait_for_result('local',saved['prompt_id'],None,20,path,saved),{'done':True})
                submit.assert_not_called()
