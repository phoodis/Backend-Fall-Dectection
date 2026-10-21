import os

from flask import Blueprint, abort, send_from_directory

from app.config import Config

bp = Blueprint('alert_images', __name__, url_prefix='/api/alert-images')

# Only these are ever served, whatever else happens to be in the directory.
ALLOWED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.mp4')


# No @jwt_required() on purpose, as in the friend's backend: the web UI loads these through <img>/<video>,
# which cannot send an Authorization header, and LINE (later step) fetches them from a public URL.
# The consequence: ANYONE WHO CAN GUESS A FILE NAME CAN OPEN THE PICTURE. Names look like
# v3_fall_detect_<camera id>_<unix seconds>.jpg, so they are guessable. See docs/migration_plan_A.md.
@bp.route('/<filename>', methods=['GET'])
def get_alert_image(filename):
    alert_dir = os.path.realpath(getattr(Config, 'ALERT_IMAGE_DIR', None) or '/app/tmp')

    # Reject anything that is not one plain file name: separators of either kind, parent references,
    # hidden files, NUL bytes, and extensions that are not on the list.
    if (not filename or filename != os.path.basename(filename) or '/' in filename or '\\' in filename
            or '\x00' in filename or filename.startswith('.') or '..' in filename
            or os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS):
        abort(404)

    # The real path (symlinks resolved) must still be inside the alert directory.
    full = os.path.realpath(os.path.join(alert_dir, filename))
    if os.path.dirname(full) != alert_dir or not os.path.isfile(full):
        abort(404)

    response = send_from_directory(alert_dir, filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
