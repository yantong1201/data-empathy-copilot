"""48/12 split + regression roster + sample units, per evaluation protocol §2/§7."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.data_empathy.codec import dumps_canonical, dumps_hash_payload
from backend.data_empathy.loader import DataStore

FROZEN_SESSIONS = (
    "S00015", "S00024", "S00001", "S00064", "S00087", "S00060",
    "S00010", "S00082", "S00011", "S00045", "S00134", "S00268",
)
REGRESSION_SESSIONS = (
    "S00065", "S00232", "S00003", "S00277", "S00042",
    "S00070", "S00303", "S00073", "S00474", "S00154",
)
DEV_SIZE = 48

SCENE_MAJORS = (
    "不良反应", "产品咨询", "会员服务", "其他服务", "售后退货",
    "物流异常", "物流服务", "补发换货", "订单服务", "退款打款",
)
SCENE_MINORS = (
    "七天无理由退货", "仅退款疑似异常", "优惠与赠品咨询", "会员权益加赠补发", "使用不适退货",
    "使用方法", "保价申请被拒", "催发货", "包裹少件", "包裹破损", "发票申请",
    "售后期关闭过敏退款", "大促价保补差", "套装搭配推荐", "好评回访", "孕妇可用咨询",
    "少发正装", "成分与肤质适配", "拆封少件拒收", "拦截改址", "显示签收未收到", "正品鉴别咨询",
    "比价与决策", "泛红刺痒", "漏发赠品", "物流停滞疑似丢件", "物流查询", "直播间承诺纠纷",
    "破损换货", "积分兑换咨询", "色号不合适退货", "色号选择", "质疑正品退货", "过敏就医",
    "退款进度查询", "退款迟迟不到账", "退款金额少退补打", "退货运费报销", "错发色号",
    "闷痘爆痘", "预售尾款咨询",
)
ONTOLOGY_VERSION = "intent_ontology_v1"


def ontology_doc() -> dict[str, Any]:
    return {
        "version": ONTOLOGY_VERSION,
        "scene_major": list(SCENE_MAJORS),
        "scene_minor": list(SCENE_MINORS),
        "note": "标签字符串保持协议原文，不做同义词合并；预测 unclear 不参与 Macro-F1",
    }


def ontology_hash() -> str:
    return hashlib.sha256(
        dumps_hash_payload(ontology_doc()).encode("utf-8")).hexdigest()


def _buyer_key(store: DataStore, session_id: str) -> str:
    rows = store.chats_by_session.get(session_id) or []
    nick = rows[0].buyer_nick if rows else ""
    shop = rows[0].shop or ""
    return f"{nick}|{shop}"


def build_split(store: DataStore) -> dict[str, Any]:
    """Deterministic dev-48 selection: session_id order, buyer isolation.

    Frozen 12 and regression 10 come verbatim from the protocol. Dev candidates
    are all other sessions sorted by session_id; any session whose buyer
    (nick+shop) already appears in frozen/regression is skipped so the same
    buyer never crosses sets. Unselected sessions stay in a labeled pool.
    """
    all_sessions = sorted(store.chats_by_session.keys())
    frozen = [s for s in FROZEN_SESSIONS if s in store.chats_by_session]
    regression = [s for s in REGRESSION_SESSIONS if s in store.chats_by_session]
    protected_buyers = {_buyer_key(store, s) for s in frozen + regression}
    dev: list[str] = []
    pool: list[str] = []
    for session_id in all_sessions:
        if session_id in frozen or session_id in regression:
            continue
        if _buyer_key(store, session_id) in protected_buyers:
            pool.append(session_id)
            continue
        if len(dev) < DEV_SIZE:
            dev.append(session_id)
        else:
            pool.append(session_id)

    buyer_sets = {
        "frozen": {_buyer_key(store, s) for s in frozen},
        "regression": {_buyer_key(store, s) for s in regression},
        "dev": {_buyer_key(store, s) for s in dev},
    }
    cross = {
        "frozen∩dev": sorted(buyer_sets["frozen"] & buyer_sets["dev"]),
        "frozen∩regression": sorted(buyer_sets["frozen"] & buyer_sets["regression"]),
        "dev∩regression": sorted(buyer_sets["dev"] & buyer_sets["regression"]),
    }

    split = {
        "split_version": "split_v1",
        "method": (
            "冻结12与回归10按评测协议固定；开发集48=其余会话按 session_id 升序排除"
            "冻结/回归及其同买家(昵称+店铺)会话后取前48；未选入会话登记为 pool"
        ),
        "frozen": frozen,
        "regression": regression,
        "dev": dev,
        "pool_not_in_eval": pool,
        "buyer_isolation": {"cross_sets": cross, "isolated": not any(cross.values())},
        "ontology": ontology_doc(),
    }
    split["split_sha256"] = hashlib.sha256(
        dumps_hash_payload({k: split[k] for k in ("frozen", "regression", "dev", "pool_not_in_eval")})
        .encode("utf-8")).hexdigest()
    split["ontology_sha256"] = ontology_hash()
    return split


def sample_units(store: DataStore, split: dict[str, Any], set_name: str) -> list[dict[str, Any]]:
    """(session_id, message_no, as_of_time) units: target buyer messages only."""
    units = []
    for session_id in split[set_name]:
        for row in store.chats_by_session.get(session_id, []):
            if row.is_target_buyer_message:
                units.append({
                    "sample_id": f"{session_id}#{row.message_no}",
                    "session_id": session_id,
                    "message_no": row.message_no,
                    "as_of_time": row.message_time.isoformat(),
                })
    return units
