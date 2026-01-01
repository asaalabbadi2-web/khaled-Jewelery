import 'package:flutter/foundation.dart';

/// ناقل بسيط لإشعار الشاشات بتغيّر بيانات الكيانات المشتركة.
/// حالياً ندعم الأصناف فقط، ويمكن توسيعه لاحقاً لبقية الكيانات.
class DataSyncBus {
  DataSyncBus._();

  static final ValueNotifier<int> _itemsRevision = ValueNotifier<int>(0);

  static ValueListenable<int> get itemsRevision => _itemsRevision;

  /// زيادة رقم النسخة لإجبار المستمعين على إعادة تحميل بيانات الأصناف.
  static void notifyItemsChanged() {
    _itemsRevision.value++;
  }
}
