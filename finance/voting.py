# finance/voting.py

from finance.models import db, Voting

def cast_user_vote(user_id: int, proposal: str, vote: str) -> Voting:
    voting = Voting(user_id=user_id, proposal=proposal, vote=vote)
    db.session.add(voting)
    db.session.commit()
    return voting

def count_votes(proposal: str) -> dict:
    votes = Voting.query.filter_by(proposal=proposal).all()
    results = {'yes': 0, 'no': 0, 'abstain': 0}

    for vote in votes:
        v = vote.vote.lower()
        if v in results:
            results[v] += 1

    return results
