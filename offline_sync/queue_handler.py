import json, os

QUEUE_FILE = "offline_queue.json"

def add_to_queue(data):
    queue = []
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            queue = json.load(f)
    queue.append(data)
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f)

def flush_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r") as f:
        queue = json.load(f)
    os.remove(QUEUE_FILE)
    return queue
