import 'package:flutter/foundation.dart';

class SalesRaceRefreshProvider with ChangeNotifier {
  int _refreshToken = 0;

  int get refreshToken => _refreshToken;

  void notifySaleInvoiceSaved() {
    _refreshToken += 1;
    notifyListeners();
  }

  /// Called after settings are saved so the home screen re-fetches
  /// the leaderboard with the latest config values.
  void notifySettingsChanged() {
    _refreshToken += 1;
    notifyListeners();
  }
}
