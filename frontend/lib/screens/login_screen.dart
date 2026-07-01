import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/auth_provider.dart';
import '../providers/settings_provider.dart';
import '../widgets/app_logo.dart';
import '../widgets/gold_price_ticker_bar.dart';
import 'forgot_password_screen.dart';
import 'username_recovery_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

enum _ServerStatus { checking, online, offline }

class _LoginScreenState extends State<LoginScreen>
    with SingleTickerProviderStateMixin {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _usernameFocusNode = FocusNode();
  final _passwordFocusNode = FocusNode();
  bool _obscurePassword = true;
  _ServerStatus _serverStatus = _ServerStatus.checking;

  late AnimationController _fadeCtrl;
  late Animation<double> _fadeAnim;

  static const _gold = Color(0xFFB8860B);
  static const _bgStart = Color(0xFFC9962A);
  static const _bgEnd = Color(0xFF8B6508);

  @override
  void initState() {
    super.initState();
    _fadeCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 180),
    );
    _fadeAnim = CurvedAnimation(parent: _fadeCtrl, curve: Curves.easeIn);
    _fadeCtrl.forward();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _usernameFocusNode.requestFocus();
    });
    _pingServer();
  }

  Future<void> _pingServer() async {
    try {
      // Strip /api suffix to reach the root /health endpoint.
      final base = ApiService.resolvedBaseUrl.replaceFirst(RegExp(r'/api$'), '');
      final response = await http
          .get(Uri.parse('$base/health'))
          .timeout(const Duration(seconds: 5));
      if (mounted) {
        setState(() => _serverStatus = response.statusCode < 500
            ? _ServerStatus.online
            : _ServerStatus.offline);
      }
    } catch (_) {
      if (mounted) setState(() => _serverStatus = _ServerStatus.offline);
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _usernameFocusNode.dispose();
    _passwordFocusNode.dispose();
    _fadeCtrl.dispose();
    super.dispose();
  }

  Future<void> _attemptLogin() async {
    if (!_formKey.currentState!.validate()) return;
    final auth = context.read<AuthProvider>();
    final success = await auth.login(
      _usernameController.text.trim(),
      _passwordController.text.trim(),
    );
    if (!mounted) return;
    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('فشل تسجيل الدخول. تأكد من البيانات.'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isLoading = context.watch<AuthProvider>().isLoading;
    final settings = context.watch<SettingsProvider>();

    return Scaffold(
      body: FadeTransition(
        opacity: _fadeAnim,
        child: Stack(
          children: [
            // ── خلفية متدرجة ذهبية ────────────────────────────────────
            Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [_bgStart, _bgEnd],
                  begin: Alignment.topRight,
                  end: Alignment.bottomLeft,
                ),
              ),
            ),

            // ── عنصر زخرفي واحد: ماسة هندسية في الركن العلوي الأيمن ──
            Positioned(
              top: -80,
              right: -80,
              child: Transform.rotate(
                angle: 0.7854, // 45°
                child: Container(
                  width: 300,
                  height: 300,
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: Colors.white.withOpacity(0.10),
                      width: 1.5,
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              top: -20,
              right: -20,
              child: Transform.rotate(
                angle: 0.7854,
                child: Container(
                  width: 170,
                  height: 170,
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: Colors.white.withOpacity(0.06),
                      width: 1,
                    ),
                  ),
                ),
              ),
            ),

            // ── المحتوى الرئيسي ─────────────────────────────────────
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
    );
  }

  Widget _buildCard(ThemeData theme, bool isLoading) {
    return Card(
      elevation: 6,
      shadowColor: Colors.black.withOpacity(0.25),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 540),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 40),
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ── شعار أكبر ──────────────────────────────────────
                const Center(child: AppLogo.gold(width: 120, height: 120)),
                const SizedBox(height: 14),

                // ── اسم المحل ───────────────────────────────────────
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
                    color: Colors.grey.shade500,
                    letterSpacing: 0.3,
                  ),
                  textAlign: TextAlign.center,
                ),

                // ── فاصل ────────────────────────────────────────────
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 28),
                  child: Row(
                    children: [
                      Expanded(
                          child: Divider(
                              color: Colors.grey.shade200, thickness: 1)),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Icon(Icons.diamond_outlined,
                            size: 14, color: Colors.grey.shade300),
                      ),
                      Expanded(
                          child: Divider(
                              color: Colors.grey.shade200, thickness: 1)),
                    ],
                  ),
                ),

                // ── حقل اسم المستخدم ─────────────────────────────
                _fieldLabel('اسم المستخدم', theme),
                const SizedBox(height: 6),
                TextFormField(
                  controller: _usernameController,
                  focusNode: _usernameFocusNode,
                  textInputAction: TextInputAction.next,
                  keyboardType: TextInputType.text,
                  autofillHints: const [AutofillHints.username],
                  onFieldSubmitted: (_) => _passwordFocusNode.requestFocus(),
                  decoration: _fieldDecoration(
                    hint: 'أدخل اسم المستخدم',
                    icon: Icons.person_outline,
                  ),
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? 'اسم المستخدم مطلوب' : null,
                ),
                const SizedBox(height: 20),

                // ── حقل كلمة المرور ───────────────────────────────
                _fieldLabel('كلمة المرور', theme),
                const SizedBox(height: 6),
                TextFormField(
                  controller: _passwordController,
                  focusNode: _passwordFocusNode,
                  obscureText: _obscurePassword,
                  textInputAction: TextInputAction.done,
                  onFieldSubmitted: (_) => _attemptLogin(),
                  keyboardType: TextInputType.visiblePassword,
                  autofillHints: const [AutofillHints.password],
                  decoration: _fieldDecoration(
                    hint: 'أدخل كلمة المرور',
                    icon: Icons.lock_outline,
                    suffix: IconButton(
                      icon: Icon(
                        _obscurePassword
                            ? Icons.visibility_off_outlined
                            : Icons.visibility_outlined,
                        size: 20,
                        color: Colors.grey.shade500,
                      ),
                      onPressed: () =>
                          setState(() => _obscurePassword = !_obscurePassword),
                    ),
                  ),
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? 'كلمة المرور مطلوبة' : null,
                ),

                // ── نسيت كلمة المرور — محاذاة يسار (RTL: يمين) ────
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: TextButton(
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    onPressed: isLoading
                        ? null
                        : () => Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => const ForgotPasswordScreen())),
                    child: const Text(
                      'نسيت كلمة المرور؟',
                      style: TextStyle(fontSize: 12, color: _gold),
                    ),
                  ),
                ),
                const SizedBox(height: 20),

                // ── زر الدخول ─────────────────────────────────────
                SizedBox(
                  height: 52,
                  child: ElevatedButton.icon(
                    onPressed: isLoading ? null : _attemptLogin,
                    icon: isLoading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.login_rounded,
                            size: 20, color: Colors.white),
                    label: Text(
                      isLoading ? 'جارٍ الدخول...' : 'تسجيل الدخول',
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
                const SizedBox(height: 12),

                // ── نسيت اسم المستخدم ─────────────────────────────
                Center(
                  child: TextButton(
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    onPressed: isLoading
                        ? null
                        : () => Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => const UsernameRecoveryScreen())),
                    child: Text(
                      'نسيت اسم المستخدم؟',
                      style: TextStyle(
                          fontSize: 12, color: Colors.grey.shade500),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildFooter() {
    final (dotColor, label) = switch (_serverStatus) {
      _ServerStatus.checking => (Colors.amber.shade300, 'جارٍ الفحص...'),
      _ServerStatus.online => (const Color(0xFF4CAF50), 'متصل'),
      _ServerStatus.offline => (Colors.red.shade400, 'غير متصل'),
    };

    return Column(
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: dotColor,
                shape: BoxShape.circle,
                boxShadow: _serverStatus == _ServerStatus.online
                    ? [BoxShadow(color: dotColor.withOpacity(0.6), blurRadius: 6)]
                    : null,
              ),
            ),
            const SizedBox(width: 6),
            Text(
              'الخادم: $label',
              style: TextStyle(
                  fontSize: 12, color: Colors.white.withOpacity(0.80)),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          'Version 1.0.0  ·  © 2026 Khaled Jewellery ERP',
          style: TextStyle(
              fontSize: 11, color: Colors.white.withOpacity(0.50)),
        ),
      ],
    );
  }

  Widget _fieldLabel(String text, ThemeData theme) {
    return Text(
      text,
      style: theme.textTheme.bodySmall?.copyWith(
        fontWeight: FontWeight.w600,
        color: Colors.grey.shade700,
      ),
    );
  }

  InputDecoration _fieldDecoration({
    required String hint,
    required IconData icon,
    Widget? suffix,
  }) {
    const radius = BorderRadius.all(Radius.circular(10));
    return InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: Colors.grey.shade400, fontSize: 14),
      prefixIcon: Icon(icon, size: 20, color: Colors.grey.shade500),
      suffixIcon: suffix,
      border: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.grey.shade300)),
      enabledBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.grey.shade300)),
      focusedBorder: const OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: _gold, width: 1.5)),
      errorBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.red.shade400)),
      focusedErrorBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: Colors.red.shade400, width: 1.5)),
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      filled: true,
      fillColor: Colors.grey.shade50,
    );
  }
}
