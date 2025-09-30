# notifications/utils.py
from extensions import db
from notifications.models import Notification

def push_notification(user_id: int, message: str, ntype: str = "info", meta: str | None = None):
    n = Notification(user_id=user_id, message=message, type=ntype, meta=meta)
    db.session.add(n)
    db.session.commit()
    return n.to_dict()

def push_to_many(user_ids: list[int], message: str, ntype: str = "info", meta: str | None = None):
    if not user_ids:
        return []
    notif_objs = [Notification(user_id=uid, message=message, type=ntype, meta=meta) for uid in user_ids]
    db.session.add_all(notif_objs)
    db.session.commit()
    return [n.to_dict() for n in notif_objs]
