import 'package:flutter/foundation.dart';

/// Global event notifiers for cross-screen refresh signals.
class AppEvents {
  AppEvents._();

  /// Incremented whenever a posting or unposting operation completes.
  /// Screens that show vault balances or dashboards should listen to this
  /// and reload their data when it changes.
  static final ValueNotifier<int> vaultRefreshSignal = ValueNotifier<int>(0);

  /// Trigger a vault refresh signal (call after post/unpost).
  static void notifyVaultChanged() {
    vaultRefreshSignal.value += 1;
  }
}
