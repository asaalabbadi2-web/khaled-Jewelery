import sys
import os

# Add parent directory to path to allow `from backend import app`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.app import app
from backend.routes import _reset_transactions

def perform_reset():
    """
    Uses the main application context to call the _reset_transactions function.
    """
    with app.app_context():
        try:
            print("Starting the reset process for transactions...")
            _reset_transactions()
            print("Successfully reset all transactions, customers/suppliers balances, and account balances.")
        except Exception as e:
            import traceback
            print(f"An error occurred during the reset: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    perform_reset()