// Web implementation using dart:html
import 'dart:async';
import 'dart:html';

Future<String?> pickJsonFile() {
  final input = FileUploadInputElement();
  input.accept = '.json,application/json';
  input.multiple = false;

  final completer = Completer<String?>();

  input.onChange.listen((_) {
    final files = input.files;
    if (files == null || files.isEmpty) {
      completer.complete(null);
      return;
    }
    final file = files.first;
    final reader = FileReader();
    reader.onLoad.listen((evt) {
      completer.complete(reader.result as String?);
    });
    reader.onError.listen((err) {
      completer.completeError('Failed to read file');
    });
    reader.readAsText(file);
  });

  // Trigger picker
  input.click();
  return completer.future;
}

void downloadString(String filename, String content) {
  final blob = Blob([content], 'application/json');
  final url = Url.createObjectUrlFromBlob(blob);
  final anchor = AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..style.display = 'none';
  document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  Url.revokeObjectUrl(url);
}

void downloadBytes(String filename, List<int> bytes, String mimeType) {
  final blob = Blob([bytes], mimeType);
  final url = Url.createObjectUrlFromBlob(blob);
  final anchor = AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..style.display = 'none';
  document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  Url.revokeObjectUrl(url);
}
