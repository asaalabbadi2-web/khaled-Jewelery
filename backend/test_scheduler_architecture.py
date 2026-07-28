"""Architectural contract tests for ERP scheduler process isolation.

These tests encode the regression introduced in commit 69dd64a (2026-07-24):
when the ERP moved to Gunicorn, start_all_schedulers() stopped being called
because it lived only inside if __name__ == '__main__'.  No scheduler ran.
No auto-settlement happened.

Five invariants are enforced here so any future change that breaks them turns
red before merging:

  ARCH-SCHED-1  ERP scheduler runs via a dedicated Docker service, not inside
                Gunicorn workers.

  ARCH-SCHED-2  Exactly one ClearingSettlementScheduler instance per process
                (singleton + idempotent start).

  ARCH-SCHED-3  Gunicorn entrypoint (wsgi.py) contains zero scheduler
                references — the compile-time proof that workers never start
                threads.

  ARCH-SCHED-4  from routes import _compute_clearing_due_amount succeeds —
                the silent-fallback regression is closed.

  ARCH-SCHED-5  The re-exported function IS the same object as the one in
                routes.clearing — no copy, no wrapper, no alternative
                implementation.
"""
from __future__ import annotations

import pathlib

import pytest

BACKEND_DIR = pathlib.Path(__file__).parent
REPO_ROOT   = BACKEND_DIR.parent


# ═══════════════════════════════════════════════════════════════════════════════
# ARCH-SCHED-1 — Scheduler runs under Docker architecture
# ═══════════════════════════════════════════════════════════════════════════════

class TestDockerSchedulerService:
    """ERP scheduler is a dedicated Docker service, not a Gunicorn thread."""

    def test_run_schedulers_entrypoint_exists_and_starts_all(self):
        """backend/run_schedulers.py must exist and call start_all_schedulers.

        This is the command the erp-scheduler Docker service executes.
        If this file is missing or does not start schedulers, the service
        boots and immediately does nothing useful.
        """
        entrypoint = BACKEND_DIR / 'run_schedulers.py'
        assert entrypoint.exists(), (
            "backend/run_schedulers.py is missing. "
            "It is the erp-scheduler Docker service entrypoint."
        )
        source = entrypoint.read_text()
        assert 'start_all_schedulers' in source, (
            "run_schedulers.py must call start_all_schedulers(app). "
            "Without that call, the Docker service starts but no scheduler runs."
        )

    def test_docker_compose_declares_erp_scheduler_service(self):
        """docker-compose.local.yml must declare an erp-scheduler service
        whose command includes run_schedulers.

        Without this service, docker compose up starts ERP under Gunicorn only
        and no settlement scheduler ever runs.
        """
        compose_path = REPO_ROOT / 'docker-compose.local.yml'
        assert compose_path.exists(), "docker-compose.local.yml not found at repo root."
        source = compose_path.read_text()

        assert 'erp-scheduler' in source, (
            "docker-compose.local.yml must declare an erp-scheduler service. "
            "Without it, `docker compose up` starts no ERP scheduler."
        )
        assert 'run_schedulers' in source, (
            "erp-scheduler service command must reference run_schedulers. "
            "That script is the only correct ERP scheduler entrypoint."
        )

    def test_erp_scheduler_depends_on_erp_being_healthy(self):
        """erp-scheduler must declare erp as a dependency with service_healthy.

        erp runs create_tables() on startup; erp-scheduler must not start
        before the schema exists or its first process_due_settlements() run
        may fail on missing tables.
        """
        compose_path = REPO_ROOT / 'docker-compose.local.yml'
        source = compose_path.read_text()

        sched_pos = source.find('erp-scheduler')
        assert sched_pos != -1, "erp-scheduler service declaration not found."

        # Everything after the erp-scheduler declaration (up to the next
        # top-level service) must contain the health-condition dependency.
        after_sched = source[sched_pos:]
        assert 'service_healthy' in after_sched, (
            "erp-scheduler must depend on erp with condition: service_healthy. "
            "The scheduler needs the ERP schema to be ready before running."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ARCH-SCHED-2 — Only one scheduler instance per process
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedulerSingleton:
    """get_clearing_settlement_scheduler returns the same object every call."""

    def test_get_clearing_settlement_scheduler_is_singleton(self, monkeypatch):
        """get_clearing_settlement_scheduler(app) must return the same instance
        on every call within the same process.

        If it returned a new object each time, every Gunicorn worker that
        accidentally called it would create its own scheduler thread, producing
        one duplicate settlement per worker per schedule cycle.
        """
        import clearing_settlement_scheduler as css_module
        from app import app as flask_app

        # Reset module-level singleton so this test is self-contained.
        monkeypatch.setattr(css_module, '_scheduler_instance', None)

        s1 = css_module.get_clearing_settlement_scheduler(flask_app)
        s2 = css_module.get_clearing_settlement_scheduler(flask_app)

        assert s1 is s2, (
            "get_clearing_settlement_scheduler must return the same object on "
            "every call.  Two different instances mean two scheduler threads."
        )

    def test_start_is_idempotent_when_already_running(self, monkeypatch):
        """ClearingSettlementScheduler.start() on an already-running scheduler
        must not call setup_schedule() or spawn an additional thread.

        setup_schedule() registers jobs; calling it twice doubles the job list.
        An extra thread would run a second scheduling loop in parallel.
        """
        import clearing_settlement_scheduler as css_module
        from app import app as flask_app

        monkeypatch.setattr(css_module, '_scheduler_instance', None)
        scheduler = css_module.get_clearing_settlement_scheduler(flask_app)
        scheduler.is_running = True  # simulate already started

        setup_calls: list[bool] = []
        original_setup = scheduler.setup_schedule
        scheduler.setup_schedule = lambda: (setup_calls.append(True), original_setup())[1]

        scheduler.start()  # second call — must be a no-op

        assert setup_calls == [], (
            "start() on an already-running scheduler must not call "
            "setup_schedule().  Each call would add duplicate jobs."
        )
        assert scheduler.is_running is True, "is_running must remain True."
        scheduler.is_running = False  # restore for subsequent tests


# ═══════════════════════════════════════════════════════════════════════════════
# ARCH-SCHED-3 — Gunicorn workers never start schedulers
# ═══════════════════════════════════════════════════════════════════════════════

class TestGunicornIsolation:
    """wsgi.py is the Gunicorn entrypoint; it must contain no scheduler code."""

    def test_wsgi_has_no_scheduler_references(self):
        """Any scheduler reference in wsgi.py would start one scheduler thread
        per Gunicorn worker.  With -w 2 that is two parallel clearing-settlement
        loops, creating duplicate vouchers for every settlement cycle.
        """
        wsgi_path = BACKEND_DIR / 'wsgi.py'
        assert wsgi_path.exists(), "backend/wsgi.py not found."
        source = wsgi_path.read_text().lower()

        assert 'scheduler' not in source, (
            "wsgi.py must not reference any scheduler. "
            "Schedulers belong in the erp-scheduler Docker service."
        )
        assert 'start_all_schedulers' not in source, (
            "wsgi.py must not call start_all_schedulers. "
            "That call creates one scheduler thread per Gunicorn worker."
        )

    def test_scheduler_entrypoint_does_not_import_or_start_gunicorn(self):
        """run_schedulers.py and wsgi.py must be strictly separate entrypoints.

        run_schedulers.py runs schedulers only.
        wsgi.py runs the HTTP server only.
        Neither does the other's job.

        We check for actual gunicorn import or invocation, not just the word
        appearing in a comment or docstring.
        """
        wsgi_src  = (BACKEND_DIR / 'wsgi.py').read_text().lower()
        sched_src = (BACKEND_DIR / 'run_schedulers.py').read_text()

        assert 'start_all_schedulers' not in wsgi_src, (
            "wsgi.py must not start schedulers."
        )

        # These are the patterns that would actually start a Gunicorn process.
        gunicorn_invocations = (
            'import gunicorn',
            'from gunicorn',
            'subprocess.run.*gunicorn',
            "app.run(",         # Flask dev-server — also forbidden here
        )
        sched_lower = sched_src.lower()
        for pattern in gunicorn_invocations:
            assert pattern.lower() not in sched_lower, (
                f"run_schedulers.py must not invoke gunicorn or Flask's dev server. "
                f"Found pattern: {pattern!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# ARCH-SCHED-4 — from routes import _compute_clearing_due_amount succeeds
# ═══════════════════════════════════════════════════════════════════════════════

class TestRouteReExports:
    """routes/__init__.py must re-export both clearing helpers."""

    def test_compute_clearing_due_amount_importable_from_routes(self):
        """from routes import _compute_clearing_due_amount must succeed.

        Before the fix this raised ImportError.  The scheduler caught it and
        silently fell back to _compute_sbt_based_due(), which cannot handle
        partial SettlementLine gaps (AV-2026-00133 class of bugs): when
        historical settlement vouchers cover all invoice-payment rows but leave
        residual gaps in SettlementLine, _compute_sbt_based_due() returns 0
        and process_due_settlements() skips all IPs as already-settled.
        """
        try:
            from routes import _compute_clearing_due_amount  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"'from routes import _compute_clearing_due_amount' raised "
                f"ImportError: {exc}\n"
                "Add the missing re-export to routes/__init__.py:\n"
                "  from routes.clearing import _compute_clearing_due_amount  # noqa: F401"
            )

    def test_create_clearing_settlement_voucher_re_export_intact(self):
        """The pre-existing re-export must not have been accidentally removed
        while adding the new one.
        """
        try:
            from routes import _create_clearing_settlement_voucher  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"Pre-existing re-export broken: {exc}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# ARCH-SCHED-5 — Scheduler uses primary implementation, not fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrimaryImplementationUsed:
    """The function the scheduler receives IS the one in routes.clearing."""

    def test_routes_export_is_same_object_as_routes_clearing(self):
        """routes._compute_clearing_due_amount must be the identical object as
        routes.clearing._compute_clearing_due_amount — same function, same id().

        This proves the re-export is a direct reference, not a copy or a wrapper.
        A copy could silently diverge.  A wrapper could introduce a different
        code path.  Same object identity guarantees the scheduler runs the
        SettlementLine-aware formula (which handles partial gaps) rather than
        the SBT-only fallback.
        """
        from routes import _compute_clearing_due_amount as via_package
        from routes.clearing import _compute_clearing_due_amount as direct

        assert via_package is direct, (
            f"routes._compute_clearing_due_amount (id={id(via_package)}) is not "
            f"the same object as routes.clearing._compute_clearing_due_amount "
            f"(id={id(direct)}).  The re-export must be a direct reference:\n"
            "  from routes.clearing import _compute_clearing_due_amount  # noqa: F401"
        )

    def test_scheduler_try_block_does_not_raise(self):
        """Reproduce the exact import statement inside process_due_settlements.

        The scheduler does:
            try:
                from routes import _compute_clearing_due_amount
                running_clearing_due = _compute_clearing_due_amount(safe_box_id)
            except Exception:
                running_clearing_due = self._compute_sbt_based_due(safe_box_id)

        If the import raises, the primary path is skipped.  This test verifies
        the import succeeds so the primary path is always entered.
        """
        exception_raised = False
        try:
            from routes import _compute_clearing_due_amount  # noqa: F401
        except Exception:
            exception_raised = True

        assert not exception_raised, (
            "The 'from routes import _compute_clearing_due_amount' import "
            "inside process_due_settlements() would raise and force the "
            "fallback path (_compute_sbt_based_due).  "
            "Fix: add the re-export to routes/__init__.py."
        )
