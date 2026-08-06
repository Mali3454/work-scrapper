import pytest

from scrapper.config import MissingEnvVar, load_config

CONFIG_YAML = """
smtp:
  host: smtp.gmail.com
  port: 587
  user: ${SMTP_USER}
  password: ${SMTP_PASSWORD}
  to: olosolo16@gmail.com

profiles:
  - name: frontend-szczecin
    keywords: [frontend, react]
    exclude: [senior]
    locations: [szczecin]
    include_remote: true
    max_age_days: 14
"""


def test_loads_profiles_and_smtp(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML, encoding="utf-8")

    config = load_config(path, env={"SMTP_USER": "me@gmail.com", "SMTP_PASSWORD": "sekret"})

    assert config.smtp.user == "me@gmail.com"
    assert config.smtp.password == "sekret"
    assert len(config.profiles) == 1
    assert config.profiles[0].keywords == ["frontend", "react"]


def test_missing_env_var_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML, encoding="utf-8")

    with pytest.raises(MissingEnvVar, match="SMTP_PASSWORD"):
        load_config(path, env={"SMTP_USER": "me@gmail.com"})


def test_literal_values_pass_through(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML.replace("${SMTP_USER}", "stale@example.com"), encoding="utf-8")

    config = load_config(path, env={"SMTP_PASSWORD": "sekret"})

    assert config.smtp.user == "stale@example.com"
