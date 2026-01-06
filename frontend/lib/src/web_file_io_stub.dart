// Stub implementation for non-web platforms.
import 'dart:async';

Future<String?> pickJsonFile() async {
  // Not supported on non-web platforms via this helper.
  return null;
}

void downloadString(String filename, String content) {
  // No-op on non-web platforms.
}
