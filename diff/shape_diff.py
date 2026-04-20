from __future__ import annotations

from typing import List, Dict, Any, Optional
import difflib

from services.models.docnode import DocNode
from services.models.block import Block
from services.block.signature import signature
from services.diff.paragraph_diff import diff_words
from services.diff.table_diff import diff_table
from services.diff.image_diff import images_equal, build_image_change


def _serialize_node(node: Optional[DocNode]) -> Optional[Dict[str, Any]]:
    if node is None:
        return None

    return {
        "uid": getattr(node, "uid", None),
        "type": node.type,
        "display_type": node.type,
        "order": getattr(node, "order", 0),
        "path": getattr(node, "path", ""),
        "content": node.content or {},
        "children": [
            _serialize_node(c)
            for c in (node.children or [])
        ],
    }


def _blocks_from_children(children: List[DocNode]) -> List[Block]:
    return [
        Block(
            type=n.type,
            node=n,
            signature=signature(n),
            heading_ctx=None,
            order=getattr(n, "order", 0),
        )
        for n in children
    ]


def _build_basic_change(
    cid: int,
    change_type: str,
    change_kind: str,
    original: Optional[Dict[str, Any]],
    modified: Optional[Dict[str, Any]],
    diff_spans: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "id": cid,
        "type": change_type,
        "display_type": change_type.replace("_modified", "").replace("_inserted", "").replace("_deleted", ""),
        "change_kind": change_kind,
        "original": original,
        "modified": modified,
        "left_context": original,
        "right_context": modified,
        "diff_spans": diff_spans,
    }


def diff_shape(a_shape: DocNode, b_shape: DocNode) -> List[Dict[str, Any]]:
    a_blocks = _blocks_from_children(a_shape.children or [])
    b_blocks = _blocks_from_children(b_shape.children or [])

    sm = difflib.SequenceMatcher(
        a=[x.signature for x in a_blocks],
        b=[x.signature for x in b_blocks],
        autojunk=False,
    )

    changes: List[Dict[str, Any]] = []
    cid = 1

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue

        if tag == "insert":
            for blk in b_blocks[j1:j2]:
                changes.append(
                    _build_basic_change(
                        cid=cid,
                        change_type=f"{blk.type}_inserted",
                        change_kind="insert",
                        original=None,
                        modified=_serialize_node(blk.node),
                    )
                )
                cid += 1
            continue

        if tag == "delete":
            for blk in a_blocks[i1:i2]:
                changes.append(
                    _build_basic_change(
                        cid=cid,
                        change_type=f"{blk.type}_deleted",
                        change_kind="delete",
                        original=_serialize_node(blk.node),
                        modified=None,
                    )
                )
                cid += 1
            continue

        if tag == "replace":
            pairs = min(i2 - i1, j2 - j1)

            for k in range(pairs):
                a_node = a_blocks[i1 + k].node
                b_node = b_blocks[j1 + k].node

                a_serialized = _serialize_node(a_node)
                b_serialized = _serialize_node(b_node)

                if a_node.type == "paragraph" and b_node.type == "paragraph":
                    old = a_node.content.get("text", "") or ""
                    new = b_node.content.get("text", "") or ""

                    if old != new:
                        changes.append(
                            _build_basic_change(
                                cid=cid,
                                change_type="paragraph_modified",
                                change_kind="replace",
                                original=a_serialized,
                                modified=b_serialized,
                                diff_spans=diff_words(old, new),
                            )
                        )
                        cid += 1
                    continue

                if a_node.type == "table" and b_node.type == "table":
                    table_changes = diff_table(a_node, b_node)

                    if table_changes:
                        changes.append(
                            {
                                "id": cid,
                                "type": "table_modified",
                                "display_type": "table",
                                "change_kind": "replace",
                                "original": a_serialized,
                                "modified": b_serialized,
                                "left_context": a_serialized,
                                "right_context": b_serialized,
                                "changes": table_changes,
                            }
                        )
                        cid += 1
                    continue

                if a_node.type == "image" and b_node.type == "image":
                    if not images_equal(a_node, b_node):
                        image_change = build_image_change(a_node, b_node)
                        image_change["id"] = cid
                        changes.append(image_change)
                        cid += 1
                    continue

                changes.append(
                    _build_basic_change(
                        cid=cid,
                        change_type=f"{a_node.type}_to_{b_node.type}_modified",
                        change_kind="replace",
                        original=a_serialized,
                        modified=b_serialized,
                    )
                )
                cid += 1

            for blk in a_blocks[i1 + pairs:i2]:
                changes.append(
                    _build_basic_change(
                        cid=cid,
                        change_type=f"{blk.type}_deleted",
                        change_kind="delete",
                        original=_serialize_node(blk.node),
                        modified=None,
                    )
                )
                cid += 1

            for blk in b_blocks[j1 + pairs:j2]:
                changes.append(
                    _build_basic_change(
                        cid=cid,
                        change_type=f"{blk.type}_inserted",
                        change_kind="insert",
                        original=None,
                        modified=_serialize_node(blk.node),
                    )
                )
                cid += 1

    return changes