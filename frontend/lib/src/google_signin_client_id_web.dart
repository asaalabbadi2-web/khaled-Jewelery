// ignore_for_file: avoid_web_libraries_in_flutter

import 'dart:html' as html;

String? readGoogleSignInClientIdFromMeta() {
  final el = html.document.querySelector('meta[name="google-signin-client_id"]');
  final content = el?.getAttribute('content')?.trim();
  if (content == null || content.isEmpty) return null;
  return content;
}
