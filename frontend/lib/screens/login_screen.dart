import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/auth_provider.dart';
import '../providers/settings_provider.dart';
import '../widgets/app_logo.dart';
import '../widgets/gold_price_ticker_bar.dart';
import 'forgot_password_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

enum _ServerStatus { checking, online, offline }

class _LoginScreenState extends State<LoginScreen>
    with TickerProviderStateMixin {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _usernameFocusNode = FocusNode();
  final _passwordFocusNode = FocusNode();
  // FocusNode ثابت للـ KeyboardListener بدلاً من إنشائه في كل build
  final _kbFocusNode = FocusNode();

  bool _obscurePassword = true;
  String? _usernameError; // خطأ حقل اسم المستخدم
  String? _loginError;    // خطأ المصادقة (أسفل كلمة المرور)
  _ServerStatus _serverStatus = _ServerStatus.checking;

  // ── Animations ─────────────────────────────────────────────────────────
  late AnimationController _fadeCtrl;
  late Animation<double> _fadeAnim;

  late AnimationController _shakeCtrl;
  late Animation<double> _shakeAnim;

  late AnimationController _shimmerCtrl;
  late Animation<Color?> _shimmerAnim;

  // ── Colors ──────────────────────────────────────────────────────────────
  static const _gold      = Color(0xFFB8860B);
  static const _goldLight = Color(0xFFE8C55A);
  static const _bgStart   = Color(0xFFC9962A);
  static const _bgEnd     = Color(0xFF8B6508);
  static const _textPrimary   = Color(0xFF2D2D2D);
  static const _textSecondary = Color(0xFF505050);
  static const _textMuted     = Color(0xFF6B6B6B);

  @override
  void initState() {
    super.initState();

    _fadeCtrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 180));
    _fadeAnim = CurvedAnimation(parent: _fadeCtrl, curve: Curves.easeIn);
    _fadeCtrl.forward();

    _shakeCtrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 500));
    _shakeAnim = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0.0, end: -9.0), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -9.0, end:  9.0), weight: 2),
      TweenSequenceItem(tween: Tween(begin:  9.0, end: -9.0), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -9.0, end:  9.0), weight: 2),
      TweenSequenceItem(tween: Tween(begin:  9.0, end:  0.0), weight: 1),
    ]).animate(CurvedAnimation(parent: _shakeCtrl, curve: Curves.easeInOut));

    _shimmerCtrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 700));
    _shimmerAnim = ColorTween(begin: _gold, end: _goldLight).animate(
        CurvedAnimation(parent: _shimmerCtrl, curve: Curves.easeInOut));

    _usernameFocusNode.addListener(_onFocusChange);
    _passwordFocusNode.addListener(_onFocusChange);

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _usernameFocusNode.requestFocus();
    });
    _pingServer();
  }

  void _onFocusChange() {
    if (_usernameFocusNode.hasFocus || _passwordFocusNode.hasFocus) {
      _shimmerCtrl.repeat(reverse: true);
    } else {
      _shimmerCtrl.stop();
      _shimmerCtrl.value = 0;
    }
    // نُعيد البناء فقط لتحديث لون الأيقونة/الحدود عند تغيّر التركيز
    // الأخطاء تُمسح عند الكتابة (onChanged) لا عند التركيز
    setState(() {});
  }

  Future<void> _pingServer() async {
    try {
      final base =
          ApiService.resolvedBaseUrl.replaceFirst(RegExp(r'/api$'), '');
      final res = await http
          .get(Uri.parse('$base/health'))
          .timeout(const Duration(seconds: 5));
      if (mounted) {
        setState(() => _serverStatus =
            res.statusCode < 500 ? _ServerStatus.online : _ServerStatus.offline);
      }
    } catch (_) {
      if (mounted) setState(() => _serverStatus = _ServerStatus.offline);
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _usernameFocusNode
      ..removeListener(_onFocusChange)
      ..dispose();
    _passwordFocusNode
      ..removeListener(_onFocusChange)
      ..dispose();
    _kbFocusNode.dispose();
    _fadeCtrl.dispose();
    _shakeCtrl.dispose();
    _shimmerCtrl.dispose();
    super.dispose();
  }

  // ── Validation يدوي — بدون Form لتجنب HTML form-submit على Flutter Web ──
  bool _validate() {
    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty) {
      setState(() { _usernameError = 'اسم المستخدم مطلوب'; _loginError = null; });
      _usernameFocusNode.requestFocus();
      return false;
    }
    if (password.isEmpty) {
      setState(() { _loginError = 'كلمة المرور مطلوبة'; _usernameError = null; });
      _passwordFocusNode.requestFocus();
      return false;
    }
    return true;
  }

  Future<void> _attemptLogin() async {
    setState(() { _loginError = null; _usernameError = null; });
    if (!_validate()) return;

    final auth = context.read<AuthProvider>();
    final success = await auth.login(
      _usernameController.text.trim(),
      _passwordController.text.trim(),
    );
    if (!mounted) return;

    if (success) {
      TextInput.finishAutofillContext(shouldSave: true);
    } else {
      // اضبط الخطأ أولاً، ثم انقل التركيز، ثم هز، ثم أخبر المتصفح
      // (finishAutofillContext بعد الـ shake حتى لا يتدخل في setState)
      setState(() => _loginError = 'اسم المستخدم أو كلمة المرور غير صحيحة');
      _passwordController.clear();
      _passwordFocusNode.requestFocus();
      await _shakeCtrl.forward(from: 0);
      TextInput.finishAutofillContext(shouldSave: false);
    }
  }

  void _clearFields() {
    _usernameController.clear();
    _passwordController.clear();
    setState(() { _loginError = null; _usernameError = null; });
    _usernameFocusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isLoading = context.watch<AuthProvider>().isLoading;
    final settings  = context.watch<SettingsProvider>();

    return KeyboardListener(
      focusNode: _kbFocusNode,
      onKeyEvent: (event) {
        if (event is KeyDownEvent &&
            event.logicalKey == LogicalKeyboardKey.escape) {
          _clearFields();
        }
      },
      child: Scaffold(
        body: FadeTransition(
          opacity: _fadeAnim,
          child: Stack(
            children: [
              // ── خلفية ─────────────────────────────────────────────
              Container(
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    colors: [_bgStart, _bgEnd],
                    begin: Alignment.topRight,
                    end: Alignment.bottomLeft,
                  ),
                ),
              ),

              // ── ماسة هندسية — زخرفة وحيدة ────────────────────────
              Positioned(
                top: -80, right: -80,
                child: Transform.rotate(
                  angle: 0.7854,
                  child: Container(
                    width: 300, height: 300,
                    decoration: BoxDecoration(
                      border: Border.all(
                          color: Colors.white.withOpacity(0.10), width: 1.5),
                    ),
                  ),
                ),
              ),
              Positioned(
                top: -20, right: -20,
                child: Transform.rotate(
                  angle: 0.7854,
                  child: Container(
                    width: 170, height: 170,
                    decoration: BoxDecoration(
                      border: Border.all(
                          color: Colors.white.withOpacity(0.06), width: 1),
                    ),
                  ),
                ),
              ),

              // ── المحتوى ───────────────────────────────────────────
              Column(
                children: [
                  Expanded(
                    child: Center(
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 24, vertical: 32),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            _buildCard(theme, isLoading),
                            const SizedBox(height: 20),
                            _buildFooter(),
                          ],
                        ),
                      ),
                    ),
                  ),
                  if (settings.showGoldPriceTickerOnLogin)
                    GoldPriceTickerBar(
                      isArabic: true,
                      currencySymbol: settings.currencySymbolText,
                      isNewSar: settings.currencyIsNewSar,
                      refreshInterval: settings.goldPriceTickerRefreshInterval,
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCard(ThemeData theme, bool isLoading) {
    return AnimatedBuilder(
      animation: Listenable.merge([_shakeCtrl, _shimmerCtrl]),
      builder: (context, _) {
        return Card(
          elevation: 6,
          shadowColor: Colors.black.withOpacity(0.22),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: BorderSide(color: _gold.withOpacity(0.18), width: 1),
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 36, vertical: 36),
              // AutofillGroup بدلاً من Form — لا ينشئ HTML <form> فلا reload
              child: AutofillGroup(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // ── شعار ────────────────────────────────────────
                    const Center(
                        child: AppLogo.gold(width: 120, height: 120)),
                    const SizedBox(height: 12),

                    Text(
                      'Khaled Jewellery',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: _gold,
                        letterSpacing: 0.4,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Gold Management ERP System',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: _textSecondary,
                        letterSpacing: 0.3,
                        fontSize: 13,
                      ),
                      textAlign: TextAlign.center,
                    ),

                    // ── فاصل ◇ ──────────────────────────────────────
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 22),
                      child: Row(
                        children: [
                          Expanded(child: Divider(
                              color: Colors.grey.shade200, thickness: 1)),
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 12),
                            child: Icon(Icons.diamond_outlined,
                                size: 14, color: Colors.grey.shade400),
                          ),
                          Expanded(child: Divider(
                              color: Colors.grey.shade200, thickness: 1)),
                        ],
                      ),
                    ),

                    // ── اسم المستخدم ─────────────────────────────────
                    _fieldLabel('اسم المستخدم'),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _usernameController,
                      focusNode: _usernameFocusNode,
                      textInputAction: TextInputAction.next,
                      keyboardType: TextInputType.text,
                      autofillHints: const [AutofillHints.username],
                      onSubmitted: (_) => _passwordFocusNode.requestFocus(),
                      onChanged: (_) {
                        if (_usernameError != null) {
                          setState(() => _usernameError = null);
                        }
                      },
                      style: const TextStyle(color: _textPrimary, fontSize: 15),
                      decoration: _fieldDecoration(
                        icon: Icons.person_outline,
                        hasFocus: _usernameFocusNode.hasFocus,
                        hasError: _usernameError != null,
                      ),
                    ),
                    if (_usernameError != null)
                      _inlineError(_usernameError!),
                    const SizedBox(height: 18),

                    // ── كلمة المرور ──────────────────────────────────
                    _fieldLabel('كلمة المرور'),
                    const SizedBox(height: 6),
                    Transform.translate(
                      offset: Offset(_shakeAnim.value, 0),
                      child: TextField(
                        controller: _passwordController,
                        focusNode: _passwordFocusNode,
                        obscureText: _obscurePassword,
                        textInputAction: TextInputAction.go,
                        onSubmitted: (_) => _attemptLogin(),
                        onChanged: (_) {
                          if (_loginError != null) {
                            setState(() => _loginError = null);
                          }
                        },
                        keyboardType: TextInputType.visiblePassword,
                        autofillHints: const [AutofillHints.password],
                        style: const TextStyle(
                            color: _textPrimary, fontSize: 15),
                        decoration: _fieldDecoration(
                          icon: Icons.lock_outline,
                          hasFocus: _passwordFocusNode.hasFocus,
                          hasError: _loginError != null,
                          suffix: IconButton(
                            icon: Icon(
                              _obscurePassword
                                  ? Icons.visibility_off_outlined
                                  : Icons.visibility_outlined,
                              size: 22,
                              color: _textMuted,
                            ),
                            onPressed: () => setState(
                                () => _obscurePassword = !_obscurePassword),
                          ),
                        ),
                      ),
                    ),
                    if (_loginError != null)
                      _inlineError(_loginError!),

                    // ── نسيت كلمة المرور ─────────────────────────────
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton(
                        style: TextButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          minimumSize: Size.zero,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                        onPressed: isLoading
                            ? null
                            : () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) =>
                                        const ForgotPasswordScreen())),
                        child: const Text(
                          'نسيت كلمة المرور؟',
                          style: TextStyle(fontSize: 12, color: _gold),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // ── دخول النظام ──────────────────────────────────
                    SizedBox(
                      height: 52,
                      child: ElevatedButton.icon(
                        onPressed: isLoading ? null : _attemptLogin,
                        icon: isLoading
                            ? const SizedBox(
                                width: 18, height: 18,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.login_rounded,
                                size: 22, color: Colors.white),
                        label: Text(
                          isLoading ? 'جارٍ الدخول...' : 'دخول النظام',
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                            letterSpacing: 0.5,
                          ),
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _gold,
                          foregroundColor: Colors.white,
                          disabledBackgroundColor: Colors.grey.shade300,
                          elevation: 2,
                          shadowColor: _gold.withOpacity(0.4),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10)),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildFooter() {
    final (dotColor, label) = switch (_serverStatus) {
      _ServerStatus.checking => (Colors.amber.shade300, 'جارٍ الفحص...'),
      _ServerStatus.online   => (const Color(0xFF4CAF50), 'متصل'),
      _ServerStatus.offline  => (Colors.red.shade400, 'غير متصل'),
    };

    return Column(
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8, height: 8,
              decoration: BoxDecoration(
                color: dotColor,
                shape: BoxShape.circle,
                boxShadow: _serverStatus == _ServerStatus.online
                    ? [BoxShadow(
                        color: dotColor.withOpacity(0.6), blurRadius: 6)]
                    : null,
              ),
            ),
            const SizedBox(width: 6),
            Text('الخادم: $label',
                style: TextStyle(
                    fontSize: 12, color: Colors.white.withOpacity(0.85))),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          'Version 1.0.0  ·  © 2026 Khaled Jewellery ERP',
          style: TextStyle(
              fontSize: 11, color: Colors.white.withOpacity(0.55)),
        ),
      ],
    );
  }

  Widget _fieldLabel(String text) => Text(
        text,
        style: const TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: _textSecondary,
        ),
      );

  Widget _inlineError(String message) => Padding(
        padding: const EdgeInsets.only(top: 5, right: 4),
        child: Text(
          message,
          style: TextStyle(fontSize: 12, color: Colors.red.shade600),
          textAlign: TextAlign.right,
        ),
      );

  InputDecoration _fieldDecoration({
    required IconData icon,
    required bool hasFocus,
    bool hasError = false,
    Widget? suffix,
  }) {
    const radius = BorderRadius.all(Radius.circular(10));
    final shimmerColor = _shimmerAnim.value ?? _gold;
    final activeBorderColor = hasError ? Colors.red.shade500 : shimmerColor;

    return InputDecoration(
      prefixIcon: Icon(icon,
          size: 22,
          color: hasFocus
              ? (hasError ? Colors.red.shade400 : shimmerColor)
              : _textMuted),
      suffixIcon: suffix,
      border: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.grey.shade300)),
      enabledBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(
              color: hasError ? Colors.red.shade400 : Colors.grey.shade300)),
      focusedBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: activeBorderColor, width: 1.5)),
      errorBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.red.shade400)),
      focusedErrorBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.red.shade400, width: 1.5)),
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      filled: true,
      fillColor: Colors.grey.shade50,
    );
  }
}
