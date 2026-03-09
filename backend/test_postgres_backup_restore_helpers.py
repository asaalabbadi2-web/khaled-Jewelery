import subprocess
from unittest.mock import patch

from app import app
from routes import _create_postgres_backup_to_file, _restore_postgres_from_backup_file


_POSTGRES_PARTS = {
    'host': 'db.example.local',
    'port': 5432,
    'user': 'yasar',
    'password': 'secret',
    'database': 'yasargold',
}


def test_create_postgres_backup_uses_pg_dump_custom_format(tmp_path):
    backup_path = tmp_path / 'backup.dump'
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return None

    with app.app_context():
        with patch('routes._is_postgres_database', return_value=True), patch(
            'routes._pg_tools_available', return_value=(True, [])
        ), patch('routes._postgres_conn_parts', return_value=_POSTGRES_PARTS), patch(
            'routes.subprocess.run', side_effect=_fake_run
        ):
            _create_postgres_backup_to_file(str(backup_path))

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[0] == 'pg_dump'
    assert '-Fc' in cmd
    assert '-f' in cmd
    assert str(backup_path) in cmd
    assert cmd[-1] == 'yasargold'
    assert kwargs['env']['PGPASSWORD'] == 'secret'
    assert kwargs['check'] is True


def test_restore_postgres_terminates_connections_before_pg_restore(tmp_path):
    backup_path = tmp_path / 'backup.dump'
    backup_path.write_bytes(b'dummy')
    commands = []

    def _fake_run(cmd, **kwargs):
        commands.append(cmd)
        return None

    with app.app_context():
        with patch('routes._is_postgres_database', return_value=True), patch(
            'routes._pg_tools_available', return_value=(True, [])
        ), patch('routes._postgres_conn_parts', return_value=_POSTGRES_PARTS), patch(
            'routes.db.session.remove'
        ), patch('routes.db.engine.dispose'), patch(
            'routes.subprocess.run', side_effect=_fake_run
        ):
            _restore_postgres_from_backup_file(str(backup_path))

    assert len(commands) == 2
    terminate_cmd = commands[0]
    restore_cmd = commands[1]

    assert terminate_cmd[0] == 'psql'
    assert '-c' in terminate_cmd
    terminate_sql = terminate_cmd[terminate_cmd.index('-c') + 1]
    assert 'pg_terminate_backend' in terminate_sql
    assert "datname = 'yasargold'" in terminate_sql

    assert restore_cmd[0] == 'pg_restore'
    assert '--clean' in restore_cmd
    assert '--if-exists' in restore_cmd
    assert '-d' in restore_cmd
    assert str(backup_path) == restore_cmd[-1]


def test_restore_postgres_falls_back_to_psql_for_plain_sql_dump(tmp_path):
    backup_path = tmp_path / 'backup.dump'
    backup_path.write_text('select 1;', encoding='utf-8')
    commands = []

    def _fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[0] == 'pg_restore':
            raise subprocess.CalledProcessError(
                1,
                cmd,
                stderr='input file appears to be a text format dump. Please use psql.',
            )
        return None

    with app.app_context():
        with patch('routes._is_postgres_database', return_value=True), patch(
            'routes._pg_tools_available', return_value=(True, [])
        ), patch('routes._postgres_conn_parts', return_value=_POSTGRES_PARTS), patch(
            'routes.db.session.remove'
        ), patch('routes.db.engine.dispose'), patch(
            'routes.subprocess.run', side_effect=_fake_run
        ):
            _restore_postgres_from_backup_file(str(backup_path))

    assert len(commands) == 3
    assert commands[0][0] == 'psql'
    assert commands[1][0] == 'pg_restore'
    assert commands[2][0] == 'psql'
    assert '-f' in commands[2]
    assert str(backup_path) == commands[2][-1]
