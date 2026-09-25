// Browser Geolocation API wrapper with friendly errors
function getLocation(){
  return new Promise((resolve,reject)=>{
    if(!navigator.geolocation) return reject('Location is not supported by this browser.');
    navigator.geolocation.getCurrentPosition(
      p=>resolve({latitude:p.coords.latitude,longitude:p.coords.longitude}),
      e=>reject(e.code===1?'Location permission denied. Please allow location access.':
                e.code===2?'Location unavailable. Turn on GPS/Wi-Fi and retry.':'Location request timed out.'),
      {enableHighAccuracy:true,timeout:15000,maximumAge:0});
  });
}
