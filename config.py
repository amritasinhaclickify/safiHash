import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Flask Core ---
    SECRET_KEY = os.getenv('SECRET_KEY', 'fallback-secret-key')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///safichain.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Hedera Operator ---
    HEDERA_OPERATOR_ID = os.getenv('HEDERA_OPERATOR_ID')
    HEDERA_OPERATOR_KEY = os.getenv('HEDERA_OPERATOR_KEY')

    # --- JWT Authentication (Cookie-Based) ---
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")

    # Store JWT in cookies instead of headers
    JWT_TOKEN_LOCATION = ["cookies", "headers"]


    # Cookies config
    JWT_COOKIE_SECURE = False  # ⚠️ Set to True with HTTPS in production
    JWT_ACCESS_COOKIE_PATH = "/"
    JWT_REFRESH_COOKIE_PATH = "/api/users/token/refresh"

    # CSRF protection (disable during local dev to avoid token mismatch issues)
    JWT_COOKIE_CSRF_PROTECT = False  # ✅ changed from True to False for easier local testing

    # Token expiry
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)

    # --- Hedera defaults for onboarding ---
    # Optional HTS token for initial deposit; leave blank for HBAR
    HEDERA_DEFAULT_TOKEN_ID = os.getenv("HEDERA_DEFAULT_TOKEN_ID", "")
    # Initial airdrop amount (float)
    HEDERA_INITIAL_DEPOSIT = float(os.getenv("HEDERA_INITIAL_DEPOSIT", "100"))
    HEDERA_TOPIC_ID = os.getenv("HEDERA_TOPIC_ID", "0.0.6613182")

