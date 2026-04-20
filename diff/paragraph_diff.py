from __future__ import annotations

import difflib
from typing import List, Dict, Any, Optional


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split()).strip()


def _char_diff_spans(old_word: str, new_word: str) -> Dict[str, Any]:
    """
    Khi một từ bị replace, tính thêm char-level diff bên trong từ đó.
    Trả về dict gồm old_chars / new_chars là list span char với type equal/delete/insert.
    Dùng để frontend highlight chính xác từng ký tự thay đổi bên trong từ.
    """
    sm = difflib.SequenceMatcher(a=list(old_word), b=list(new_word), autojunk=False)
    old_chars: List[Dict[str, Any]] = []
    new_chars: List[Dict[str, Any]] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old_seg = old_word[i1:i2]
        new_seg = new_word[j1:j2]

        if tag == "equal":
            old_chars.append({"type": "equal", "text": old_seg})
            new_chars.append({"type": "equal", "text": new_seg})
        elif tag == "delete":
            old_chars.append({"type": "delete", "text": old_seg})
        elif tag == "insert":
            new_chars.append({"type": "insert", "text": new_seg})
        elif tag == "replace":
            old_chars.append({"type": "delete", "text": old_seg})
            new_chars.append({"type": "insert", "text": new_seg})

    return {"old_chars": old_chars, "new_chars": new_chars}


def diff_words(old_text: str, new_text: str) -> Dict[str, Any]:
    """
    So sánh 2 đoạn text ở mức word, trả về dict gồm:
      - old_full_text  : toàn bộ đoạn gốc (để render cả đoạn bên left)
      - new_full_text  : toàn bộ đoạn mới (để render cả đoạn bên right)
      - spans          : list các span, mỗi span là một từ hoặc nhóm từ với type:
                           "equal"  — giống nhau, hiện bình thường cả 2 bên
                           "delete" — chỉ có bên left, highlight đỏ
                           "insert" — chỉ có bên right, highlight xanh
                           "replace"— từ bị thay thế, có thêm char_diff để
                                      highlight chính xác từng ký tự thay đổi

    Cursor tracking dùng để tính old_start/old_end/new_start/new_end
    tính theo char offset trong normalized text, dùng cho frontend positioning.
    """
    old_text = _normalize_text(old_text or "")
    new_text = _normalize_text(new_text or "")

    a = old_text.split()
    b = new_text.split()

    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    spans: List[Dict[str, Any]] = []
    old_cursor = 0
    new_cursor = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old_words = a[i1:i2]
        new_words = b[j1:j2]
        old_segment = " ".join(old_words)
        new_segment = " ".join(new_words)

        if tag == "equal":
            if old_segment:
                spans.append(
                    {
                        "type": "equal",
                        "action": "equal",
                        "side": "both",
                        "old_text": old_segment,
                        "new_text": old_segment,
                        "text": old_segment,
                        "old_start": old_cursor,
                        "old_end": old_cursor + len(old_segment),
                        "new_start": new_cursor,
                        "new_end": new_cursor + len(old_segment),
                        "char_diff": None,
                    }
                )
                old_cursor += len(old_segment) + 1
                new_cursor += len(old_segment) + 1
            continue

        if tag == "delete":
            if old_segment:
                spans.append(
                    {
                        "type": "delete",
                        "action": "delete",
                        "side": "left",
                        "old_text": old_segment,
                        "new_text": "",
                        "text": old_segment,
                        "old_start": old_cursor,
                        "old_end": old_cursor + len(old_segment),
                        "new_start": new_cursor,
                        "new_end": new_cursor,
                        "char_diff": None,
                    }
                )
                old_cursor += len(old_segment) + 1
            continue

        if tag == "insert":
            if new_segment:
                spans.append(
                    {
                        "type": "insert",
                        "action": "insert",
                        "side": "right",
                        "old_text": "",
                        "new_text": new_segment,
                        "text": new_segment,
                        "old_start": old_cursor,
                        "old_end": old_cursor,
                        "new_start": new_cursor,
                        "new_end": new_cursor + len(new_segment),
                        "char_diff": None,
                    }
                )
                new_cursor += len(new_segment) + 1
            continue

        if tag == "replace":
            # Ghép thành 1 span "replace" thay vì tách delete+insert riêng,
            # để frontend biết đây là cùng 1 vị trí — render song song 2 bên.
            # Thêm char_diff để highlight chính xác ký tự thay đổi bên trong.
            char_diff: Optional[Dict[str, Any]] = None
            if len(old_words) == 1 and len(new_words) == 1:
                # Single word replace — tính char diff
                char_diff = _char_diff_spans(old_words[0], new_words[0])

            old_start = old_cursor
            new_start = new_cursor

            if old_segment:
                old_cursor += len(old_segment) + 1
            if new_segment:
                new_cursor += len(new_segment) + 1

            spans.append(
                {
                    "type": "replace",
                    "action": "replace",
                    "side": "both",
                    "old_text": old_segment,
                    "new_text": new_segment,
                    # text = old để dễ fallback khi render left
                    "text": old_segment,
                    "old_start": old_start,
                    "old_end": old_start + len(old_segment),
                    "new_start": new_start,
                    "new_end": new_start + len(new_segment),
                    "char_diff": char_diff,
                }
            )

    return {
        "old_full_text": old_text,
        "new_full_text": new_text,
        "spans": spans,
    }