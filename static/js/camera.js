// Shared webcam camera helper with cross-browser polyfills
async function startCamera(video) {
  // 1. Cross-browser polyfill for getUserMedia
  let getUserMedia = null;
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    getUserMedia = (constraints) => navigator.mediaDevices.getUserMedia(constraints);
  } else {
    const legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
    if (legacy) {
      getUserMedia = (constraints) => new Promise((resolve, reject) => legacy.call(navigator, constraints, resolve, reject));
    }
  }

  // 2. Secure Context check (HTTP vs HTTPS)
  const isSecure = window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';

  if (!getUserMedia) {
    if (!isSecure) {
      throw 'Camera access requires a Secure Context (HTTPS) on external browsers. Please access this portal using https:// instead of http://.';
    }
    throw 'Camera API is not supported by your browser. Please try Chrome, Edge, Safari, or Firefox.';
  }

  try {
    const stream = await getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: 'user'
      }
    });
    video.srcObject = stream;
    await video.play();
    return stream;
  } catch (e) {
    if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
      throw 'Camera permission was denied. Please allow camera access in your browser site settings and retry.';
    } else if (e.name === 'NotFoundError' || e.name === 'DevicesNotFoundError') {
      throw 'No camera detected on your device.';
    } else if (e.name === 'NotReadableError' || e.name === 'TrackStartError') {
      throw 'Camera is currently in use by another app or browser tab.';
    } else {
      throw 'Unable to start camera stream (' + (e.message || e) + ').';
    }
  }
}

function stopCamera(stream) {
  if (stream) {
    try {
      stream.getTracks().forEach(track => track.stop());
    } catch (e) {}
  }
}

function captureFrame(video) {
  const c = document.createElement('canvas');
  c.width = video.videoWidth || 640;
  c.height = video.videoHeight || 480;
  c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.9);
}
