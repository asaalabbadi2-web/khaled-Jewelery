import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';

class InitialSetupScreen extends StatefulWidget {
  const InitialSetupScreen({super.key});

  @override
  State<InitialSetupScreen> createState() => _InitialSetupScreenState();
}

class _InitialSetupScreenState extends State<InitialSetupScreen> {
  final _formKey = GlobalKey<FormState>();

  final _companyNameController = TextEditingController(text: 'مجوهرات خالد');
  final _fullNameController = TextEditingController(text: 'مدير النظام');
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _obscurePassword = true;

  @override
  void dispose() {
    _companyNameController.dispose();
    _fullNameController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final auth = context.read<AuthProvider>();
    final ok = await auth.completeInitialSetup(
      companyName: _companyNameController.text.trim(),
      adminFullName: _fullNameController.text.trim(),
      adminPassword: _passwordController.text,
    );

    if (!mounted) {
      return;
    }

    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('فشل إعداد النظام. تأكد من البيانات وحاول مرة أخرى.'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final isLoading = context.watch<AuthProvider>().isLoading;

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [colorScheme.primary, colorScheme.primaryContainer],
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
          ),
        ),
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Card(
              elevation: 8,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(24),
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 460),
                child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.diamond,
                          size: 72,
                          color: AppColors.primaryGold,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'تهيئة النظام لأول مرة',
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.bold,
                            color: colorScheme.primary,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'قم بإعداد بيانات المنشأة وإنشاء مسؤول النظام',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: Colors.grey.shade600,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 28),
                        TextFormField(
                          controller: _companyNameController,
                          textInputAction: TextInputAction.next,
                          decoration: InputDecoration(
                            labelText: 'اسم المنشأة',
                            prefixIcon: const Icon(Icons.storefront_outlined),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          validator: (value) {
                            if (value == null || value.trim().isEmpty) {
                              return 'اسم المنشأة مطلوب';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _fullNameController,
                          textInputAction: TextInputAction.next,
                          decoration: InputDecoration(
                            labelText: 'اسم مسؤول النظام',
                            prefixIcon: const Icon(Icons.person_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          validator: (value) {
                            if (value == null || value.trim().isEmpty) {
                              return 'اسم مسؤول النظام مطلوب';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _passwordController,
                          obscureText: _obscurePassword,
                          textInputAction: TextInputAction.next,
                          keyboardType: TextInputType.visiblePassword,
                          decoration: InputDecoration(
                            labelText: 'كلمة المرور (admin)',
                            prefixIcon: const Icon(Icons.lock_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                            suffixIcon: IconButton(
                              icon: Icon(
                                _obscurePassword
                                    ? Icons.visibility_off
                                    : Icons.visibility,
                              ),
                              onPressed: () {
                                setState(
                                  () => _obscurePassword = !_obscurePassword,
                                );
                              },
                            ),
                          ),
                          validator: (value) {
                            if (value == null || value.isEmpty) {
                              return 'كلمة المرور مطلوبة';
                            }
                            if (value.length < 6) {
                              return 'كلمة المرور يجب أن تكون 6 أحرف على الأقل';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _confirmPasswordController,
                          obscureText: _obscurePassword,
                          textInputAction: TextInputAction.done,
                          onFieldSubmitted: (_) => _submit(),
                          keyboardType: TextInputType.visiblePassword,
                          decoration: InputDecoration(
                            labelText: 'تأكيد كلمة المرور',
                            prefixIcon: const Icon(Icons.lock_outline),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          validator: (value) {
                            if (value == null || value.isEmpty) {
                              return 'تأكيد كلمة المرور مطلوب';
                            }
                            if (value != _passwordController.text) {
                              return 'كلمتا المرور غير متطابقتين';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 24),
                        SizedBox(
                          width: double.infinity,
                          height: 48,
                          child: FilledButton(
                            onPressed: isLoading ? null : _submit,
                            child: isLoading
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : const Text('إكمال التهيئة والدخول'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
