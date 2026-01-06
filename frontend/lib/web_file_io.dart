// Conditional import: use html-backed implementation when running on web.
export 'src/web_file_io_stub.dart'
    if (dart.library.html) 'src/web_file_io_web.dart';
