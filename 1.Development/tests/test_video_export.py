import numpy as np

from bio_video_gui.video_export import write_video


def test_write_video_creates_readable_mp4(tmp_path):
    stack = np.zeros((5, 32, 32, 3), dtype=np.uint8)
    stack[:, :, :, 0] = 255  # solid blue frames (BGR)
    out_path = tmp_path / "out.mp4"

    result = write_video(stack, out_path, fps=5)

    assert result == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0
