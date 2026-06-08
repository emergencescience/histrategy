import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch
from histrategy.cli.record import generate_video

def test_generate_video_no_directory():
    with pytest.raises(FileNotFoundError):
        generate_video("nonexistent_session")

def test_generate_video_empty_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"HISTRATEGY_DATA_DIR": tmpdir}):
            session_id = "test_empty_session"
            session_dir = Path(tmpdir) / "sessions" / session_id
            session_dir.mkdir(parents=True)
            
            with pytest.raises(FileNotFoundError):
                generate_video(session_id)

def test_generate_video_with_frames():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"HISTRATEGY_DATA_DIR": tmpdir}):
            session_id = "test_valid_session"
            session_dir = Path(tmpdir) / "sessions" / session_id
            frames_dir = session_dir / "frames"
            frames_dir.mkdir(parents=True)
            
            # 1x1 transparent PNG bytes
            png_bytes = (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
                b'\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc` \x00\x00\x00\x02\x00\x01H'
                b'\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
            )
            
            for i in range(3):
                with open(frames_dir / f"frame_{i:04d}.png", "wb") as f:
                    f.write(png_bytes)
            
            with patch("subprocess.run") as mock_run:
                # Mock running ffmpeg by creating the output file
                def side_effect(*args, **kwargs):
                    out_path = session_dir / "out.mp4"
                    out_path.write_text("dummy video content")
                    return mock_run.return_value
                
                mock_run.side_effect = side_effect
                
                res = generate_video(session_id)
                assert Path(res).exists()
                assert "out.mp4" in res
                mock_run.assert_called_once()
