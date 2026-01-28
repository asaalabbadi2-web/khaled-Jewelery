import 'google_signin_client_id_stub.dart'
    if (dart.library.html) 'google_signin_client_id_web.dart' as impl;

String? readGoogleSignInClientIdFromMeta() => impl.readGoogleSignInClientIdFromMeta();
