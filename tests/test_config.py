from app.config import load_settings


def test_akshare_defaults_enabled(tmp_path) -> None:
    settings = load_settings(str(tmp_path / "missing.toml"))
    assert settings.akshare_enabled is True
    assert settings.akshare_timeout == 30


def test_akshare_can_be_disabled_in_config(tmp_path) -> None:
    config = tmp_path / "sources.toml"
    config.write_text('[akshare]\nenabled = false\ntimeout = 12\n', encoding="utf-8")
    settings = load_settings(str(config))
    assert settings.akshare_enabled is False
    assert settings.akshare_timeout == 12
