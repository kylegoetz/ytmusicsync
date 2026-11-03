from unittest.mock import patch
import pytest

from src.cli import main, interactive_menu

def test_interactive_menu_exit():
    with patch("builtins.input", side_effect=["5"]):
        exit_code = interactive_menu()
        assert exit_code == 0

def test_main_no_args_triggers_interactive_menu():
    with patch("src.cli.interactive_menu", return_value=0) as mock_interactive:
        exit_code = main([])
        assert exit_code == 0
        mock_interactive.assert_called_once()
