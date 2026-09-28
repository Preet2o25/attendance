import base64
import cv2
import numpy as np
import config


class FaceError(Exception):
    def __init__(self, message, code="face_error"):
        super().__init__(message)
        self.message, self.code = message, code


def _fr():
    try:
        import face_recognition
        return face_recognition
    except (ImportError, Exception, SystemExit) as e:
        raise FaceError(f"The 'face_recognition' library is not available or failed to load: {e}", "server_error")


def decode_image(data_url):
    if not data_url:
        raise FaceError("No image received. Make sure camera is active.", "bad_image")
    try:
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        arr = np.frombuffer(base64.b64decode(b64), np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None:
        raise FaceError("Invalid or poor image. Please try again.", "bad_image")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), img


def encode_single_face(data_url):
    """Detect exactly one face and return (encoding, bgr_image)."""
    fr = _fr()
    rgb, bgr = decode_image(data_url)
    try:
        locs = fr.face_locations(rgb)
    except Exception as e:
        raise FaceError(f"Face detection failed: {str(e)}", "server_error")
    if len(locs) == 0:
        raise FaceError("Face not detected. Face the camera in good lighting.", "no_face")
    if len(locs) > 1:
        raise FaceError("Please ensure that only one person is visible.", "multiple_faces")
    try:
        encodings = fr.face_encodings(rgb, locs)
        if not encodings:
            raise FaceError("Could not extract face features. Please try again.", "no_face")
        return encodings[0], bgr
    except FaceError:
        raise
    except Exception as e:
        raise FaceError(f"Face encoding failed: {str(e)}", "server_error")


def best_match(encoding, known):
    """known = [(student_row_id, np.array)]. Returns (row_id, distance) or None if no match."""
    if not known:
        return None
    fr = _fr()
    try:
        known_encs = [k[1] for k in known]
        dists = fr.face_distance(known_encs, encoding)
        if len(dists) == 0:
            return None
        i = int(np.argmin(dists))
        if dists[i] <= config.FACE_TOLERANCE:
            return known[i][0], float(dists[i])
    except Exception:
        return None
    return None
