import os
import sys
from unittest.mock import patch

from histrategy.cli.app import main
from histrategy.state.world_state import get_data_dir


def test_cli_room_arg_parsing():
    # Save original env and sys.argv
    orig_env = os.environ.get("HISTRATEGY_DATA_DIR")
    orig_argv = sys.argv

    try:
        # Mock sys.argv to run dev mode with a specific room
        sys.argv = ["histrategy", "--dev", "--room", "room_test_123"]

        # Patch the actual run_dev function to do nothing and exit
        with patch("histrategy.cli.dev_cli.run_dev") as mock_run_dev:
            # We want HISTRATEGY_DATA_DIR to not be set at first
            if "HISTRATEGY_DATA_DIR" in os.environ:
                del os.environ["HISTRATEGY_DATA_DIR"]

            main()

            # Check that run_dev was called
            mock_run_dev.assert_called_once()

            # Check HISTRATEGY_DATA_DIR was set correctly
            data_dir = os.environ.get("HISTRATEGY_DATA_DIR")
            assert data_dir is not None
            assert data_dir.endswith(os.path.join("rooms", "room_test_123"))

            # Check get_data_dir() resolves correctly
            resolved_dir = get_data_dir()
            assert str(resolved_dir) == data_dir

    finally:
        # Restore original env and sys.argv
        sys.argv = orig_argv
        if orig_env is not None:
            os.environ["HISTRATEGY_DATA_DIR"] = orig_env
        elif "HISTRATEGY_DATA_DIR" in os.environ:
            del os.environ["HISTRATEGY_DATA_DIR"]
