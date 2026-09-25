let sessions=[],cur=null,left=0,pos=null,stream=null,tick=null;
const $=id=>document.getElementById(id);
function badge(id,text,cls){const e=$(id);e.textContent=text;e.className='badge '+cls}
function show(text,ok){const m=$('msg');m.textContent=text;m.className='msg '+(ok?'ok':'bad');m.style.display='block'}

async function loadSessions(){
  const r=await api('/api/sessions/active');sessions=r.sessions||[];
  const sel=$('sessSel');sel.innerHTML='';
  if(!sessions.length){sel.innerHTML='<option>No active class</option>';setCur(null);show('No active class. Ask the teacher to start an attendance session.',false);return}
  sessions.forEach(s=>sel.add(new Option(s.subject+' ('+s.slot_start+')',s.id)));
  setCur(sessions[0]);
}
function setCur(s){
  cur=s;clearInterval(tick);
  $('cSub').textContent=s?s.subject:'-';$('cFac').textContent=s?s.faculty:'-';$('cRoom').textContent=s?s.room:'-';
  if(!s){badge('cStat','NONE','wait');$('timer').textContent='--:--';$('btnFace').disabled=true;return}
  left=s.remaining_seconds;badge('cStat','ACTIVE','ok');
  tick=setInterval(()=>{left--;$('timer').textContent=fmt(Math.max(left,0));
    if(left<=0){clearInterval(tick);badge('cStat','CLOSED','bad');$('btnFace').disabled=true;show('Attendance window has expired.',false)}},1000);
  $('timer').textContent=fmt(left);
  checkLocation();
}
$('sessSel').onchange=e=>setCur(sessions.find(s=>s.id==e.target.value));

async function checkLocation(){
  if(!cur)return;
  badge('lStat','Checking...','wait');$('lLoc').textContent='Checking...';$('lDist').textContent='Calculating...';$('btnFace').disabled=true;pos=null;
  const cfg=await api('/api/config');
  try{ if(!cfg.demo_mode) pos=await getLocation(); }
  catch(e){badge('lStat','Rejected','bad');$('lLoc').textContent='Unavailable';show(e,false);return}
  const r=await api('/api/location/check','POST',{session_id:cur.id,...(pos||{})});
  if(!r.success){badge('lStat','Rejected','bad');show(r.message,false);return}
  $('lLoc').textContent=r.latitude.toFixed(5)+', '+r.longitude.toFixed(5)+(cfg.demo_mode?' (demo)':'');
  $('lDist').textContent=r.distance_calculated+' m';
  $('rLoc').textContent=r.location_verified?'YES':'NO';
  if(!r.location_verified){badge('lStat','Rejected','bad');show(r.message,false);return}
  badge('lStat','Verified','ok');$('msg').style.display='none';
  if(!stream){try{stream=await startCamera($('video'))}catch(e){show(e,false);return}}
  $('btnFace').disabled=false;
}

async function verifyFace(){
  $('btnFace').disabled=true;badge('fStat','Verifying...','wait');
  const r=await api('/api/attendance/mark','POST',{session_id:cur.id,image:captureFrame($('video')),...(pos||{})});
  if(r.success){badge('fStat','Recognized','ok');$('rFace').textContent='YES';$('rLoc').textContent='YES';$('rAtt').textContent='PRESENT';
    show(r.message+' '+r.student+' ('+r.roll+') – '+r.subject+' at '+r.time+', '+r.distance+' m from classroom.',true);stopCamera(stream);stream=null;return}
  badge('fStat','Failed','bad');$('rAtt').textContent='NOT MARKED';
  if(['not_recognized','no_face','multiple_faces'].includes(r.code))$('rFace').textContent='NO';
  show(r.message,false);if(r.code!=='expired'&&r.code!=='duplicate')$('btnFace').disabled=false;
}
loadSessions();
