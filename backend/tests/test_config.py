import os

import pytest

from app.config import _load_dotenv


@pytest.fixture()
def clean_env():
    names = ["SV_TEST_A", "SV_TEST_B", "SV_TEST_C", "SV_TEST_KEEP"]
    for n in names:
        os.environ.pop(n, None)
    yield names
    for n in names:
        os.environ.pop(n, None)


def test_reads_plain_utf8_with_comments_quotes_and_spaces(tmp_path, clean_env):
    f = tmp_path / ".env"
    f.write_text('# a comment\n\nSV_TEST_A = abc123\nSV_TEST_B="quoted value"\nnot a setting\n', encoding="utf-8")
    _load_dotenv(f)
    assert os.environ["SV_TEST_A"] == "abc123"
    assert os.environ["SV_TEST_B"] == "quoted value"


def test_reads_windows_utf8_bom_and_crlf(tmp_path, clean_env):
    f = tmp_path / ".env"
    f.write_bytes(b"\xef\xbb\xbfSV_TEST_A=from-notepad\r\nSV_TEST_B=second\r\n")
    _load_dotenv(f)
    assert os.environ["SV_TEST_A"] == "from-notepad"
    assert os.environ["SV_TEST_B"] == "second"


def test_reads_utf16_written_by_powershell_redirect(tmp_path, clean_env):
    f = tmp_path / ".env"
    f.write_bytes("SV_TEST_A=from-powershell\r\nSV_TEST_B=region\r\n".encode("utf-16"))
    _load_dotenv(f)
    assert os.environ["SV_TEST_A"] == "from-powershell"
    assert os.environ["SV_TEST_B"] == "region"


def test_an_empty_line_never_hides_the_same_setting_with_a_value(tmp_path, clean_env):
    # The empty line comes from copying .env.example; the real value was added below it.
    f = tmp_path / ".env"
    f.write_text("SV_TEST_A=\nSV_TEST_B=first\nSV_TEST_A=the-real-key\nSV_TEST_B=\n", encoding="utf-8")
    _load_dotenv(f)
    assert os.environ["SV_TEST_A"] == "the-real-key"
    assert os.environ["SV_TEST_B"] == "first"


def test_the_last_value_wins_when_a_setting_is_repeated(tmp_path, clean_env):
    f = tmp_path / ".env"
    f.write_text("SV_TEST_A=old\nSV_TEST_A=new\n", encoding="utf-8")
    _load_dotenv(f)
    assert os.environ["SV_TEST_A"] == "new"


def test_real_environment_variables_win_and_a_missing_file_is_fine(tmp_path, clean_env):
    os.environ["SV_TEST_KEEP"] = "from-environment"
    f = tmp_path / ".env"
    f.write_text("SV_TEST_KEEP=from-file\n", encoding="utf-8")
    _load_dotenv(f)
    assert os.environ["SV_TEST_KEEP"] == "from-environment"
    _load_dotenv(tmp_path / "does-not-exist")
