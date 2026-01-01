
import sys
import os

# Add the current directory to sys.path to allow local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import Account

def check_accounts():
    with app.app_context():
        print("-" * 50)
        print("Checking Account Status:")
        
        # Check 1290
        acc_1290 = Account.query.filter_by(account_number='1290').first()
        if acc_1290:
            print(f"Account 1290: {acc_1290.name} | Type: {acc_1290.type} | Parent: {acc_1290.parent_id}")
        else:
            print("Account 1290: Not Found")

        # Check 5230 (Old location)
        acc_5230 = Account.query.filter_by(account_number='5230').first()
        if acc_5230:
            print(f"Account 5230: {acc_5230.name} | Type: {acc_5230.type} | Parent: {acc_5230.parent_id}")
        else:
            print("Account 5230: Not Found")
            
        # Check 431 (Very old location)
        acc_431 = Account.query.filter_by(account_number='431').first()
        if acc_431:
            print(f"Account 431: {acc_431.name} | Type: {acc_431.type} | Parent: {acc_431.parent_id}")
        else:
            print("Account 431: Not Found")
            
        print("-" * 50)

if __name__ == "__main__":
    check_accounts()
