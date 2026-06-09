import os
import sys
from histrategy.cli.app import main


def test_cli_playthrough_simulation(tmp_path) -> None:
    """Test that the playthrough simulation CLI option runs and generates all logs/reports."""
    orig_env = os.environ.get("HISTRATEGY_DATA_DIR")
    orig_argv = sys.argv

    # Set isolated data directory using tmp_path to prevent interference with local dev files
    os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

    # Disable force v1 if any to allow engine detection if available
    orig_v1 = os.environ.get("HISTRATEGY_FORCE_V1")
    if "HISTRATEGY_FORCE_V1" in os.environ:
        del os.environ["HISTRATEGY_FORCE_V1"]

    try:
        sys.argv = ["histrategy", "--simulate-playthrough", "--loglevel", "DEBUG"]

        # Run CLI main method
        main()

        # Check logs directory exists
        log_dir = tmp_path / "logs"
        assert log_dir.exists()

        # Verify python standard logging file is created and contains debug lines
        log_file = log_dir / "histrategy.log"
        assert log_file.exists()
        log_content = log_file.read_text(encoding="utf-8")
        assert len(log_content) > 0

        # Verify simulation history file is created and populated with faction snapshots
        sim_history_file = log_dir / "simulation_history.jsonl"
        assert sim_history_file.exists()
        sim_lines = sim_history_file.read_text(encoding="utf-8").splitlines()
        # Should have at least 3 turns of simulation logging entries
        assert len(sim_lines) >= 3

        # Verify markdown playthrough report is compiled and saved
        report_file = tmp_path / "playthrough_records.md"
        assert report_file.exists()
        report_content = report_file.read_text(encoding="utf-8")
        assert "《三國志略》实战推演与数值仿真审查报告" in report_content
        assert "势力全局数值状态" in report_content
        assert "第 1 回合" in report_content
        assert "第 2 回合" in report_content
        assert "第 3 回合" in report_content

    finally:
        # Restore sys.argv and environment variables
        sys.argv = orig_argv
        if orig_env is not None:
            os.environ["HISTRATEGY_DATA_DIR"] = orig_env
        else:
            os.environ.pop("HISTRATEGY_DATA_DIR", None)

        if orig_v1 is not None:
            os.environ["HISTRATEGY_FORCE_V1"] = orig_v1
