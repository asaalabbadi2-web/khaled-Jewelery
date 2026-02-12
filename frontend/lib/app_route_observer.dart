import 'package:flutter/widgets.dart';

/// Shared route observer used to detect when a screen becomes visible again
/// after another route is popped.
final RouteObserver<PageRoute<dynamic>> routeObserver =
    RouteObserver<PageRoute<dynamic>>();
