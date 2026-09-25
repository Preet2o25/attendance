// Shared webcam helpers
async function startCamera(video){
  try{const s=await navigator.mediaDevices.getUserMedia({video:{width:640,height:480}});video.srcObject=s;await video.play();return s}
  catch(e){throw 'Camera permission denied or no camera found.'}}
function stopCamera(s){if(s)s.getTracks().forEach(t=>t.stop())}
function captureFrame(video){const c=document.createElement('canvas');c.width=video.videoWidth;c.height=video.videoHeight;
  c.getContext('2d').drawImage(video,0,0);return c.toDataURL('image/jpeg',0.9)}
