"""
WeightLedgerService - Rule Engine for Weight Ledger Management
==============================================================

Centralizes all weight ledger logic to ensure consistent application
of the Golden Rule across the entire system.

Philosophy:
----------
1. Any cash transaction → automatically converts to weight
2. Inventory accounts → exception (physical weight only)
3. All conversions use direct market price (24k)
4. Weight balance is enforced (debit = credit)

Key Methods:
-----------
- should_create_weight_entry(account) → bool
- convert_amount_to_weight(amount, karat) → float
- is_inventory_account(account) → bool
- create_weight_entry(...) → ensures balanced weight ledger
- validate_weight_balance(journal_entry) → raises if imbalanced

Usage:
-----
Always use this service instead of creating weight entries manually.

Example:
    service = WeightLedgerService()
    service.create_weight_entry(
        journal_entry_id=je.id,
        account=cash_account,
        amount=1000,
        is_debit=True
    )
"""

import logging
from typing import Optional, Dict, Tuple
from decimal import Decimal

# سنحتاج db و Account و JournalEntryLine من models عند الاستدعاء
# لكن نتجنب الاستيراد المباشر لتفادي circular imports

logger = logging.getLogger(__name__)


class WeightImbalanceError(Exception):
    """Raised when weight ledger is not balanced"""
    pass


class WeightLedgerService:
    """Centralized service for managing weight ledger entries"""
    
    # حسابات المخزون (استثناء من القاعدة الذهبية)
    INVENTORY_ACCOUNT_PREFIXES = ['13', '1310', '71', '7131']
    
    # حسابات المذكرة (الوزن فقط)
    MEMO_ACCOUNT_PREFIX = '7'
    
    # الحد الأدنى للفرق المقبول (tolerance)
    WEIGHT_TOLERANCE = 0.0001
    
    def __init__(self, db_session=None, settings=None):
        """
        Initialize the service
        
        Args:
            db_session: SQLAlchemy session (optional, can be set later)
            settings: Settings object (optional, will fetch from DB if not provided)
        """
        self.db_session = db_session
        self.settings = settings
        self._main_karat_cache = None
        self._direct_price_cache = None
    
    def set_session(self, db_session):
        """Set the database session (for use in Flask request context)"""
        self.db_session = db_session
        return self
    
    def _get_main_karat(self) -> int:
        """Get the main karat for weight normalization"""
        if self._main_karat_cache:
            return self._main_karat_cache
        
        if self.settings and self.settings.main_karat:
            self._main_karat_cache = self.settings.main_karat
            return self._main_karat_cache
        
        # Try to fetch from DB
        if self.db_session:
            try:
                from models import Settings
                settings = self.db_session.query(Settings).first()
                if settings and settings.main_karat:
                    self._main_karat_cache = settings.main_karat
                    self.settings = settings
                    return self._main_karat_cache
            except Exception as e:
                logger.warning(f"Failed to fetch main karat from DB: {e}")
        
        # Default fallback
        from config import MAIN_KARAT
        self._main_karat_cache = MAIN_KARAT or 21
        return self._main_karat_cache
    
    def _get_direct_gold_price(self, karat: Optional[int] = None) -> float:
        """
        Get current direct gold price from market
        
        Args:
            karat: Gold karat (if None, uses main karat from settings)
        
        Returns:
            Price per gram in SAR for the specified karat (or main karat)
        """
        # 🔧 استخدام العيار الرئيسي كافتراضي بدلاً من 24k
        target_karat = karat if karat is not None else self._get_main_karat()
        
        if self._direct_price_cache:
            cached_price = self._direct_price_cache.get(target_karat, 0.0)
            if cached_price > 0:
                return cached_price
        
        if self.db_session:
            try:
                from models import GoldPrice
                latest_price = self.db_session.query(GoldPrice).order_by(
                    GoldPrice.id.desc()
                ).first()
                
                if latest_price:
                    # 🔧 حساب السعر بناءً على سعر 24k المحفوظ
                    price_24k = getattr(latest_price, 'price_per_gram_24k', 0.0)
                    
                    if price_24k > 0:
                        self._direct_price_cache = {}
                        for k in [18, 21, 22, 24]:
                            self._direct_price_cache[k] = (price_24k * k) / 24.0
                        
                        return self._direct_price_cache.get(target_karat, 0.0)
            except Exception as e:
                logger.warning(f"Failed to fetch gold price: {e}")
        
        # Fallback: حساب سعر افتراضي بناءً على العيار
        base_price_24k = 400.0
        fallback_price = (base_price_24k * target_karat) / 24.0
        logger.warning(f"Using fallback gold price for {target_karat}k: {fallback_price:.2f} SAR/g")
        return fallback_price
    
    def is_inventory_account(self, account) -> bool:
        """
        Check if account is an inventory account (exception to golden rule)
        
        Args:
            account: Account object or account_number string
        
        Returns:
            True if inventory account
        """
        account_number = getattr(account, 'account_number', account)
        if not account_number:
            return False
        
        account_str = str(account_number).strip()
        return any(account_str.startswith(prefix) for prefix in self.INVENTORY_ACCOUNT_PREFIXES)
    
    def is_memo_account(self, account) -> bool:
        """Check if account is a memo (weight-only) account"""
        account_number = getattr(account, 'account_number', account)
        if not account_number:
            return False
        
        account_str = str(account_number).strip()
        return account_str.startswith(self.MEMO_ACCOUNT_PREFIX)
    
    def should_create_weight_entry(self, account, has_memo_account: bool = True) -> bool:
        """
        Determine if a weight entry should be created for this account
        
        Args:
            account: Account object
            has_memo_account: Whether the account has a linked memo account
        
        Returns:
            True if weight entry should be created
        """
        # Memo accounts themselves don't create weight entries
        if self.is_memo_account(account):
            return False
        
        # Financial accounts with memo accounts → create weight entries
        if has_memo_account:
            return True
        
        # Inventory accounts → only if they have memo accounts
        if self.is_inventory_account(account):
            return has_memo_account
        
        return False
    
    def convert_amount_to_weight(
        self, 
        amount: float, 
        from_karat: Optional[int] = None,
        to_karat: Optional[int] = None
    ) -> float:
        """
        Convert cash amount to weight using direct gold price
        
        Args:
            amount: Amount in SAR
            from_karat: Karat for price lookup (default: main karat from settings)
            to_karat: Target karat for weight (default: main karat from settings)
        
        Returns:
            Weight in grams at target karat
            
        Example:
            1000 SAR ÷ 350 SAR/g (21k) = 2.857g @ 21k
        """
        if amount <= 0:
            return 0.0
        
        # 🔧 استخدام العيار الرئيسي كافتراضي
        main_karat = self._get_main_karat()
        source_karat = from_karat if from_karat is not None else main_karat
        target_karat = to_karat if to_karat is not None else main_karat
        
        # Get direct price for the source karat
        price_per_gram = self._get_direct_gold_price(source_karat)
        
        if price_per_gram <= 0:
            logger.error(f"Invalid gold price for {source_karat}k: {price_per_gram}")
            return 0.0
        
        # Calculate weight at source karat
        weight_at_source_karat = amount / price_per_gram
        
        # Convert to target karat if different
        if source_karat != target_karat:
            weight = (weight_at_source_karat * source_karat) / target_karat
        else:
            weight = weight_at_source_karat
        
        logger.debug(
            f"Converted {amount} SAR @ {source_karat}k ({price_per_gram} SAR/g) "
            f"→ {weight:.4f}g @ {target_karat}k"
        )
        
        return round(weight, 4)
    
    def validate_weight_balance(
        self, 
        journal_entry_id: int,
        raise_on_imbalance: bool = True
    ) -> Tuple[bool, Dict[str, float]]:
        """
        Validate that weight ledger is balanced for a journal entry
        
        Args:
            journal_entry_id: Journal entry ID
            raise_on_imbalance: Raise exception if imbalanced (default True)
        
        Returns:
            (is_balanced, details_dict)
        
        Raises:
            WeightImbalanceError: If imbalanced and raise_on_imbalance=True
        """
        if not self.db_session:
            raise RuntimeError("DB session not set. Call set_session() first.")
        
        from models import JournalEntryLine
        
        lines = self.db_session.query(JournalEntryLine).filter_by(
            journal_entry_id=journal_entry_id
        ).all()
        
        # حساب المجاميع لكل عيار
        totals = {}
        for karat in [18, 21, 22, 24]:
            debit_field = f'debit_gold_{karat}k_weight'
            credit_field = f'credit_gold_{karat}k_weight'
            
            total_debit = sum(getattr(line, debit_field, 0) or 0 for line in lines)
            total_credit = sum(getattr(line, credit_field, 0) or 0 for line in lines)
            
            difference = total_debit - total_credit
            
            totals[f'{karat}k'] = {
                'debit': round(total_debit, 4),
                'credit': round(total_credit, 4),
                'difference': round(difference, 4),
                'balanced': abs(difference) <= self.WEIGHT_TOLERANCE
            }
        
        # Check overall balance
        is_balanced = all(k['balanced'] for k in totals.values())
        
        if not is_balanced and raise_on_imbalance:
            imbalanced_karats = [
                f"{k}: debit={v['debit']}g, credit={v['credit']}g, diff={v['difference']}g"
                for k, v in totals.items()
                if not v['balanced']
            ]
            error_msg = f"Weight ledger imbalanced for JE#{journal_entry_id}:\n" + "\n".join(imbalanced_karats)
            raise WeightImbalanceError(error_msg)
        
        return is_balanced, totals
    
    def create_weight_entry(
        self,
        journal_entry_id: int,
        account,
        amount: float = 0.0,
        is_debit: bool = True,
        karat: int = 21,
        physical_weight: Optional[float] = None,
        description: str = "",
        auto_balance: bool = True
    ):
        """
        Create a weight ledger entry following the golden rule
        
        Args:
            journal_entry_id: Journal entry ID
            account: Account object
            amount: Cash amount (for conversion) or 0 if physical_weight provided
            is_debit: True for debit, False for credit
            karat: Gold karat
            physical_weight: Physical weight (for inventory only)
            description: Entry description
            auto_balance: Automatically validate balance after creation
        
        Raises:
            WeightImbalanceError: If auto_balance=True and imbalanced
        """
        if not self.db_session:
            raise RuntimeError("DB session not set")
        
        from models import JournalEntryLine
        
        # Determine weight
        if physical_weight is not None:
            # استثناء: وزن فعلي (مخزون)
            weight = physical_weight
            logger.info(f"Using physical weight: {weight}g @ {karat}k for account {account.account_number}")
        else:
            # القاعدة الذهبية: تحويل من مبلغ
            weight = self.convert_amount_to_weight(amount, from_karat=24, to_karat=karat)
            logger.info(f"Golden rule applied: {amount} SAR → {weight}g @ {karat}k")
        
        # Create the entry
        weight_field = f'weight_{karat}k_{"debit" if is_debit else "credit"}'
        
        entry = JournalEntryLine(
            journal_entry_id=journal_entry_id,
            account_id=account.id,
            **{weight_field: weight},
            description=description or f"Weight entry @ {karat}k"
        )
        
        self.db_session.add(entry)
        
        # Validate balance if requested
        if auto_balance:
            try:
                self.db_session.flush()
                self.validate_weight_balance(journal_entry_id, raise_on_imbalance=True)
            except WeightImbalanceError as e:
                logger.error(f"Weight balance validation failed: {e}")
                raise
        
        return entry


# Singleton instance (can be used across the app)
weight_ledger_service = WeightLedgerService()


# Helper functions for backwards compatibility
def should_create_weight_entry(account, has_memo_account=True):
    """Check if weight entry should be created (backwards compatible)"""
    return weight_ledger_service.should_create_weight_entry(account, has_memo_account)


def convert_amount_to_weight(amount, from_karat=24, to_karat=None):
    """Convert amount to weight (backwards compatible)"""
    return weight_ledger_service.convert_amount_to_weight(amount, from_karat, to_karat)


def is_inventory_account(account):
    """Check if inventory account (backwards compatible)"""
    return weight_ledger_service.is_inventory_account(account)
