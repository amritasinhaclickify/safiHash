# audit/models.py

from datetime import datetime
from extensions import db

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(255), nullable=False)       # e.g., "update loan", "verify KYC"
    table_name = db.Column(db.String(100), nullable=False)   # e.g., "Loan"
    record_id = db.Column(db.Integer, nullable=True)         # optional: loan id, user id etc.
    old_value = db.Column(db.Text)                           # JSON string (before update)
    new_value = db.Column(db.Text)                           # JSON string (after update)

    # canonical column
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # 🔹 alias for backward compatibility
    @property
    def created_at(self):
        return self.timestamp

    @created_at.setter
    def created_at(self, val):
        self.timestamp = val

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else None
        }

