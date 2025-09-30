from flask import Blueprint, request, jsonify
from offline_sync.queue_handler import add_to_queue, flush_queue

sync_bp = Blueprint('sync', __name__, url_prefix='/api/sync')

# Data  queue route
@sync_bp.route('/queue', methods=['POST'])
def add_data_to_queue():
    data = request.get_json()
    add_to_queue(data)
    return jsonify({"message": "Data added to local queue"}), 201

# Queue flush DB route
@sync_bp.route('/sync', methods=['POST'])
def sync_data():
    queued_data = flush_queue()
    # DB save logic
    return jsonify({"message": "Data synced successfully", "records": queued_data}), 200
