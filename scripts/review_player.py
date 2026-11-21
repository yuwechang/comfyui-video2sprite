"""Serve actual GIFs locally and record bounded continuous playback observations."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import time
from generate import save
from job_contract import file_digest

def receipt(entry, observed, elapsed_ms):
    if type(elapsed_ms) is not int:raise ValueError('Playback duration must be integer milliseconds')
    if elapsed_ms<entry['clip_duration_ms']:raise ValueError('Full clip duration has not elapsed')
    if observed.get('full_clip_observed') is not True:raise ValueError('Confirm full clip observation')
    if entry.get('check_replay_boundary') and observed.get('replay_boundary_observed') is not True:
        raise ValueError('Confirm loop tail-to-head observation')
    if not isinstance(observed.get('reason'),str) or not observed['reason'].strip():raise ValueError('Provide actual playback findings')
    return {'path':entry['path'],'sha256':file_digest(entry['path']),
        'method':'continuous_playback','full_clip_observed':True,
        'replay_boundary_observed':observed.get('replay_boundary_observed',False),
        'elapsed_visible_ms':elapsed_ms,'clip_duration_ms':entry['clip_duration_ms'],'reason':observed['reason']}

def validate(record, entries):
    observations=record.get('observations',[])
    if record.get('status')!='complete' or len(observations)!=len(entries):raise ValueError('Incomplete playback record')
    if len({str(Path(o['path']).resolve()) for o in observations})!=len(entries):raise ValueError('Duplicate playback observations')
    for entry in entries:
        item=next((x for x in observations if Path(x['path']).resolve()==Path(entry['path']).resolve()),None)
        if not item or item.get('method')!='continuous_playback' or item.get('sha256')!=file_digest(entry['path']):
            raise ValueError('Playback evidence missing or preview changed')
        receipt(entry,item,item.get('elapsed_visible_ms',-1))

def load_progress(folder, entries, fingerprint):
    session=Path(folder)/'session.json';progress=Path(folder)/'observations.json'
    if not session.exists():
        if Path(folder).exists() and any(Path(folder).iterdir()):raise ValueError('Review output contains unrelated files')
        return {}
    if json.loads(session.read_text(encoding='utf-8')).get('fingerprint')!=fingerprint:
        raise ValueError('Review inputs changed; use a new session directory')
    if not progress.exists():return {}
    record=json.loads(progress.read_text(encoding='utf-8'))
    if record.get('status') not in ('in_progress','complete'):raise ValueError('Invalid playback progress state')
    observed={}
    for item in record.get('observations',[]):
        index=next((i for i,e in enumerate(entries) if Path(e['path']).resolve()==Path(item['path']).resolve()),None)
        if index is None or index in observed:raise ValueError('Unexpected or duplicate observation')
        validate({'status':'complete','observations':[item]},[entries[index]])
        observed[index]=item
    if (record['status']=='complete')!=(len(observed)==len(entries)):raise ValueError('Playback progress status differs from observation coverage')
    return observed

PAGE='''<!doctype html><meta charset="utf-8"><title>Animation review</title>
<style>body{background:#222;color:#eee;font:16px sans-serif;margin:24px}.review{display:flex;gap:24px;align-items:flex-start}.controls{max-width:600px}img{display:block;max-height:70vh;max-width:45vw}textarea{display:block;width:95%;height:70px}label{display:block;margin:12px 0}</style>
<h1 id="title"></h1><div class="review"><section><img id="gif"></section><section class="controls"><p id="instructions"></p><p id="clock"></p>
<label><input type="checkbox" id="full">已完整觀看本片段 / Full clip observed</label>
<label id="boundaryLabel"><input type="checkbox" id="boundary">已檢查尾接首 / Replay boundary observed</label>
<textarea id="reason" placeholder="記錄實際動作、節奏及結束行為 / Actual findings"></textarea>
<button id="submit">保存觀察 / Save observation</button><p id="result"></p></section></div>
<script>const entries=ENTRIES;const title=document.getElementById('title'),instructions=document.getElementById('instructions'),gif=document.getElementById('gif'),clock=document.getElementById('clock'),full=document.getElementById('full'),boundary=document.getElementById('boundary'),boundaryLabel=document.getElementById('boundaryLabel'),reason=document.getElementById('reason'),submit=document.getElementById('submit'),result=document.getElementById('result');let index=START_INDEX,elapsed=0,last=performance.now(),loaded=false;
function show(){loaded=false;elapsed=0;last=performance.now();const e=entries[index];title.textContent=e.variant;instructions.textContent=e.instruction;
boundaryLabel.hidden=!e.check_replay_boundary;full.checked=false;boundary.checked=false;reason.value='';gif.onload=()=>{loaded=true;last=performance.now()};gif.src='asset/'+index+'?TOKEN';}
setInterval(()=>{const now=performance.now(),r=gif.getBoundingClientRect(),visible=r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth;if(loaded&&!document.hidden&&visible)elapsed+=now-last;else elapsed=0;last=now;clock.textContent=Math.floor(elapsed)+' ms / '+entries[index].clip_duration_ms+' ms';},100);
document.addEventListener('visibilitychange',()=>{if(document.hidden){elapsed=0;loaded=false}else{loaded=true;last=performance.now();gif.src='asset/'+index+'?TOKEN&restart='+Date.now()}});
submit.onclick=async()=>{const r=await fetch('observe?TOKEN',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index,elapsed_ms:Math.floor(elapsed),full_clip_observed:full.checked,replay_boundary_observed:boundary.checked,reason:reason.value})});const data=await r.json();result.textContent=data.message;if(r.ok){if(data.next_index!==null){index=data.next_index;show()}else{submit.disabled=true;result.textContent='觀察已保存 / Observations saved'}}};show();</script>'''

def serve(request_file, output, timeout=900):
    import math
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('Review timeout must be finite and positive')
    request=json.loads(Path(request_file).read_text(encoding='utf-8-sig'))
    entries=request['diagnostic']['playback']
    if not entries:raise ValueError('Request has no playback entries')
    for entry in entries:
        if not Path(entry['path']).is_file():raise ValueError('Missing preview')
        if type(entry.get('clip_duration_ms')) is not int or entry['clip_duration_ms']<=0:raise ValueError('Invalid playback duration')
    folder=Path(output).resolve()
    expected_hashes=[file_digest(e['path']) for e in entries]
    fingerprint=hashlib.sha256((file_digest(request_file)+''.join(expected_hashes)).encode()).hexdigest()
    observed=load_progress(folder,entries,fingerprint)
    if len(observed)==len(entries):return {'status':'complete','playback_record':str(folder/'observations.json')}
    folder.mkdir(parents=True,exist_ok=True);token=secrets.token_urlsafe(24);loaded={};started=time.monotonic()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,payload,mime='application/json'):
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            route,_,query=self.path.partition('?')
            if query.split('&')[0]!=token:return self.respond(403,b'{}')
            if route=='/':
                data=json.dumps(entries,ensure_ascii=False).replace('<','\\u003c')
                first=next(i for i in range(len(entries)) if i not in observed)
                return self.respond(200,PAGE.replace('ENTRIES',data).replace('TOKEN',token).replace('START_INDEX',str(first)).encode(),'text/html; charset=utf-8')
            if route.startswith('/asset/'):
                try:
                    i=int(route.rsplit('/',1)[1]);path=Path(entries[i]['path'])
                    if file_digest(path)!=expected_hashes[i]:return self.respond(409,b'{"message":"Preview changed; restart review"}')
                    loaded[i]=time.monotonic()
                    return self.respond(200,path.read_bytes(),'image/gif')
                except (ValueError,IndexError):pass
            self.respond(404,b'{}')
        def do_POST(self):
            if self.path!='/observe?'+token:return self.respond(403,b'{}')
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise ValueError('Invalid request length')
                data=json.loads(self.rfile.read(length));i=data['index']
                if type(i) is not int or not 0<=i<len(entries) or i not in loaded:raise ValueError('Preview not loaded')
                if type(data.get('elapsed_ms')) is not int:raise ValueError('Invalid playback duration')
                if file_digest(entries[i]['path'])!=expected_hashes[i]:raise ValueError('Preview changed; restart review')
                elapsed=min(data['elapsed_ms'],int((time.monotonic()-loaded[i])*1000))
                observed[i]=receipt(entries[i],data,elapsed)
                save(folder/'observations.json',{'status':'complete' if len(observed)==len(entries) else 'in_progress',
                    'observations':[observed[k] for k in sorted(observed)]})
                next_index=next((i for i in range(len(entries)) if i not in observed),None)
                self.respond(200,json.dumps({'message':'Saved','next_index':next_index}).encode())
            except (KeyError,ValueError,TypeError) as exc:self.respond(400,json.dumps({'message':str(exc)}).encode())
    server=HTTPServer(('127.0.0.1',0),Handler);server.timeout=1
    url='http://127.0.0.1:'+str(server.server_port)+'/?'+token
    save(folder/'session.json',{'url':url,'request':str(Path(request_file).resolve()),'fingerprint':fingerprint})
    print(json.dumps({'status':'review_ready','url':url}),flush=True)
    try:
        while len(observed)<len(entries) and time.monotonic()-started<timeout:server.handle_request()
    finally:server.server_close()
    if len(observed)<len(entries):raise TimeoutError('Playback observation incomplete; no approval was recorded')
    return {'status':'complete','playback_record':str(folder/'observations.json')}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--timeout',type=float,default=900);args=parser.parse_args()
    print(json.dumps(serve(args.request,args.output,args.timeout)))
