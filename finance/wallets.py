# finance/wallets.py

from finance.models import db, Wallet

def create_wallet(user_id: int) -> Wallet:
    wallet = Wallet(user_id=user_id, balance=0.0)
    db.session.add(wallet)
    db.session.commit()
    return wallet

def deposit_to_wallet(user_id: int, amount: float) -> bool:
    wallet = Wallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        return False
    wallet.balance += amount
    db.session.commit()
    return True

def get_wallet_balance(user_id: int) -> float:
    wallet = Wallet.query.filter_by(user_id=user_id).first()
    if wallet:
        return wallet.balance
    return 0.0
