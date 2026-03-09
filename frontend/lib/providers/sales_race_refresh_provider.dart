import 'package:flutter/foundation.dart';

class SalesRaceRefreshProvider with ChangeNotifier {
  int _refreshToken = 0;

  int get refreshToken => _refreshToken;

  void notifySaleInvoiceSaved() {
    _refreshToken += 1;
    notifyListeners();
  }
}
