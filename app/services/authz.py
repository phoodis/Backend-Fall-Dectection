"""The one admin check, so there cannot be a second, weaker one.

There were two. `app/routes/admin.py` had this database-backed decorator, and
`app/routes/detector_info.py` had a hand-rolled substitute that read a `role` claim off the
JWT: `if role and 'admin' not in role`. **No token in this application carries a role claim** --
`create_access_token(identity=str(user.id))` in `auth.py` passes no `additional_claims` and
there is no `additional_claims_loader` anywhere -- so `role` was always the empty string, the
`if role` guard was always false, and any logged-in user could rewrite the detector profile for
every camera on the machine. The endpoint was reachable regardless of what the admin-only panel
in the frontend chose to render.

That is the failure mode of a check that cannot fail, and the reason it is worth a module of
its own rather than a fix in place: authority has to be read from the user record, and there
has to be exactly one place that does it.

Use with `@jwt_required()` first -- this reads the verified identity, it does not verify.

    @bp.route('/thing', methods=['POST'])
    @jwt_required()
    @admin_required
    def change_thing(): ...
"""
from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity

from app.models.user import User


def get_current_user():
    """-> the User this request's verified token identifies, or None if they are gone."""
    identity = get_jwt_identity()
    if identity is None:
        return None
    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        # A token whose subject is not a user id is not a user, whatever else it is.
        return None
    return User.query.get(user_id)


def admin_required(f):
    """Require that the verified token belongs to an existing user whose record says admin.

    Every failure path denies. A missing user, an unparseable identity and a database error are
    all "not demonstrably an admin", and the previous version's habit of treating an absent
    claim as permission is exactly what this exists to prevent.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user = get_current_user()
        except Exception as exc:
            return jsonify({'success': False,
                            'error': 'Authorization failed: %s' % exc}), 500
        if not current_user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if not current_user.is_admin():
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        return f(*args, **kwargs)

    return decorated_function
