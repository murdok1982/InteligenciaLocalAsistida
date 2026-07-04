"""Tests for utils.io module."""
import tempfile
import yaml
from pathlib import Path

from utils.io import load_config, ensure_dir, save_text, ts_stamp


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_yaml(self):
        """Test loading valid YAML config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"key": "value", "nested": {"a": 1}}, f)
            f.flush()
            config = load_config(f.name)
        assert config == {"key": "value", "nested": {"a": 1}}

    def test_load_empty_yaml(self):
        """Test loading empty YAML returns None."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            config = load_config(f.name)
        assert config is None

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file raises FileNotFoundError."""
        try:
            load_config("/nonexistent/path.yaml")
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass


class TestEnsureDir:
    """Tests for ensure_dir function."""

    def test_create_new_directory(self):
        """Test creating new directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "new" / "nested" / "dir"
            ensure_dir(str(new_dir))
            assert new_dir.exists()
            assert new_dir.is_dir()

    def test_existing_directory(self):
        """Test ensure_dir on existing directory does nothing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_dir(tmpdir)  # Should not raise


class TestSaveText:
    """Tests for save_text function."""

    def test_save_text_creates_file(self):
        """Test saving text creates file with content."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = f.name
        try:
            save_text(tmp_path, "Hello, World!")
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content == "Hello, World!"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_save_text_creates_parent_dirs(self):
        """Test saving text creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "nested" / "dir" / "file.txt"
            save_text(str(file_path), "content")
            assert file_path.exists()
            assert file_path.read_text() == "content"


class TestTsStamp:
    """Tests for ts_stamp function."""

    def test_format(self):
        """Test timestamp format matches YYYYMMDD_HHMMSS."""
        stamp = ts_stamp()
        assert len(stamp) == 15  # YYYYMMDD_HHMMSS
        assert stamp[8] == "_"
        assert stamp[:4].isdigit()  # Year
        assert stamp[4:6].isdigit()  # Month
        assert stamp[6:8].isdigit()  # Day
        assert stamp[9:11].isdigit()  # Hour
        assert stamp[11:13].isdigit()  # Minute
        assert stamp[13:15].isdigit()  # Second