from __future__ import annotations

from typing import List, Dict, Any, Optional

from services.models.docnode import DocNode
from services.diff.paragraph_diff import diff_words
from services.diff.image_diff import images_equal, build_image_change


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_node(node: Optional[DocNode]) -> Any:
    """
    Serialize DocNode thành dict đầy đủ, giữ nguyên children (nested table,
    image trong cell, paragraph...) để frontend render đúng cấu trúc.
    """
    if node is None:
        return None

    return {
        "uid": getattr(node, "uid", None),
        "type": node.type,
        "content": node.content,
        "children": [_serialize_node(c) for c in (node.children or [])],
    }


def _serialize_cell(cell: Optional[DocNode]) -> Optional[Dict[str, Any]]:
    """
    Serialize cell thành dict đầy đủ gồm text, col_index, row_index,
    span info và toàn bộ children (paragraph, image, nested table).
    Dùng cho left_cells / right_cells — không được mất rich content.
    """
    if cell is None:
        return None

    content = cell.content or {}

    return {
        "uid": getattr(cell, "uid", None),
        "type": "cell",
        "text": (content.get("text") or "").strip(),
        "row_index": content.get("row_index"),
        "col_index": content.get("col_index"),
        "row_span": content.get("row_span", 1),
        "col_span": content.get("col_span", 1),
        "is_merged": content.get("is_merged", False),
        "children": [_serialize_node(c) for c in (cell.children or [])],
    }


def _serialize_row(row: Optional[DocNode]) -> Optional[Dict[str, Any]]:
    """
    Serialize row với đầy đủ cells dạng rich (không phải plain text).
    """
    if row is None:
        return None

    cells = [c for c in (row.children or []) if c.type == "cell"]

    return {
        "uid": getattr(row, "uid", None),
        "type": "row",
        "row_index": (row.content or {}).get("row_index"),
        "text": (row.content or {}).get("text", ""),
        "cells": [_serialize_cell(c) for c in cells],
    }


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _cell_text(cell: Optional[DocNode]) -> str:
    if not cell:
        return ""
    return (cell.content.get("text") or "").strip()


def _row_text(row: Optional[DocNode]) -> str:
    if not row:
        return ""
    return (row.content.get("text") or "").strip()


def _get_rows(tbl: DocNode) -> List[DocNode]:
    return [c for c in (tbl.children or []) if c.type == "row"]


def _get_cells(row: DocNode) -> List[DocNode]:
    return [c for c in (row.children or []) if c.type == "cell"]


# ---------------------------------------------------------------------------
# Paragraph diff inside cell
# ---------------------------------------------------------------------------

def _diff_paragraph(a: DocNode, b: DocNode) -> Optional[Dict[str, Any]]:
    """
    So sánh 2 paragraph node bên trong cell.
    Trả về change object với old_full_text / new_full_text / spans rõ ràng
    để frontend render cả đoạn và highlight chỗ thay đổi.
    """
    old_text = (a.content.get("text") or "").strip()
    new_text = (b.content.get("text") or "").strip()

    text_changed = old_text != new_text
    a_imgs = [c for c in (a.children or []) if c.type == "image"]
    b_imgs = [c for c in (b.children or []) if c.type == "image"]

    if not text_changed and not a_imgs and not b_imgs:
        return None

    changes: List[Dict[str, Any]] = []

    if text_changed:
        word_diff = diff_words(old_text, new_text)
        # diff_words trả về list có 1 phần tử chứa old_full_text/new_full_text/spans
        diff_result = word_diff[0] if word_diff else {}
        changes.append(
            {
                "type": "paragraph_modified",
                "old_full_text": diff_result.get("old_full_text", old_text),
                "new_full_text": diff_result.get("new_full_text", new_text),
                "spans": diff_result.get("spans", []),
                "original_content": a.content,
                "modified_content": b.content,
            }
        )

    max_img = max(len(a_imgs), len(b_imgs))
    for i in range(max_img):
        ai = a_imgs[i] if i < len(a_imgs) else None
        bi = b_imgs[i] if i < len(b_imgs) else None

        if images_equal(ai, bi):
            continue

        changes.append(build_image_change(ai, bi))

    if not changes:
        return None

    return {
        "type": "paragraph_container_modified",
        "original": _serialize_node(a),
        "modified": _serialize_node(b),
        "changes": changes,
    }


# ---------------------------------------------------------------------------
# Cell diff
# ---------------------------------------------------------------------------

def _diff_cell(a: DocNode, b: DocNode) -> List[Dict[str, Any]]:
    """
    So sánh nội dung 2 cell.
    Xử lý: paragraph, image, nested table, type mismatch.
    Không dùng plain text — giữ nguyên rich content.
    """
    changes: List[Dict[str, Any]] = []

    a_children = a.children or []
    b_children = b.children or []
    max_len = max(len(a_children), len(b_children))

    for i in range(max_len):
        ac = a_children[i] if i < len(a_children) else None
        bc = b_children[i] if i < len(b_children) else None

        # --- một bên không có ---
        if ac is None and bc is not None:
            changes.append(
                {
                    "type": f"{bc.type}_inserted",
                    "change_kind": "insert",
                    "original": None,
                    "modified": _serialize_node(bc),
                }
            )
            continue

        if bc is None and ac is not None:
            changes.append(
                {
                    "type": f"{ac.type}_deleted",
                    "change_kind": "delete",
                    "original": _serialize_node(ac),
                    "modified": None,
                }
            )
            continue

        if ac is None or bc is None:
            continue

        # --- cùng type ---
        if ac.type == "paragraph" and bc.type == "paragraph":
            paragraph_change = _diff_paragraph(ac, bc)
            if paragraph_change:
                changes.append(paragraph_change)
            continue

        if ac.type == "image" and bc.type == "image":
            if not images_equal(ac, bc):
                changes.append(build_image_change(ac, bc))
            continue

        if ac.type == "table" and bc.type == "table":
            nested_changes = diff_table(ac, bc)
            if nested_changes:
                changes.append(
                    {
                        "type": "nested_table_modified",
                        "change_kind": "replace",
                        "original": _serialize_node(ac),
                        "modified": _serialize_node(bc),
                        "changes": nested_changes,
                    }
                )
            continue

        # --- khác type ---
        if ac.type != bc.type:
            changes.append(
                {
                    "type": "node_type_changed",
                    "change_kind": "replace",
                    "original": _serialize_node(ac),
                    "modified": _serialize_node(bc),
                }
            )

    return changes


# ---------------------------------------------------------------------------
# Main: diff_table
# ---------------------------------------------------------------------------

def diff_table(a_tbl: DocNode, b_tbl: DocNode) -> List[Dict[str, Any]]:
    """
    So sánh 2 table node.

    Mỗi row change trả về:
      - type: "table_row_added" | "table_row_deleted" | "table_row_modified"
      - change_kind: "insert" | "delete" | "replace"
      - left_row / right_row: serialize đầy đủ (cells với rich content)
      - left_cells / right_cells: List[Dict] đầy đủ (KHÔNG phải List[str])
      - cell_changes: chi tiết thay đổi từng cell (chỉ có khi modified)

    Row added  → left_row=None,  right_row=full, left_cells=[],   right_cells=full
    Row deleted → left_row=full, right_row=None, left_cells=full, right_cells=[]
    Row modified → cả hai đầy đủ + cell_changes
    """
    changes: List[Dict[str, Any]] = []

    a_rows = _get_rows(a_tbl)
    b_rows = _get_rows(b_tbl)
    max_rows = max(len(a_rows), len(b_rows)) if (a_rows or b_rows) else 0

    for r in range(max_rows):
        ar = a_rows[r] if r < len(a_rows) else None
        br = b_rows[r] if r < len(b_rows) else None

        # ---- ROW ADDED (chỉ có bên modified) ----
        if ar is None and br is not None:
            b_cells = _get_cells(br)
            changes.append(
                {
                    "type": "table_row_added",
                    "change_kind": "insert",
                    "row_index": r,
                    "left_row": None,
                    "right_row": _serialize_row(br),
                    "left_cells": [],
                    # right_cells là List[Dict] đầy đủ để frontend render bảng
                    "right_cells": [_serialize_cell(c) for c in b_cells],
                    "left_text": "",
                    "right_text": _row_text(br),
                    "cell_changes": [],
                }
            )
            continue

        # ---- ROW DELETED (chỉ có bên original) ----
        if br is None and ar is not None:
            a_cells = _get_cells(ar)
            changes.append(
                {
                    "type": "table_row_deleted",
                    "change_kind": "delete",
                    "row_index": r,
                    "left_row": _serialize_row(ar),
                    "right_row": None,
                    # left_cells là List[Dict] đầy đủ để frontend render bảng
                    "left_cells": [_serialize_cell(c) for c in a_cells],
                    "right_cells": [],
                    "left_text": _row_text(ar),
                    "right_text": "",
                    "cell_changes": [],
                }
            )
            continue

        if ar is None or br is None:
            continue

        # ---- ROW MODIFIED (có cả hai, so sánh cell) ----
        a_cells = _get_cells(ar)
        b_cells = _get_cells(br)
        max_cells = max(len(a_cells), len(b_cells)) if (a_cells or b_cells) else 0

        row_changed = False
        row_cell_changes: List[Dict[str, Any]] = []

        for c in range(max_cells):
            ac = a_cells[c] if c < len(a_cells) else None
            bc = b_cells[c] if c < len(b_cells) else None

            # Cell chỉ có bên modified
            if ac is None and bc is not None:
                row_changed = True
                row_cell_changes.append(
                    {
                        "type": "table_cell_added",
                        "change_kind": "insert",
                        "col_index": c,
                        "left_cell": None,
                        "right_cell": _serialize_cell(bc),
                        "left_text": "",
                        "right_text": _cell_text(bc),
                        "changes": [],
                    }
                )
                continue

            # Cell chỉ có bên original
            if bc is None and ac is not None:
                row_changed = True
                row_cell_changes.append(
                    {
                        "type": "table_cell_deleted",
                        "change_kind": "delete",
                        "col_index": c,
                        "left_cell": _serialize_cell(ac),
                        "right_cell": None,
                        "left_text": _cell_text(ac),
                        "right_text": "",
                        "changes": [],
                    }
                )
                continue

            if ac is None or bc is None:
                continue

            # So sánh nội dung cell
            cell_changes = _diff_cell(ac, bc)

            if cell_changes:
                row_changed = True
                row_cell_changes.append(
                    {
                        "type": "table_cell_modified",
                        "change_kind": "replace",
                        "col_index": c,
                        "left_cell": _serialize_cell(ac),
                        "right_cell": _serialize_cell(bc),
                        "left_text": _cell_text(ac),
                        "right_text": _cell_text(bc),
                        "changes": cell_changes,
                    }
                )

        if row_changed or _row_text(ar) != _row_text(br):
            changes.append(
                {
                    "type": "table_row_modified",
                    "change_kind": "replace",
                    "row_index": r,
                    "left_row": _serialize_row(ar),
                    "right_row": _serialize_row(br),
                    "left_cells": [_serialize_cell(c) for c in a_cells],
                    "right_cells": [_serialize_cell(c) for c in b_cells],
                    "left_text": _row_text(ar),
                    "right_text": _row_text(br),
                    "cell_changes": row_cell_changes,
                }
            )

    return changes