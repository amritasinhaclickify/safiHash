# security/models.py
from extensions import db
from datetime import datetime

class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    event = db.Column(db.String(255))
    severity = db.Column(db.String(50))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event": self.event,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }
