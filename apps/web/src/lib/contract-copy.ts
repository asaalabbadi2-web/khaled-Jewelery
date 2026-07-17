/**
 * FC-5 — Copy is Contract.
 * Every Arabic string in the UI lives here. Components and tests import from
 * this file ONLY — never inline Arabic strings in JSX.
 * Changing any string here is a contract-level change requiring review.
 */

export const COPY = {
  // ─── Gold Live Bar ──────────────────────────────────────────
  goldBar: {
    ariaLabel:           'أسعار الذهب اللحظية',
    lastUpdatedPrefix:   'آخر تحديث قبل',
    lastUpdatedSuffix:   'ثانية',
    updating:            'جارٍ تحديث الأسعار',
    halted:              'تحديث الأسعار متوقف مؤقتًا. التصفح متاح والحجز يعود قريبًا',
    perGram:             'ر.س/غ',
  },

  // ─── System banners ─────────────────────────────────────────
  banners: {
    halted:  'تحديث الأسعار متوقف مؤقتًا. التصفح متاح والحجز يعود قريبًا',
    offline: 'لا اتصال — الأسعار المعروضة قد تكون قديمة',
    offlineCheckout: 'انقطع الاتصال — حجزك محفوظ في الخادم وسنحدّث حالته تلقائيًا',
  },

  // ─── Item availability ───────────────────────────────────────
  availability: {
    available:       'متاح',
    reservedByOther: 'محجوزة الآن — قد تتاح خلال دقائق',
    sold:            'بيعت هذه القطعة',
    viewOverlay:     'عرض',
  },

  // ─── Navigation & layout ────────────────────────────────────
  nav: {
    jewellery: 'المجوهرات',
    about:     'عن الشركة',
    track:     'تتبع الطلب',
    search:    'بحث',
    menu:      'القائمة',
  },

  // ─── SiteFooter ─────────────────────────────────────────────
  footer: {
    priceNote: 'الأسعار تُحدَّث آليًا من سوق الذهب',
    links: {
      faq:     'الأسئلة الشائعة',
      returns: 'سياسة الاسترجاع',
      terms:   'الشروط والأحكام',
      privacy: 'سياسة الخصوصية',
    },
    navAriaLabel: 'روابط الموقع',
  },

  // ─── PricingCard ─────────────────────────────────────────────
  pricing: {
    priceLabel:        'السعر الحالي',
    priceUnit:         'ر.س',
    priceDetails:      'تفاصيل السعر',
    priceLocked:       '— السعر مثبَّت',
    reserveCta:        'احجز القطعة والسعر',
    reserveNote:       'الحجز يثبّت السعر والقطعة لمدة 10 دقائق لإتمام الدفع',
    reserved:          'تم حجز القطعة والسعر',
    reservedExclusive: 'القطعة محجوزة لك حصريًا حتى انتهاء المهلة',
    cancelLink:        'إلغاء الحجز',
    timeLabel:         'الوقت المتبقي للدفع',
    urgentWarning:     'أقل من دقيقة — أكمل الدفع الآن',
    checkoutCta:       'إتمام الدفع',
    expiredTitle:      'انتهت مهلة الحجز',
    prevPrice:         'السعر السابق',
    newPrice:          'السعر الحالي',
    reserveNewCta:     'احجز بالسعر الجديد',
    staleUpdating:     'جارٍ تحديث السعر — الحجز يعود خلال لحظات',
    reservedByOther:   'هذه القطعة محجوزة الآن',
    reservedByOtherSub:'إن لم يكتمل شراؤها خلال دقائق تعود متاحة هنا',
    raceConflict:      'سبقك إليها عميل آخر قبل لحظات — إن لم يكمل الدفع خلال دقائق تعود متاحة',
    soldTitle:         'بيعت هذه القطعة',
    soldSub:           'هذه القطعة وجدت من يقدّرها. استعرض قطعًا ذات طابع مشابه أدناه.',
    browseSimilar:     'تصفح قطعًا مشابهة',
    verifyingTitle:    'نتحقق من دفعتك…',
    verifyingNote:     'دفعتك مسجلة لدى بوابة الدفع — لا تعد المحاولة',
    latePaymentTitle:  'وصل دفعك بعد انتهاء مهلة الحجز',
    latePaymentNote:   'نُعيد المبلغ كاملًا تلقائيًا — لا يلزمك أي إجراء',
    refundedTitle:     'تم استرداد المبلغ كاملًا',
    refundedNote:      'المبلغ في طريقه إلى حسابك خلال 3–5 أيام عمل.',
    offlineNote:       'انقطع الاتصال — حجزك محفوظ في الخادم وسنحدّث حالته تلقائيًا',
    cancelledFrozen:   'العداد متوقف مؤقتًا بسبب انقطاع الاتصال',
  },

  // ─── OrderTimeline ───────────────────────────────────────────
  timeline: {
    paid:            'تم الدفع',
    orderCreated:    'جارٍ إنشاء الطلب',
    preparing:       'جارٍ تجهيز القطعة',
    shipmentReady:   'جُهّزت الشحنة (مؤمَّنة بالكامل)',
    shipped:         'خرجت للتوصيل',
    delivered:       'تم التسليم',
    ariaLabel:       'حالة الطلب',
  },

  // ─── ReservationStrip (checkout) ────────────────────────────
  reservationStrip: {
    label:   'شريط الحجز',
    message: 'قطعتك محجوزة — الوقت المتبقي لإتمام الدفع',
    frozen:  'مجمّد',
  },

  // ─── Checkout ────────────────────────────────────────────────
  checkout: {
    securePayment:     'دفع آمن',
    step1Label:        'العنوان',
    step2Label:        'الدفع',
    stepAriaLabel:     (n: number) => `الخطوة ${n} من 2`,
    fieldName:         'الاسم الكامل',
    fieldPhone:        'رقم الجوال',
    fieldEmail:        'البريد الإلكتروني',
    fieldCity:         'المدينة',
    fieldDistrict:     'الحي',
    fieldAddress:      'العنوان التفصيلي',
    fieldNotes:        'ملاحظات للتوصيل',
    phoneHint:         'سنرسل تأكيد الطلب ورابط التتبع إلى هذا الرقم',
    deliveryNote:      'التسليم يتطلب توقيع المستلم — الشحنة مؤمَّنة بالكامل',
    step1Cta:          'متابعة إلى الدفع',
    paymentNoCard:     'ستنتقل إلى صفحة الدفع الآمنة لإتمام العملية — لا نحتفظ ببيانات بطاقتك إطلاقًا',
    paymentNote:       'بإتمام الدفع خلال المهلة يُعتمد السعر المثبّت نهائيًا',
    paymentCta:        'الانتقال إلى الدفع الآمن',
    editAddress:       'تعديل',
    paymentFailed:     'لم تكتمل عملية الدفع',
    paymentFailedNote: 'لم يُخصم أي مبلغ',
    retryPayment:      'إعادة محاولة الدفع',
    cancelLink:        'إلغاء الحجز',
    cancelModalTitle:  'إلغاء الحجز',
    cancelModalBody:   'سيُلغى حجز القطعة والسعر فورًا وتُتاح لغيرك',
    cancelConfirm:     'تأكيد الإلغاء',
    cancelDismiss:     'البقاء في الدفع',
    lockedTotal:       'الإجمالي المثبّت',
    priceFixed:        'هذا السعر نهائي — لن يتغير بعد الحجز',
    successTitle:      'تم الدفع — القطعة لك',
    successNote:       'أرسلنا رقم الطلب ورابط التتبع إلى جوالك',
    trackCta:          'تتبع الطلب',
    backToCatalog:     'العودة للمجوهرات',
    expiredTitle:      'انتهت مهلة الحجز',
    expiredDataSaved:  'بياناتك محفوظة — لن تعيد إدخالها',
    expiredRebookCta:  'احجز بالسعر الجديد',
    expiredBackCta:    'العودة للقطعة',
    redirectingTitle:  'ننقلك إلى صفحة الدفع الآمنة…',
    redirectingNote:   'لا تغلق هذه الصفحة',
    verifyingTitle:    'نتحقق من دفعتك…',
    verifyingNote:     'دفعتك مسجلة لدى بوابة الدفع — لا تعد المحاولة ولا تغلق الصفحة',
    lateRefundTitle:   'وصل دفعك بعد انتهاء مهلة الحجز',
    lateRefundNote:    'نُعيد المبلغ كاملًا تلقائيًا — لا يلزمك أي إجراء',
    refundPending:     'جارٍ تنفيذ الاسترداد',
    refundDone:        'تم استرداد المبلغ كاملًا',
    rebookCta:         'احجز من جديد',
    paymentMethods:    'وسائل الدفع المقبولة',
  },

  // ─── Tracking ────────────────────────────────────────────────
  tracking: {
    pageTitle:        'تتبع طلبك',
    orderNumberLabel: 'رقم الطلب',
    sendOtpCta:       'إرسال رمز التحقق',
    otpDigitLabel:    (n: number) => `الرقم ${n} من رمز التحقق`,
    otpHint:          'سنرسل رمزًا إلى رقم الجوال المستخدم في الطلب',
    otpVerify:        'تحقق',
    otpResend:        'إعادة الإرسال',
    otpResendAfter:   (s: number) => `إعادة الإرسال بعد 00:${String(s).padStart(2, '0')}`,
    otpWrong:         'الرمز غير صحيح — حاول مرة أخرى',
    otpMaxAttempts:   'محاولات كثيرة — أعد المحاولة بعد دقائق',
    expiredLinkNote:  'انتهت صلاحية هذا الرابط — أدخل رقم طلبك لإرسال رمز جديد',
    notFoundNote:     'لم نجد طلبًا بهذا الرقم — تحقق من الرابط في رسالتك',
    contactUs:        'تواصل معنا',
    lockedTotal:      'الإجمالي المدفوع',
    carrierTrackNo:   'رقم التتبع لدى الناقل',
    copy:             'نسخ رقم التتبع',
    copied:           'تم النسخ',
    carrierLastUpdate: (n: string) => `آخر تحديث من الناقل قبل ${n} دقيقة`,
    deliveredNote:    'نتمنى أن تسعدك قطعتك',
    browseCta:        'استعرض قطعًا أخرى',
    refundedTitle:    'أُلغي هذا الطلب واستُرد المبلغ كاملًا',
    refundedDate:     (d: string) => `تاريخ الاسترداد: ${d}`,
    supportLine:      'سؤال عن طلبك؟',
    offlineNote:      (n: string) => `انقطع الاتصال — آخر حالة معروفة قبل ${n} دقيقة`,
    ariaAnnounce: {
      entry:        'صفحة تتبع الطلب',
      otpSent:      'تم إرسال رمز التحقق',
      orderActive:  'تم التحقق من الطلب',
      stateUpdated: 'تم تحديث حالة التتبع',
    },
  },

  // ─── Catalog (product list) ──────────────────────────────────
  catalog: {
    filterLabel:  'الفلاتر',
    filterClose:  'إغلاق',
    filterApply:  'عرض النتائج',
    filterClear:  'مسح الكل',
    filterAria:   (n: number) => `تصفية${n > 0 ? ` (${n})` : ''}`,
    resultsAria:  'قائمة القطع',
    emptyFiltered:      'لا نتائج تطابق هذه الفلاتر',
    emptyFilteredSub:   'حاول تعديل الفلاتر أو مسحها للاطلاع على المجموعة الكاملة',
    clearFiltersCta:    'مسح الفلاتر',
    nearestLabel:       'الأقرب لبحثك',
    trulyEmpty:         'لا قطع في هذا القسم حاليًا',
    trulyEmptySub:      'تصل مجموعات جديدة دوريًا',
    sortNewest:         'الأحدث',
    sortPriceAsc:       'السعر: من الأقل',
    sortPriceDesc:      'السعر: من الأعلى',
    sortWeight:         'الوزن',
    karatGroup:         'العيار',
    weightGroup:        'الوزن',
    categoryGroup:      'الفئة',
    priceGroup:         'السعر',
    weightLt5:          'أقل من 5غ',
    weight5to10:        '5–10غ',
    weightGt10:         'أكثر من 10غ',
    paginationAria:     'صفحات النتائج',
    paginationPrev:     'السابق',
    paginationNext:     'التالي',
    paginationOf:       (curr: number, total: number) => `${curr} من ${total}`,
    karat24:            '24K',
    karat21:            '21K',
    karat18:            '18K',
    priceRangeLt1000:   'أقل من 1,000',
    priceRange1to2k:    '1,000 – 2,000',
    priceRangeGt2k:     'أكثر من 2,000',
    resultsCount:       (n: number) => `${n} قطعة`,
    sortLabel:          'الترتيب',
    filterCta:          (n: number) => `الفلاتر${n > 0 ? ` (${n})` : ''}`,
  },

  // ─── HomePage ────────────────────────────────────────────────
  home: {
    heroTitle:      'مجوهرات تُقتنى بسعر الذهب الحي',
    heroSub:        'كل قطعة فريدة — سعرها مشتق من سعر الذهب لحظة الشراء، وتُحجز لك حصريًا حتى إتمام الدفع',
    chipLiveGold:   'ذهب حي',
    chipInstant:    'حجز فوري',
    chipSafe:       'دفع آمن',
    chipShipping:   'شحن مؤمَّن',
    browseCta:      'استعرض المجوهرات',
    trackCta:       'تتبع طلبك',
    collectionsH2:  'تسوق حسب الفئة',
    featuredH2:     'قطع مختارة',
    viewAllCta:     'عرض جميع القطع ←',
    howItWorksH2:   'كيف تشتري قطعة فريدة',
    step1:          'اختر القطعة',
    step2:          'احجز القطعة والسعر',
    step3:          'أكمل الدفع خلال 10 دقائق',
    step4:          'نشحنها إليك مؤمَّنة بالكامل',
    whyTitle:       (brand: string) => `لماذا ${brand}`,
    whyLivePrice:   'سعر مباشر من سوق الذهب',
    whyUnique:      'قطعة واحدة لا تتكرر',
    whyCert:        'شهادة أصالة مع كل قطعة',
    whyShipping:    'شحن مؤمَّن حتى باب المنزل',
    heroImgAlt:     'خاتم سوليتير ذهب أصفر عيار 21 — القطعة الرئيسية',
    colRings:       'الخواتم',
    colBracelets:   'الأساور',
    colNecklaces:   'العقود',
    colSets:        'الطقم',
    colRingsSub:    'عيار 21K · 18K',
    colBraceletsSub:'عيار 21K',
    colNecklacesSub:'عيار 21K',
    colSetsSub:     'طقم ذهبي متناسق',
    whyLivePriceSub: 'مشتق من سعر الصرف اللحظي',
    whyUniqueSub:    'لا إنتاج تسلسلي — كل قطعة فردية',
    whyCertSub:      'ضمان الأصالة والعيار',
    whyShippingSub:  'تغطية تأمينية كاملة حتى باب منزلك',
  },

  // ─── ProductPage ────────────────────────────────────────────
  product: {
    pieceNumberLabel: 'رقم القطعة',
    specKarat:        'العيار',
    specWeight:       'الوزن',
    specMaterial:     'المعدن',
    specStone:        'الأحجار',
    specValue:        { karat: (k: number) => `${k}K ذهب أصفر`, weight: (w: number) => `${w.toFixed(2)}غ`, material: 'ذهب أصفر', stone: 'زركون' },
    trustCert:        'شهادة أصالة',
    trustUnique:      'قطعة فريدة لا تتكرر',
    trustShipping:    'شحن مؤمَّن',
    similarTitle:     'قطع مشابهة',
    thumbnailAlt:     (n: number) => `زاوية ${n}`,
  },

  // ─── ProductCard ────────────────────────────────────────────
  productCard: {
    viewOverlay:    'عرض',
    unit:           'غ',
    priceUnit:      'ر.س',
    staleTime:      'آخر تحديث 12:30',
    uniquePiece:    'قطعة واحدة فريدة',
    ariaLabel:      (name: string, k: number, w: number, p: string) =>
      `${name}، ${k}K، ${w}غ، ${p} ريال`,
    browseCategory: (cat: string) => `تصفح فئة ${cat}`,
  },

  // ─── Static pages (CMS placeholder bodies) ──────────────────
  // These are UI strings used until production CMS copy is delivered.
  staticPages: {
    about:   { title: 'عن الشركة',        body: 'مجوهرات خالد — نُقدّم قطعًا ذهبية فريدة بسعر مباشر من سوق الذهب.' },
    faq:     { title: 'الأسئلة الشائعة',  body: 'أسئلة عامة وإجابات عن كيفية الشراء والحجز والتوصيل.' },
    returns: { title: 'سياسة الاسترجاع', body: 'يحق للعميل إرجاع القطعة خلال 7 أيام من الاستلام بشرط عدم الاستخدام.' },
    terms:   { title: 'الشروط والأحكام', body: 'باستخدام المنصة توافق على الشروط والأحكام المنظِّمة للبيع والشراء.' },
    privacy: { title: 'سياسة الخصوصية', body: 'نحافظ على بيانات عملائنا ولا نشاركها مع أي طرف ثالث.' },
    orderPlaceholder: 'ORD-5511',
  },

  // ─── NotFound / static fallbacks ────────────────────────────
  notFound: {
    title:     'لم نجد هذه الصفحة',
    sub:       'ربما انتقلت القطعة أو تغيّر الرابط',
    browseCta: 'استعرض المجوهرات',
    trackCta:  'تتبع طلبك',
    homeCta:   'الصفحة الرئيسية',
    notFoundGlyph: '◇',
  },

  // ─── Milestones (countdown ARIA) ────────────────────────────
  countdown: {
    min5:  'تبقى 5 دقائق لإتمام الدفع',
    min1:  'تبقت دقيقة واحدة لإتمام الدفع',
    sec30: 'تبقت 30 ثانية لإتمام الدفع',
  },

  // ─── Reservation status (domain enum labels) ─────────────────
  reservationStatus: {
    ACTIVE:    'الحجز نشط',
    CONFIRMED: 'تم التأكيد',
    EXPIRED:   'انتهى الحجز',
    CANCELLED: 'تم الإلغاء',
  },

  // ─── Payment status ──────────────────────────────────────────
  paymentStatus: {
    PENDING:        'في انتظار الدفع',
    PAID:           'تم الدفع',
    FAILED:         'فشل الدفع',
    REFUND_PENDING: 'جارٍ الاسترداد',
    REFUNDED:       'تم الاسترداد',
  },

  // ─── Order status ────────────────────────────────────────────
  orderStatus: {
    PAID:             'تم الدفع',
    PREPARING:        'قيد التجهيز',
    SHIPMENT_CREATED: 'تم إنشاء الشحنة',
    SHIPPED:          'في الطريق',
    DELIVERED:        'تم التسليم',
    CANCELLED:        'ملغى',
  },

  // ─── Empty / error states (FC-4 — No Dead Ends) ──────────────
  empty: {
    noOrders:    'لا توجد طلبات بعد',
    browseLink:  'تصفح المجوهرات',
    errorGeneric: 'حدث خطأ، يرجى المحاولة مجدداً',
    errorAction:  'إعادة المحاولة',
  },
} as const

// ─── Back-compat named exports (scaffold code uses these) ─────
export const goldLiveBar = {
  fresh:  (s: number) =>
    `${COPY.goldBar.lastUpdatedPrefix} ${s} ${COPY.goldBar.lastUpdatedSuffix}`,
  stale:  COPY.goldBar.updating,
  halted: COPY.goldBar.halted,
} as const
