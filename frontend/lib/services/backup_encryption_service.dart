import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class BackupEncryptionService {
  static const _secureKeyName = 'backup_device_master_key_v1';

  final FlutterSecureStorage _secureStorage;
  final Cipher _cipher;
  final Pbkdf2 _kdf;
  final HashAlgorithm _hash;

  BackupEncryptionService({FlutterSecureStorage? secureStorage})
      : _secureStorage = secureStorage ?? const FlutterSecureStorage(),
        _cipher = AesGcm.with256bits(),
        _hash = Sha256(),
        _kdf = Pbkdf2(
          macAlgorithm: Hmac.sha256(),
          iterations: 150000,
          bits: 256,
        );

  Future<String> _sha256B64(Uint8List bytes) async {
    final digest = await _hash.hash(bytes);
    return base64Encode(Uint8List.fromList(digest.bytes));
  }

  Future<void> forgetSavedKey() => _secureStorage.delete(key: _secureKeyName);

  Future<bool> hasSavedKey() async => (await _secureStorage.read(key: _secureKeyName)) != null;

  Future<SecretKey?> getSavedKey() async {
    final v = await _secureStorage.read(key: _secureKeyName);
    if (v == null || v.isEmpty) return null;
    final bytes = base64Decode(v);
    return SecretKey(bytes);
  }

  Future<void> saveKey(SecretKey key) async {
    final raw = await key.extractBytes();
    await _secureStorage.write(key: _secureKeyName, value: base64Encode(raw));
  }

  Future<SecretKey> getOrCreateDeviceKey() async {
    final existing = await getSavedKey();
    if (existing != null) return existing;
    final rng = Random.secure();
    final raw = Uint8List.fromList(List<int>.generate(32, (_) => rng.nextInt(256)));
    final key = SecretKey(raw);
    await saveKey(key);
    return key;
  }

  Future<SecretKey> deriveKeyFromPassword({
    required String password,
    required Uint8List salt,
  }) async {
    final baseKey = SecretKey(utf8.encode(password));
    return _kdf.deriveKey(
      secretKey: baseKey,
      nonce: salt,
    );
  }

  /// Encrypt bytes using AES-256-GCM.
  ///
  /// Output format: JSON (UTF-8) with base64 fields.
  /// {
  ///   "v": 1,
  ///   "alg": "aes-256-gcm",
  ///   "kdf": "pbkdf2-hmac-sha256",
  ///   "iter": 150000,
  ///   "sha256": "...",
  ///   "salt": "...",
  ///   "nonce": "...",
  ///   "ct": "...",
  ///   "mac": "..."
  /// }
  Future<Uint8List> encrypt({
    required Uint8List plaintext,
    String? password,
    bool useDeviceKey = false,
  }) async {
    final rng = Random.secure();
    final salt = Uint8List.fromList(List<int>.generate(16, (_) => rng.nextInt(256)));
    final nonce = Uint8List.fromList(List<int>.generate(12, (_) => rng.nextInt(256)));

    SecretKey key;
    String mode;
    Map<String, dynamic> kdfInfo;

    if (useDeviceKey) {
      key = await getOrCreateDeviceKey();
      mode = 'device';
      kdfInfo = {};
    } else {
      final pwd = (password ?? '').trim();
      if (pwd.isEmpty) {
        throw StateError('أدخل كلمة مرور للتشفير أو استخدم مفتاح الجهاز.');
      }
      key = await deriveKeyFromPassword(password: pwd, salt: salt);
      mode = 'password';
      kdfInfo = {
        'kdf': 'pbkdf2-hmac-sha256',
        'iter': 150000,
        'salt': base64Encode(salt),
      };
    }

    final box = await _cipher.encrypt(
      plaintext,
      secretKey: key,
      nonce: nonce,
    );

    final plaintextHash = await _sha256B64(plaintext);

    // GCM box.mac contains the authentication tag.
    final payload = {
      'v': 1,
      'alg': 'aes-256-gcm',
      'mode': mode,
      ...kdfInfo,
      'sha256': plaintextHash,
      'nonce': base64Encode(nonce),
      'ct': base64Encode(Uint8List.fromList(box.cipherText)),
      'mac': base64Encode(Uint8List.fromList(box.mac.bytes)),
    };

    return Uint8List.fromList(utf8.encode(jsonEncode(payload)));
  }

  Future<Uint8List> decrypt({
    required Uint8List encryptedBlob,
    String? password,
  }) async {
    final text = utf8.decode(encryptedBlob);
    final obj = jsonDecode(text);
    if (obj is! Map) {
      throw StateError('ملف النسخة المشفرة غير صالح');
    }
    if (obj['v'] != 1 || obj['alg'] != 'aes-256-gcm') {
      throw StateError('صيغة تشفير غير مدعومة');
    }

    final mode = (obj['mode']?.toString() ?? 'password').toLowerCase();

    final expectedHashB64 = obj['sha256']?.toString();

    final saltB64 = obj['salt']?.toString();
    final nonce = base64Decode(obj['nonce'] as String);
    final ct = base64Decode(obj['ct'] as String);
    final macBytes = base64Decode(obj['mac'] as String);

    SecretKey key;
    if (mode == 'device') {
      final saved = await getSavedKey();
      if (saved == null) {
        throw StateError('لا يوجد مفتاح جهاز محفوظ لفك التشفير على هذا الجهاز.');
      }
      key = saved;
    } else {
      final pwd = (password ?? '').trim();
      if (pwd.isEmpty) {
        throw StateError('أدخل كلمة المرور لفك التشفير.');
      }
      if (saltB64 == null || saltB64.isEmpty) {
        throw StateError('معلومات الملح (salt) مفقودة من الملف المشفّر.');
      }
      final salt = base64Decode(saltB64);
      key = await deriveKeyFromPassword(password: pwd, salt: Uint8List.fromList(salt));
    }

    final box = SecretBox(
      ct,
      nonce: nonce,
      mac: Mac(macBytes),
    );

    try {
      final plain = await _cipher.decrypt(
        box,
        secretKey: key,
      );
      final out = Uint8List.fromList(plain);

      if (expectedHashB64 != null && expectedHashB64.isNotEmpty) {
        final actualHashB64 = await _sha256B64(out);
        if (actualHashB64 != expectedHashB64) {
          throw StateError('فشل التحقق من سلامة الملف (SHA-256 mismatch)');
        }
      }

      return out;
    } on SecretBoxAuthenticationError {
      throw StateError('كلمة المرور غير صحيحة أو الملف تالف');
    }
  }
}
