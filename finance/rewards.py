# finance/rewards.py

from finance.models import db, Reward

def grant_reward(user_id, points, reason):
    reward = Reward(user_id=user_id, points=points, reason=reason)
    db.session.add(reward)
    db.session.commit()
    return reward.to_dict()

def get_rewards(user_id):
    rewards = Reward.query.filter_by(user_id=user_id).order_by(Reward.timestamp.desc()).all()
    return [r.to_dict() for r in rewards]

def total_points(user_id):
    points = db.session.query(db.func.sum(Reward.points)).filter_by(user_id=user_id).scalar() or 0
    return points

def check_rewards(user_id):
    reward = Reward.query.filter_by(user_id=user_id).first()
    if not reward:
        return {"points": 0, "message": "No rewards yet."}
    return {"points": reward.points, "message": "Rewards fetched."}

def redeem_rewards(user_id):
    reward = Reward.query.filter_by(user_id=user_id).first()
    if not reward or reward.points == 0:
        return {"success": False, "message": "No points to redeem."}
    reward.points = 0
    from users.models import db
    db.session.commit()
    return {"success": True, "message": "Rewards redeemed!"}
