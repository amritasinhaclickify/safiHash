from datetime import datetime
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    kyc_status = db.Column(db.String(32), default="unverified")
    role = db.Column(db.String(20), default="user")
    hedera_private_key = db.Column(db.String, nullable=True)
    kyc_file_id   = db.Column(db.String(100), nullable=True)   # Hedera File ID
    kyc_file_hash = db.Column(db.String(128), nullable=True)   # SHA256 hash of document

    # 🔹 Hedera + Banking
    hedera_account_id = db.Column(db.String(100), nullable=True)  # Hedera Account e.g. 0.0.1234
    bank_account_number = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'

    # --- Password helpers ---
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)



class KYCRequest(db.Model):
    __tablename__ = "kyc_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 🔑 Explicit fields instead of dumping JSON only
    document_type = db.Column(db.String(50), nullable=False)        # e.g., "National ID"
    document_number = db.Column(db.String(100), nullable=False)     # e.g., "GH123456"

    raw_data = db.Column(db.Text)  # optional: store full JSON if needed

    status = db.Column(db.String(20), default="pending", nullable=False)  # pending/approved/rejected
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="kyc_requests")
    hedera_file_id = db.Column(db.String(100), nullable=True)   # e.g., "0.0.6808304"
    hedera_file_hash = db.Column(db.String(200), nullable=True) # e.g., SHA-256 hash

class SystemConfig(db.Model):
    __tablename__ = "system_config"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f"<Config {self.key}={self.value}>"
    
# --- convenience helpers (import these where needed) ---
def get_config(key: str, default: str = None):
    row = db.session.get(SystemConfig, key)
    return row.value if row else default

def set_config(key: str, value: str):
    row = db.session.get(SystemConfig, key)
    if row:
        row.value = value
    else:
        row = SystemConfig(key=key, value=value)
        db.session.add(row)
    db.session.commit()
    return row
   
