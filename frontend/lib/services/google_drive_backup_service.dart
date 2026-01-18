import 'dart:async';
import 'dart:typed_data';

import 'package:google_sign_in/google_sign_in.dart';
import 'package:googleapis/drive/v3.dart' as drive;
import 'package:extension_google_sign_in_as_googleapis_auth/extension_google_sign_in_as_googleapis_auth.dart';

class GoogleDriveBackupService {
  GoogleDriveBackupService()
      : _googleSignIn = GoogleSignIn(
          scopes: const <String>[drive.DriveApi.driveFileScope],
        );

  final GoogleSignIn _googleSignIn;

  GoogleSignInAccount? get currentUser => _googleSignIn.currentUser;

  Stream<GoogleSignInAccount?> get onUserChanged => _googleSignIn.onCurrentUserChanged;

  Future<GoogleSignInAccount?> signIn() async {
    // Attempt silent sign-in first.
    final existing = await _googleSignIn.signInSilently();
    if (existing != null) return existing;
    return _googleSignIn.signIn();
  }

  Future<void> signOut() => _googleSignIn.signOut();

  Future<drive.DriveApi> _driveApi() async {
    final user = _googleSignIn.currentUser ?? await signIn();
    if (user == null) {
      throw StateError('Google Sign-In cancelled');
    }

    final client = await _googleSignIn.authenticatedClient();
    if (client == null) {
      throw StateError('Failed to create authenticated client');
    }

    return drive.DriveApi(client);
  }

  Future<String> _ensureBackupsFolderId(drive.DriveApi api) async {
    // Search for an existing folder.
    final q = "mimeType='application/vnd.google-apps.folder' and name='YasarGold Backups' and trashed=false";
    final res = await api.files.list(
      q: q,
      spaces: 'drive',
      $fields: 'files(id,name)',
    );

    final existing = res.files?.isNotEmpty == true ? res.files!.first : null;
    if (existing?.id != null) return existing!.id!;

    // Create folder.
    final folder = drive.File()
      ..name = 'YasarGold Backups'
      ..mimeType = 'application/vnd.google-apps.folder';

    final created = await api.files.create(folder, $fields: 'id');
    if (created.id == null) {
      throw StateError('Failed to create Drive folder');
    }
    return created.id!;
  }

  Future<String> uploadBackupZip({
    required String filename,
    required Uint8List bytes,
    String? mimeType,
  }) async {
    final api = await _driveApi();
    final folderId = await _ensureBackupsFolderId(api);

    final media = drive.Media(Stream<List<int>>.value(bytes), bytes.length);
    final file = drive.File()
      ..name = filename
      ..mimeType = (mimeType ?? (filename.toLowerCase().endsWith('.zip') ? 'application/zip' : 'application/octet-stream'))
      ..parents = <String>[folderId];

    final created = await api.files.create(
      file,
      uploadMedia: media,
      $fields: 'id,name,createdTime,size',
    );

    if (created.id == null) {
      throw StateError('Upload failed');
    }
    return created.id!;
  }

  Future<List<drive.File>> listBackupZips({int pageSize = 20}) async {
    final api = await _driveApi();
    final folderId = await _ensureBackupsFolderId(api);

    final q = "'$folderId' in parents and trashed=false and mimeType='application/zip'";
    final res = await api.files.list(
      q: q,
      orderBy: 'createdTime desc',
      pageSize: pageSize,
      $fields: 'files(id,name,createdTime,size)',
    );

    return res.files ?? <drive.File>[];
  }

  Future<Uint8List> downloadFileBytes(String fileId) async {
    final api = await _driveApi();

    final media = await api.files.get(
      fileId,
      downloadOptions: drive.DownloadOptions.fullMedia,
    );

    if (media is! drive.Media) {
      throw StateError('Unexpected download response');
    }

    final chunks = <int>[];
    await for (final c in media.stream) {
      chunks.addAll(c);
    }
    return Uint8List.fromList(chunks);
  }
}
