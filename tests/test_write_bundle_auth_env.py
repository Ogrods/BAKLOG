import scripts.write_bundle_auth_env as bundle_env


def test_collect_auth_env_from_process(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_env, "ROOT", tmp_path)
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    values = bundle_env.collect_auth_env()
    assert values["BAKLOG_SUPABASE_URL"] == "https://demo.supabase.co"
    assert values["BAKLOG_SUPABASE_ANON_KEY"] == "anon-key"


def test_main_writes_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_env, "ROOT", tmp_path)
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    rc = bundle_env.main([str(tmp_path / "bundle")])
    assert rc == 0
    text = (tmp_path / "bundle" / ".env").read_text(encoding="utf-8")
    assert "BAKLOG_SUPABASE_URL=https://demo.supabase.co" in text
    assert "BAKLOG_SUPABASE_ANON_KEY=anon-key" in text
    assert "SERVICE_ROLE" not in text


def test_main_fails_without_required_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_env, "ROOT", tmp_path)
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    rc = bundle_env.main([str(tmp_path / "bundle")])
    assert rc == 1
    assert not (tmp_path / "bundle" / ".env").exists()
