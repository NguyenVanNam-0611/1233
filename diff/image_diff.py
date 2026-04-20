from __future__ import annotations

from typing import Dict, Any, Optional
from services.models.docnode import DocNode


def images_equal(a: Optional[DocNode], b: Optional[DocNode]) -> bool:
    if a is None and b is None:
        return True

    if a is None or b is None:
        return False

    if a.type != "image" or b.type != "image":
        return False

    # So sánh bằng sha256 trước (chính xác nhất)
    a_hash = a.content.get("sha256") or a.content.get("hash")
    b_hash = b.content.get("sha256") or b.content.get("hash")

    if a_hash and b_hash:
        return a_hash == b_hash

    # Fallback: so sánh kích thước EMU + tên file
    return (
        a.content.get("width_emu") == b.content.get("width_emu")
        and a.content.get("height_emu") == b.content.get("height_emu")
        and (a.content.get("name") or "") == (b.content.get("name") or "")
    )


def _image_payload(node: Optional[DocNode]) -> Optional[Dict[str, Any]]:
    """
    Serialize image node thành payload đầy đủ cho frontend render.
    Đảm bảo data_uri luôn có để hiển thị ảnh trực tiếp mà không cần
    round-trip thêm request.
    """
    if node is None:
        return None

    content = node.content or {}

    # width/height pixel (nếu có) và EMU (từ extractor)
    width_emu = content.get("width_emu") or 0
    height_emu = content.get("height_emu") or 0

    # Quy đổi EMU → pixel (1 inch = 914400 EMU, 96 dpi)
    # Dùng để frontend có thể render đúng tỉ lệ ảnh
    px_per_emu = 96 / 914400
    width_px = round(width_emu * px_per_emu) if width_emu else content.get("width")
    height_px = round(height_emu * px_per_emu) if height_emu else content.get("height")

    return {
        "uid": getattr(node, "uid", None),
        "type": "image",
        "display_type": "image",
        "order": getattr(node, "order", 0),
        "path": getattr(node, "path", ""),
        "image": {
            # Identifiers
            "name": content.get("name"),
            "ext": content.get("ext"),
            "hash": content.get("hash"),
            "sha256": content.get("sha256"),
            # Kích thước
            "width_emu": width_emu,
            "height_emu": height_emu,
            "width_px": width_px,
            "height_px": height_px,
            # Data URI để frontend render trực tiếp — không cần thêm request
            "data_uri": content.get("data_uri"),
            # Metadata phụ
            "mime": content.get("mime"),
            "rid": content.get("rid"),
        },
        "text": content.get("text", ""),
        "caption": content.get("caption", ""),
        # data_uri bubble lên top-level để dễ access hơn
        "data_uri": content.get("data_uri"),
    }


def build_image_change(
    a: Optional[DocNode],
    b: Optional[DocNode],
) -> Dict[str, Any]:
    """
    Tạo change object cho image.

    Naming thống nhất:
      - left  = original (bên trái trong side-by-side)
      - right = modified (bên phải trong side-by-side)

    Frontend dùng:
      - left_img.data_uri  để render ảnh gốc
      - right_img.data_uri để render ảnh mới
      - change_kind        để biết insert/delete/replace
    """
    left_payload = _image_payload(a)
    right_payload = _image_payload(b)

    # ---- IMAGE DELETED ----
    if a is not None and b is None:
        return {
            "type": "image_deleted",
            "display_type": "image",
            "change_kind": "delete",
            # left = có ảnh gốc, right = trống
            "left": left_payload,
            "right": None,
            "left_img": left_payload,
            "right_img": None,
        }

    # ---- IMAGE ADDED ----
    if b is not None and a is None:
        return {
            "type": "image_added",
            "display_type": "image",
            "change_kind": "insert",
            # left = trống, right = có ảnh mới
            "left": None,
            "right": right_payload,
            "left_img": None,
            "right_img": right_payload,
        }

    # ---- IMAGE MODIFIED (cả 2 đều có, khác nhau) ----
    return {
        "type": "image_modified",
        "display_type": "image",
        "change_kind": "replace",
        # Hiện cả 2 ảnh song song để so sánh
        "left": left_payload,
        "right": right_payload,
        "left_img": left_payload,
        "right_img": right_payload,
    }