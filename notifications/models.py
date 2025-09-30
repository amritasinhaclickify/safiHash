
# notifications/models.py
from datetime import datetime
from extensions import db

class Notification(db.Model):
    __tablename__ = "notification"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message    = db.Column(db.String(500), nullable=False)   # short text to show in UI
    type       = db.Column(db.String(50), nullable=False, default="info")  # info|success|warning|error|system
    meta       = db.Column(db.Text, nullable=True)           # optional JSON/string payload
    is_read    = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "message": self.message,
            "type": self.type,
            "meta": self.meta,
            "is_read": self.is_read,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user_id={self.user_id} type={self.type} read={self.is_read}>"
