"""Canonical field mapping for the official MOCK Excel.

Raw Excel headers stay in `source`. Canonical names are stable English identifiers.
String IDs must never be float-coerced.
"""

from __future__ import annotations

from typing import Any

CHAT_SHEET = "聊天记录"
ORDER_SHEET = "订单"

WORKORDER_SHEETS: dict[str, dict[str, Any]] = {
    "补发换货工单": {
        "kind": "reship_exchange",
        "status_field": "工单状态",
        "extra": [
            ("工单类型", "workorder_subtype", "string"),
            ("售后原因", "aftersale_reason", "string"),
            ("发出商品货号", "outbound_sku", "string_id"),
            ("发出商品名称", "outbound_product_name", "string"),
            ("数量", "quantity", "int"),
            ("原订单物流单号", "original_tracking_no", "string_id"),
            ("补发物流单号", "reship_tracking_no", "string_id"),
            ("快递公司", "courier", "string"),
            ("发货仓库", "warehouse", "string"),
            ("客诉加急", "urgent", "string"),
        ],
    },
    "线下打款工单": {
        "kind": "offline_payment",
        "status_field": "工单状态",
        "extra": [
            ("打款类型", "payment_type", "string"),
            ("退款问题类型", "refund_issue_type", "string"),
            ("退款金额(元)", "refund_amount", "number"),
            ("支付宝实名", "alipay_real_name", "string"),
            ("支付宝账号", "alipay_account", "string"),
            ("相关物流单号", "related_tracking_no", "string_id"),
            ("转账状态", "transfer_status", "string"),
        ],
    },
    "物流工单": {
        "kind": "logistics",
        "status_field": "工单状态",
        "extra": [
            ("问题类型", "issue_type", "string"),
            ("快递公司", "courier", "string"),
            ("问题包裹物流单号", "problem_tracking_no", "string_id"),
            ("发货仓", "warehouse", "string"),
            ("订单实付(元)", "order_paid_amount", "number"),
            ("处理方案", "handling_plan", "string"),
            ("收货省", "receiver_province", "string"),
            ("收货市", "receiver_city", "string"),
        ],
    },
    "不良反应工单": {
        "kind": "adverse_reaction",
        "status_field": "任务状态",
        "extra": [
            ("类型", "channel_type", "string"),
            ("年龄", "age", "int"),
            ("肤质", "skin_type", "string"),
            ("使用商品", "used_product", "string"),
            ("产品批次号", "batch_no", "string_id"),
            ("不适部位", "affected_area", "string"),
            ("症状描述", "symptom", "string"),
            ("用后多久出现", "onset_after", "string"),
            ("是否停用", "discontinued", "string"),
            ("是否就医", "sought_medical_care", "string"),
        ],
    },
    "售后退货工单": {
        "kind": "aftersale_return",
        "status_field": "任务状态",
        "extra": [
            ("包裹类型", "package_type", "string"),
            ("退货原因", "return_reason", "string"),
            ("退货物流单号", "return_tracking_no", "string_id"),
            ("快递公司", "courier", "string"),
            ("退款编号", "refund_no", "string_id"),
            ("签收建议", "receive_advice", "string"),
            ("是否异常", "is_abnormal", "string"),
        ],
    },
}

BUSINESS_SHEETS = (CHAT_SHEET, ORDER_SHEET, *WORKORDER_SHEETS.keys())

STRING_ID_FIELDS = frozenset(
    {
        "session_id",
        "message_id",
        "order_id",
        "workorder_id",
        "buyer_nick",
        "linked_order_id",
        "linked_workorder_id",
        "tracking_no",
        "original_tracking_no",
        "reship_tracking_no",
        "related_tracking_no",
        "problem_tracking_no",
        "return_tracking_no",
        "refund_no",
        "sku_code",
        "outbound_sku",
        "batch_no",
        "alipay_account",
    }
)

CHAT_FIELDS = [
    ("会话ID", "session_id", "string_id"),
    ("消息序号", "message_no", "int"),
    ("message_id", "message_id", "string_id"),
    ("发送时间", "message_time", "time"),
    ("角色", "role", "string"),
    ("买家昵称", "buyer_nick", "string_id"),
    ("发送方", "sender", "string"),
    ("店铺", "shop", "string"),
    ("scene_major", "scene_major", "string"),
    ("scene_minor", "scene_minor", "string"),
    ("is_target_buyer_message", "is_target_buyer_message", "bool"),
    ("message_text", "message_text", "string"),
    ("内容类型", "content_type", "string"),
    ("chat_content", "chat_content", "string"),
    ("category", "category", "string"),
    ("image_path", "image_path", "string"),
    ("关联订单号", "linked_order_id", "string_id"),
    ("关联工单号", "linked_workorder_id", "string_id"),
]

ORDER_FIELDS = [
    ("订单号", "order_id", "string_id"),
    ("会话ID", "session_id", "string_id"),
    ("买家昵称", "buyer_nick", "string_id"),
    ("店铺", "shop", "string"),
    ("商品货号", "sku_code", "string_id"),
    ("商品名称", "product_name", "string"),
    ("数量", "quantity", "int"),
    ("单价(元)", "unit_price", "number"),
    ("实付金额(元)", "paid_amount", "number"),
    ("订单状态", "order_status_raw", "string"),
    ("下单时间", "placed_time", "time"),
    ("付款时间", "paid_time", "time"),
    ("发货时间", "shipped_time", "time"),
    ("快递公司", "courier", "string"),
    ("物流单号", "tracking_no", "string_id"),
    ("收货省", "receiver_province", "string"),
    ("收货市", "receiver_city", "string"),
    ("赠品", "gift", "string"),
    ("买家留言", "buyer_note", "string"),
]

WORKORDER_COMMON_FIELDS = [
    ("工单号", "workorder_id", "string_id"),
    ("会话ID", "session_id", "string_id"),
    ("关联订单号", "order_id", "string_id"),
    ("买家昵称", "buyer_nick", "string_id"),
    ("店铺", "shop", "string"),
    ("处理人", "handler", "string"),
    ("创建时间", "create_time", "time"),
    ("完成时间", "complete_time", "time"),
]

COMPLETED_STATUS_VALUES = frozenset({"已完结"})

AGENT_ROLE = "客服"

SOURCE_INCONSISTENCY_KIND = "claimed_workorder_not_in_system"

SNAPSHOT_SCHEMA = "data_empathy.snapshot.v1"


def field_mapping_document() -> dict[str, Any]:
    def pack(rows: list[tuple[str, str, str]]) -> list[dict[str, str]]:
        return [
            {"source": src, "canonical": dst, "type": typ, "string_id": dst in STRING_ID_FIELDS}
            for src, dst, typ in rows
        ]

    workorders = {}
    for sheet, meta in WORKORDER_SHEETS.items():
        status_field = meta["status_field"]
        common = list(WORKORDER_COMMON_FIELDS) + [(status_field, "status_raw", "string")]
        workorders[sheet] = {
            "kind": meta["kind"],
            "status_source": status_field,
            "fields": pack(common + list(meta["extra"])),
        }
    return {
        "timezone": "Asia/Shanghai",
        "string_id_fields": sorted(STRING_ID_FIELDS),
        "business_sheets": list(BUSINESS_SHEETS),
        "chat": {"sheet": CHAT_SHEET, "fields": pack(CHAT_FIELDS)},
        "order": {"sheet": ORDER_SHEET, "fields": pack(ORDER_FIELDS)},
        "workorder": workorders,
        "notes": [
            "Chat 关联订单号/关联工单号 are backfilled potential keys, not proof of visibility.",
            "Order status has no effective time; snapshot must not treat 交易成功 as current fact.",
            "Workorder completion requires complete_time != null and complete_time <= as_of_time.",
        ],
    }
