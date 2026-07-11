"""Driver adapter tag sidecar (data.adapter_tags)."""
from __future__ import annotations

import pandas as pd

from data import adapter_tags


def _df():
    return pd.DataFrame({
        "club": ["Dr", "Dr", "7I"],
        "carry": [250.0, 255.0, 150.0],
        "session_id": ["s1", "s1", "s2"],
    })


def test_save_and_load_round_trip(tmp_path):
    adapter_tags.save_tag(tmp_path, "s1", "+1 Loft, Draw Bias")
    assert adapter_tags.load_tags(tmp_path) == {"s1": "+1 Loft, Draw Bias"}


def test_blank_label_clears_tag(tmp_path):
    adapter_tags.save_tag(tmp_path, "s1", "Neutral")
    adapter_tags.save_tag(tmp_path, "s1", "   ")
    assert adapter_tags.load_tags(tmp_path) == {}


def test_load_missing_file_is_empty(tmp_path):
    assert adapter_tags.load_tags(tmp_path) == {}


def test_load_corrupt_file_is_empty(tmp_path):
    (tmp_path / "adapter_tags.json").write_text("{not valid json", encoding="utf-8")
    assert adapter_tags.load_tags(tmp_path) == {}


def test_apply_tags_adds_adapter_column_without_corrupting_untagged():
    tagged = adapter_tags.apply_tags(_df(), {"s1": "Draw"})
    # s1 rows tagged, s2 (untagged) defaults to "" — never NaN, never dropped.
    assert list(tagged["adapter"]) == ["Draw", "Draw", ""]
    assert len(tagged) == 3


def test_apply_tags_is_nondestructive():
    df = _df()
    adapter_tags.apply_tags(df, {"s1": "Draw"})
    assert "adapter" not in df.columns  # original untouched


def test_apply_tags_no_session_id_column_gets_blank_column():
    df = pd.DataFrame({"club": ["Dr"], "carry": [250.0]})
    out = adapter_tags.apply_tags(df, {"s1": "Draw"})
    assert list(out["adapter"]) == [""]


def test_apply_tags_empty_frame_is_safe():
    out = adapter_tags.apply_tags(pd.DataFrame(), {"s1": "Draw"})
    assert out.empty


def test_available_tags_lists_distinct_sorted():
    tagged = adapter_tags.apply_tags(
        pd.DataFrame({"session_id": ["s1", "s2", "s3"]}),
        {"s1": "Draw", "s2": "Fade", "s3": "Draw"},
    )
    assert adapter_tags.available_tags(tagged) == ["Draw", "Fade"]
