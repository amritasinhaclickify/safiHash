import os
import sys
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from config import Config
from extensions import db, migrate, jwt
from flask_jwt_extended import jwt_required, get_jwt_identity

# Blueprints
from users.models import User
from users.routes import users_bp
from ai_engine.kyc_routes import kyc_bp
from finance.routes import finance_bp
from ai_engine.chat_routes import chat_bp
from bank_admin.routes import bank_admin_bp
from notifications.routes import notifications_bp
from ai_engine.fraud_routes import fraud_bp
from complaints.routes import complaint_bp
from offline_sync.routes import sync_bp
from super_admin.routes import super_admin_bp
from ngo.routes import ngo_bp   # ⬅️ Add this
from company.routes import company_bp
from cooperative import models as cooperative_models
from cooperative.routes import coop_bp
from payments.routes import payments_bp



def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ✅ Enable CORS with credentials so cookies work
    CORS(app, supports_credentials=True)

    # ✅ Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # ✅ Register Blueprints
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(kyc_bp, url_prefix="/api/kyc")
    app.register_blueprint(finance_bp, url_prefix="/api/finance")
    app.register_blueprint(chat_bp, url_prefix="/api/chat")
    app.register_blueprint(bank_admin_bp, url_prefix="/api/bank-admin")
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")
    app.register_blueprint(fraud_bp, url_prefix="/api/fraud")
    app.register_blueprint(complaint_bp, url_prefix="/api/complaints")
    app.register_blueprint(sync_bp, url_prefix="/api/sync")
    app.register_blueprint(super_admin_bp, url_prefix="/api/super-admin")
    app.register_blueprint(company_bp, url_prefix="/api/company")
    app.register_blueprint(ngo_bp, url_prefix="/api/ngo")
    app.register_blueprint(coop_bp)
    app.register_blueprint(payments_bp)

    from apscheduler.schedulers.background import BackgroundScheduler
    from middleware.offline_sync import process_outbox

        # ✅ Background scheduler (safe, app context)
    def _process_outbox_with_app():
        with app.app_context():
            try:
                process_outbox()
            except Exception:
                import traceback
                traceback.print_exc()

    def start_scheduler():
        
        # ⚠️ Prevent running during CLI commands (db migrate, shell, etc.)
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            return

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _process_outbox_with_app,
            'interval',
            minutes=1,
            id='outbox_retry',
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=60
        )
        scheduler.start()
        print("✅ Outbox background scheduler started (runs every 1 min)")

    start_scheduler()


    # Root route -> login page
    @app.route('/')
    def index():
        return render_template("auth.html")

    # ✅ Secure Super Admin Dashboard (role check)
    @app.route("/super-admin")
    @jwt_required(optional=True)
    def super_admin_dashboard_page():
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(int(user_id))
        if not user or getattr(user, "role", "user") != "super-admin":
            return jsonify({"error": "Forbidden: Super Admins only"}), 403

        return render_template("super_admin.html")
    

    # ✅ Secure Admin Dashboard (role check)
    @app.route("/bank-admin")
    @jwt_required(optional=True)
    def admin_dashboard_page():
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(int(user_id))
        if not user or getattr(user, "role", "user") != "bank-admin":
            return jsonify({"error": "Forbidden: Admins only"}), 403

        return render_template("bank_admin.html")


    # ✅ Secure Chatbot (any logged-in user allowed)
    @app.route("/chatbot")
    @jwt_required(optional=True)
    def chatbot_page():
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        return render_template("chatbot.html")

    # ✅ Secure NGO Dashboard (role check)
    @app.route("/ngo")
    @jwt_required(optional=True)
    def ngo_dashboard_page():
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(int(user_id))
        if not user or getattr(user, "role", "user") != "ngo":
            return jsonify({"error": "Forbidden: NGO only"}), 403

        return render_template("ngo.html")
    
    # ✅ Public Documentation Page (no login required)
    @app.route("/docs")
    def docs_page():
        return render_template("docs.html")

    # ✅ Secure Company Dashboard (role check)
    @app.route("/company")
    @jwt_required(optional=True)
    def company_dashboard_page():
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(int(user_id))
        if not user or getattr(user, "role", "user") != "company":
            return jsonify({"error": "Forbidden: Company only"}), 403

        return render_template("company.html")
    # ✅ Secure Group Dashboard (any logged-in user)
    @app.route("/group/<slug>")
    @jwt_required(optional=True)
    def group_dashboard_page(slug):
        user_id = get_jwt_identity()
        if not user_id:
           return jsonify({"error": "Unauthorized"}), 401
        return render_template("group_dashboard.html", slug=slug)
    
    # ✅ Per-member Trust Score Dashboard
    @app.route("/group/<slug>/member/<int:user_id>/trust")
    @jwt_required(optional=True)
    def group_member_trust_page(slug, user_id):
        user_id_jwt = get_jwt_identity()
        if not user_id_jwt:
            return jsonify({"error": "Unauthorized"}), 401
        # Just render the dummy page for now
        return render_template("trust_dashboard.html",
                               group_slug=slug,
                               user_id=user_id)





    # ✅ Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Route not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=True)

