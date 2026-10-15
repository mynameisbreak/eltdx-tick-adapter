import pytest

from app.config import load_settings, resolve_fuyao_api_key


def test_api_key_file_is_used_when_environment_is_unset(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "fuyao.key"
    secret.write_text(" file-secret \n", encoding="utf-8")
    settings_file = tmp_path / "data_sources.toml"
    settings_file.write_text(f'[fuyao]\napi_key_file = "{secret.as_posix()}"\n', encoding="utf-8")
    monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)

    settings = load_settings(str(settings_file))

    assert resolve_fuyao_api_key(settings) == "file-secret"


def test_nonempty_environment_key_overrides_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "fuyao.key"
    secret.write_text("file-secret", encoding="utf-8")
    settings_file = tmp_path / "data_sources.toml"
    settings_file.write_text(f'[fuyao]\napi_key_file = "{secret.as_posix()}"\n', encoding="utf-8")
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", " env-secret ")

    assert resolve_fuyao_api_key(load_settings(str(settings_file))) == "env-secret"


def test_blank_environment_falls_back_to_missing_file_as_unconfigured(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "data_sources.toml"
    settings_file.write_text('[fuyao]\napi_key_file = "missing.key"\n', encoding="utf-8")
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "  \n")

    assert resolve_fuyao_api_key(load_settings(str(settings_file))) == ""


def test_default_key_file_path_is_local_secret_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)
    settings = load_settings(str(tmp_path / "absent.toml"))

    assert settings.fuyao_api_key_file == ".secrets/fuyao_api_key"
    assert resolve_fuyao_api_key(settings) == ""
