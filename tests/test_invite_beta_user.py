from __future__ import annotations
import scripts.invite_beta_user as invite

def test_invite_dry_run_new_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv('SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-key')
    monkeypatch.setattr(invite, 'find_user_by_email', lambda *_a, **_k: None)
    rc = invite.main(['--email', 'new@example.com'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'DRY-RUN' in out
    assert "invite 'new@example.com'" in out

def test_invite_send_new_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv('SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-key')
    calls: list[tuple] = []

    def fake_invite(base, key, email, *, redirect_to):
        calls.append((base, key, email, redirect_to))
        return {'id': '22222222-2222-4222-8222-222222222222', 'email': email}
    monkeypatch.setattr(invite, 'find_user_by_email', lambda *_a, **_k: None)
    monkeypatch.setattr(invite, 'invite_user_by_email', fake_invite)
    monkeypatch.setattr(invite, 'set_user_plan', lambda *a, **k: calls.append(('plan', a)))
    rc = invite.main(['--email', 'new@example.com', '--send', '--grant-pro'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'Invited new@example.com' in out
    assert any((len(c) == 4 for c in calls))
    assert calls[0][3] == invite.DEFAULT_REDIRECT

def test_invite_listed_pro_invitee_auto_grants(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv('SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-key')
    pro_file = tmp_path / 'pro_invitees.txt'
    pro_file.write_text('paid@example.com\n', encoding='utf-8')
    monkeypatch.setattr('shared.comp_pro.COMP_PRO_EMAILS_PATH', pro_file)
    writes: list[tuple] = []

    def fake_invite(base, key, email, *, redirect_to):
        return {'id': '33333333-3333-4333-8333-333333333333', 'email': email}
    monkeypatch.setattr(invite, 'find_user_by_email', lambda *_a, **_k: None)
    monkeypatch.setattr(invite, 'invite_user_by_email', fake_invite)
    monkeypatch.setattr(invite, 'set_user_plan', lambda *args: writes.append(args))
    rc = invite.main(['--email', 'paid@example.com', '--send'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'pro_invitees.txt' in out
    assert len(writes) == 1

def test_invite_non_listed_stays_free(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv('SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-key')
    pro_file = tmp_path / 'pro_invitees.txt'
    pro_file.write_text('paid@example.com\n', encoding='utf-8')
    monkeypatch.setattr('shared.comp_pro.COMP_PRO_EMAILS_PATH', pro_file)
    writes: list[tuple] = []
    monkeypatch.setattr(invite, 'find_user_by_email', lambda *_a, **_k: None)
    monkeypatch.setattr(invite, 'invite_user_by_email', lambda *a, **k: {'id': '33333333-3333-4333-8333-333333333333', 'email': a[2]})
    monkeypatch.setattr(invite, 'set_user_plan', lambda *args: writes.append(args))
    rc = invite.main(['--email', 'free@example.com', '--send'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'grant-pro' not in out
    assert writes == []

def test_invite_existing_user_grant_pro(monkeypatch, capsys) -> None:
    monkeypatch.setenv('SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-key')
    existing = {'id': '11111111-1111-4111-8111-111111111111', 'email': 'beta@example.com', 'app_metadata': {'plan': 'free'}}
    writes: list[tuple] = []
    monkeypatch.setattr(invite, 'find_user_by_email', lambda *_a, **_k: existing)
    monkeypatch.setattr(invite, 'set_user_plan', lambda *args: writes.append(args))
    rc = invite.main(['--email', 'beta@example.com', '--send', '--grant-pro'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'already registered' in out
    assert len(writes) == 1
    assert writes[0][2] == '11111111-1111-4111-8111-111111111111'