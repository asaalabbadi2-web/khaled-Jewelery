# إعدادات النظام
MAIN_KARAT = 21  # العيار الرئيسي للذهب


# ╔════════════════════════════════════════════════════════════╗
# ║  إعدادات الحسابات الداعمة لتسكير الوزن                    ║
# ╚════════════════════════════════════════════════════════════╝
#
# القائمة التالية تُستخدم لإنشاء وربط حسابات المصاريف/الفروقات
# مع حساباتها الوزنية (المذكرة) بشكل ديناميكي. يمكن إضافة أو تعديل
# العناصر هنا دون الحاجة لتعديل الكود الأساسي.

WEIGHT_SUPPORT_ACCOUNTS = [
	{
		'key': 'manufacturing_wage',
		'financial': {
			'account_number': '1340',
			'name': 'مخزون أجور مصنعية',
			'type': 'Asset',
			'transaction_type': 'cash',
			'tracks_weight': False,
			'parent_number': '13',
		},
		'memo': {
			'account_number': '71340',
			'name': 'مخزون أجور مصنعية وزني',
			'type': 'Asset',
			'transaction_type': 'gold',
			'tracks_weight': True,
			'parent_number': '71',
		},
	},
	{
		'key': 'cleaning',
		'financial': {
			'account_number': '5110',
			'name': 'مصاريف نظافة',
			'type': 'Expense',
			'transaction_type': 'cash',
			'tracks_weight': False,
			'parent_number': '51',
		},
		'memo': {
			'account_number': '7510',
			'name': 'مصاريف نظافة وزنية',
			'type': 'Expense',
			'transaction_type': 'gold',
			'tracks_weight': True,
			'parent_number': '75',
		},
	},
	{
		'key': 'melting',
		'financial': {
			'account_number': '5120',
			'name': 'مصاريف صهر',
			'type': 'Expense',
			'transaction_type': 'cash',
			'tracks_weight': False,
			'parent_number': '51',
		},
		'memo': {
			'account_number': '7520',
			'name': 'مصاريف صهر وزنية',
			'type': 'Expense',
			'transaction_type': 'gold',
			'tracks_weight': True,
			'parent_number': '75',
		},
	},
	{
		'key': 'logistics',
		'financial': {
			'account_number': '5130',
			'name': 'مصاريف شحن وتغليف',
			'type': 'Expense',
			'transaction_type': 'cash',
			'tracks_weight': False,
			'parent_number': '51',
		},
		'memo': {
			'account_number': '7530',
			'name': 'مصاريف شحن وزنية',
			'type': 'Expense',
			'transaction_type': 'gold',
			'tracks_weight': True,
			'parent_number': '75',
		},
	},
	{
		'key': 'valuation_diff',
		'financial': {
			'account_number': '3600',
			'name': 'فروقات تقييم الذهب',
			'type': 'Equity',
			'transaction_type': 'cash',
			'tracks_weight': False,
			'parent_number': '3',
		},
		'memo': {
			'account_number': '7600',
			'name': 'فروقات تقييم وزنية',
			'type': 'Equity',
			'transaction_type': 'gold',
			'tracks_weight': True,
			'parent_number': '73',  # الأب الصحيح: حقوق الملكية وزني
		},
	},
]


# ╔════════════════════════════════════════════════════════════╗
# ║  بروفايلات عمليات الوزن (يتم استخدامها لاحقاً في الخدمات)  ║
# ╚════════════════════════════════════════════════════════════╝
# هذه مجرد هيكل مبدئي وسيتم ملؤها خلال مراحل التطوير التالية.

WEIGHT_EXECUTION_PROFILES = {
	# مثال توضيحي، سيتم استكمال التفاصيل في الخطوات القادمة
	'cleaning': {
		'display_name': 'تنظيف الذهب',
		'support_account_key': 'cleaning',
		'execution_type': 'expense',
		'requires_cash_amount': True,
		'requires_weight': False,
		'price_strategy': 'live_or_manual',
	},
	'melting': {
		'display_name': 'عمليات الصهر',
		'support_account_key': 'melting',
		'execution_type': 'expense',
		'requires_cash_amount': True,
		'requires_weight': False,
		'price_strategy': 'live_or_manual',
	},
	'logistics': {
		'display_name': 'شحن وتغليف',
		'support_account_key': 'logistics',
		'execution_type': 'expense',
		'requires_cash_amount': True,
		'requires_weight': False,
		'price_strategy': 'live_or_manual',
	},
	'valuation_adjustment': {
		'display_name': 'تعديل فروقات التقييم',
		'support_account_key': 'valuation_diff',
		'execution_type': 'variance',
		'requires_cash_amount': False,
		'requires_weight': True,
		'price_strategy': 'reference_order',
	},
}

# يمكن لاحقاً إضافة إعدادات أخرى مثل سعر الأونصة المرجعي
