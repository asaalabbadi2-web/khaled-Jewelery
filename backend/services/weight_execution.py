"""خدمات مساندة لبروفايلات عمليات الوزن والتكاليف."""

from typing import Dict, Optional

from config import WEIGHT_SUPPORT_ACCOUNTS, WEIGHT_EXECUTION_PROFILES
from models import Account


class WeightSupportRegistry:
    """تجميع سريع لإعدادات الحسابات الداعمة مع أدوات استعلام."""

    def __init__(self):
        self._by_key = {entry['key']: entry for entry in WEIGHT_SUPPORT_ACCOUNTS}

    def get_account_numbers(self, key: str):
        entry = self._by_key.get(key or '')
        if not entry:
            return None, None
        financial_number = (entry.get('financial') or {}).get('account_number')
        memo_number = (entry.get('memo') or {}).get('account_number')
        return financial_number, memo_number

    def resolve_accounts(self, key: str):
        financial_number, memo_number = self.get_account_numbers(key)
        financial = Account.query.filter_by(account_number=financial_number).first() if financial_number else None
        memo = Account.query.filter_by(account_number=memo_number).first() if memo_number else None
        return financial, memo


_support_registry = WeightSupportRegistry()


def list_weight_profiles():
    """إرجاع قائمة مبسطة للبروفايلات المتاحة مع معلومات العرض."""
    profiles = []
    for key, profile in WEIGHT_EXECUTION_PROFILES.items():
        profiles.append(
            {
                'key': key,
                'display_name': profile.get('display_name', key.title()),
                'requires_cash_amount': profile.get('requires_cash_amount', False),
                'requires_weight': profile.get('requires_weight', False),
                'price_strategy': profile.get('price_strategy', 'manual'),
                'execution_type': profile.get('execution_type', 'expense'),
            }
        )
    return profiles


def resolve_weight_profile(profile_key: str) -> Dict:
    profile = WEIGHT_EXECUTION_PROFILES.get(profile_key)
    if not profile:
        raise ValueError(f"Weight execution profile '{profile_key}' غير معرّف")

    financial_account, memo_account = _support_registry.resolve_accounts(profile.get('support_account_key'))

    return {
        'key': profile_key,
        'meta': profile,
        'financial_account': financial_account,
        'memo_account': memo_account,
    }


def ensure_profile_accounts_ready(profile_key: Optional[str] = None) -> bool:
    """تأكد من توفر الحسابات الخاصة ببروفايل معين أو بجميع البروفايلات."""
    if profile_key:
        profile = resolve_weight_profile(profile_key)
        return bool(profile['financial_account'] and profile['memo_account'])

    for key in WEIGHT_EXECUTION_PROFILES.keys():
        profile = resolve_weight_profile(key)
        if not profile['financial_account'] or not profile['memo_account']:
            return False
    return True
