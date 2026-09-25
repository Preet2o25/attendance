async function startS(id){const r=await api('/api/sessions/start','POST',{timetable_id:id});alert(r.message);if(r.success)location.href='/attendance'}
async function stopS(id){const r=await api('/api/sessions/'+id+'/stop','POST');alert(r.message);location.reload()}
document.querySelectorAll('.cd').forEach(td=>{let s=+td.dataset.left;const t=()=>{td.textContent=fmt(s);if(s<=0){location.reload();return}s--;setTimeout(t,1000)};t()});
