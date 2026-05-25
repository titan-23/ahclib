import json
import os
import sys
from collections import deque


def compute_tree_layout(root_id, children_dict, nodes_dict, MIN_GAP=1.0, mutate_children_order=False):
    """Reingold-Tilford 風のツリーレイアウトを計算する。
    children_dict: parent_id -> 子IDのリスト
    mutate_children_order=True の場合、children_dict の子順を最適化（重い枝を中央）して書き換える。
    Returns: {node_id: x_position}

    pass1 は反復化されており、各ノードの contour は (depth -> x) の dict ではなく
    深さ毎の最小/最大値を持つ配列で管理する（小さいオフセットの contour は
    親の contour に shift 加算して merge する代わりに、累積 shift で一括ずらしする）。
    """
    if mutate_children_order:
        eff_children = children_dict
    else:
        eff_children = {pid: list(kids) for pid, kids in children_dict.items()}

    # 反復で subtree_size と post-order の順序を計算
    subtree_size = {}
    post_order = []
    stack = [(root_id, False)]
    while stack:
        nid, processed = stack.pop()
        if processed:
            kids = eff_children.get(nid, [])
            subtree_size[nid] = 1 + sum(subtree_size.get(k, 1) for k in kids)
            post_order.append(nid)
        else:
            stack.append((nid, True))
            for k in eff_children.get(nid, []):
                stack.append((k, False))

    # 重い枝を中央に
    for pid in list(eff_children.keys()):
        kids = eff_children[pid]
        if len(kids) <= 1:
            continue
        sorted_kids = sorted(kids, key=lambda k: subtree_size.get(k, 0), reverse=True)
        arranged = deque()
        for i, k in enumerate(sorted_kids):
            if i % 2 == 0:
                arranged.append(k)
            else:
                arranged.appendleft(k)
        eff_children[pid] = list(arranged)

    node_offsets = {}
    # 各ノードの contour: (left_contour_dict, right_contour_dict) 形式の代わりに
    # 深さ -> 値 の dict をそのまま持つ（merge は shift 加算で対応）
    left_contours = {}
    right_contours = {}

    for nid in post_order:
        kids = eff_children.get(nid, [])
        depth = nodes_dict[nid]["turn"] if nid in nodes_dict else 0

        if not kids:
            node_offsets[nid] = 0.0
            left_contours[nid] = {depth: 0.0}
            right_contours[nid] = {depth: 0.0}
            continue

        # 最初の子の contour を借りる（後段で shift=0 として shift マップに記録）
        first_child = kids[0]
        merged_left = dict(left_contours[first_child])
        merged_right = dict(right_contours[first_child])

        kid_shifts = [0.0]

        for i in range(1, len(kids)):
            child = kids[i]
            c_left = left_contours[child]
            c_right = right_contours[child]

            # shift 計算: 各深さで right(merged) - left(c) + MIN_GAP の最大値
            shift = 0.0
            if len(c_left) < len(merged_right):
                small, large = c_left, merged_right
                # 小さい方の dict をループ
                for d, lv in small.items():
                    rv = large.get(d)
                    if rv is not None:
                        req = rv - lv + MIN_GAP
                        if req > shift:
                            shift = req
            else:
                for d, rv in merged_right.items():
                    lv = c_left.get(d)
                    if lv is not None:
                        req = rv - lv + MIN_GAP
                        if req > shift:
                            shift = req

            kid_shifts.append(shift)

            # contour 更新
            for d, val in c_left.items():
                shifted_val = val + shift
                cur = merged_left.get(d)
                if cur is None or shifted_val < cur:
                    merged_left[d] = shifted_val

            for d, val in c_right.items():
                shifted_val = val + shift
                cur = merged_right.get(d)
                if cur is None or shifted_val > cur:
                    merged_right[d] = shifted_val

        # 子の不要 contour を解放（メモリ削減）
        for child in kids:
            left_contours.pop(child, None)
            right_contours.pop(child, None)

        parent_x = (kid_shifts[0] + kid_shifts[-1]) / 2.0

        for i, child in enumerate(kids):
            node_offsets[child] = kid_shifts[i] - parent_x

        if parent_x != 0.0:
            for d in merged_left:
                merged_left[d] -= parent_x
            for d in merged_right:
                merged_right[d] -= parent_x

        cur_l = merged_left.get(depth)
        if cur_l is None or 0.0 < cur_l:
            merged_left[depth] = 0.0
        cur_r = merged_right.get(depth)
        if cur_r is None or 0.0 > cur_r:
            merged_right[depth] = 0.0

        left_contours[nid] = merged_left
        right_contours[nid] = merged_right

    # contour を解放
    left_contours.clear()
    right_contours.clear()

    positions = {}
    pass2_stack = [(root_id, 0.0)]
    while pass2_stack:
        nid, current_x = pass2_stack.pop()
        positions[nid] = current_x
        for child in eff_children.get(nid, []):
            child_x = current_x + node_offsets.get(child, 0.0)
            pass2_stack.append((child, child_x))

    return positions


def compute_compact_layout(active_set, children_dict_full, nodes_dict, root_id="-1"):
    """active_set に含まれるノードだけからなるサブツリーのレイアウトを計算。
    children_dict_full は変更されない。active_set 起点で走査し O(|active_set|) で構築する。"""
    sub_children = {}

    root_kids = children_dict_full.get(root_id)
    if root_kids:
        filtered = [k for k in root_kids if k in active_set]
        if filtered:
            sub_children[root_id] = filtered

    for pid in active_set:
        kids = children_dict_full.get(pid)
        if not kids:
            continue
        filtered = [k for k in kids if k in active_set]
        if filtered:
            sub_children[pid] = filtered

    return compute_tree_layout(root_id, sub_children, nodes_dict, mutate_children_order=True)


def load_and_process_data(filepath="history.json"):
    if not os.path.exists(filepath):
        return {"current_data": {}}, 1, {0: "0"}

    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if "nodes" not in raw_data:
        inf_val = raw_data.get("INF", 1e18)
        parent_ids = raw_data.get("parent_ids", [])
        scores = raw_data.get("scores", [])
        actions = raw_data.get("actions", [])
        hashes = raw_data.get("hashes", [])
        statuses = raw_data.get("statuses", [])
        turn_starts = raw_data.get("turn_start_indices", [])
        answer_indices = set(raw_data.get("answer_indices", []))
        state_infos = raw_data.get("state_infos", {})

        num_nodes = len(parent_ids)
        nodes = []

        turn_idx = 0
        num_turns = len(turn_starts)
        turns = [0] * num_nodes
        for i in range(num_nodes):
            if turn_idx + 1 < num_turns and i >= turn_starts[turn_idx + 1]:
                turn_idx += 1
            turns[i] = turn_idx + 1

        snapshots_dict_temp = {}
        for i in range(num_nodes):
            t = turns[i]
            status = statuses[i]
            nodes.append(
                {
                    "node_id": i,
                    "parent_id": parent_ids[i],
                    "turn": t,
                    "score": scores[i],
                    "hash": hashes[i],
                    "action": actions[i],
                    "state_info": state_infos.get(str(i), {}),
                    "status": status,
                    "is_answer": i in answer_indices,
                }
            )
            if status == 0:
                if t not in snapshots_dict_temp:
                    snapshots_dict_temp[t] = []
                snapshots_dict_temp[t].append(i)

        snapshots_list = [
            {"turn": t, "active_node_ids": active_ids}
            for t, active_ids in snapshots_dict_temp.items()
        ]

        data = {"INF": inf_val, "nodes": nodes, "snapshots": snapshots_list}
    else:
        data = raw_data

    nodes = data.get("nodes", [])
    inf_val = data.get("INF", 1e18)

    # 1. ノードIDで一意に保ち、複数親を持つDAG化（ゴーストエッジの交差）を完全に防ぐ
    nodes_dict = {str(n["node_id"]): n for n in nodes}

    # vis_beam.py が描画する実データも重複排除済みのものに差し替える
    data["nodes"] = list(nodes_dict.values())

    children_dict = {}

    # 必ず重複排除後の辞書から親子関係を構築する
    for nid, n in nodes_dict.items():
        pid = str(n["parent_id"])
        if pid not in children_dict:
            children_dict[pid] = []
        children_dict[pid].append(nid)

    turn_stats = {}
    for nid, n in nodes_dict.items():
        t = n["turn"]
        s = n["score"]
        status = n.get("status", 0)

        if t not in turn_stats:
            turn_stats[t] = {
                "scores": [],
                "generated": 0,
                "invalid": 0,
                "pruned": 0,
                "unique_parents": 0,
            }

        turn_stats[t]["generated"] += 1

        if status == 2:
            turn_stats[t]["invalid"] += 1
        elif s >= inf_val or status == 1:
            turn_stats[t]["pruned"] += 1
        else:
            turn_stats[t]["scores"].append(s)

    snapshots_dict = {
        s["turn"]: {
            "active": s["active_node_ids"],
            "threshold": s.get("threshold", inf_val),
        }
        for s in data.get("snapshots", [])
    }

    # 多様性（生存している active ノードの親の種類数）を計算
    for t, snapshot in snapshots_dict.items():
        active_ids = snapshot["active"]
        parents = set()
        for active_id in active_ids:
            active_nid = str(active_id)
            if active_nid in nodes_dict:
                parents.add(nodes_dict[active_nid]["parent_id"])
        if t in turn_stats:
            turn_stats[t]["unique_parents"] = len(parents)

    for t, snapshot in snapshots_dict.items():
        active_ids = snapshot["active"]
        parents = set()
        valid_active_ids = []

        for active_id in active_ids:
            active_nid = str(active_id)
            if active_nid in nodes_dict:
                parents.add(nodes_dict[active_nid]["parent_id"])
                node_data = nodes_dict[active_nid]
                if node_data["score"] < inf_val and node_data.get("status", 0) not in (
                    1,
                    2,
                ):
                    valid_active_ids.append(active_nid)

        if t in turn_stats:
            turn_stats[t]["unique_parents"] = len(parents)

            paths = []
            for nid in valid_active_ids:
                path = []
                curr = nid
                while curr != "-1" and curr in nodes_dict:
                    path.append(curr)
                    curr = str(nodes_dict[curr]["parent_id"])
                path.append("-1")
                paths.append(path[::-1])

            common_count = 0
            if paths:
                min_len = min(len(p) for p in paths)
                for i in range(min_len):
                    if all(p[i] == paths[0][i] for p in paths):
                        common_count += 1
                    else:
                        break

            turn_stats[t]["common_ancestor_depth"] = (
                max(0, common_count - 1) if paths else 0
            )

    valid_scores = [n["score"] for n in data["nodes"] if n["score"] < inf_val]

    for t, stats in turn_stats.items():
        scores = stats["scores"]
        count = len(scores)
        if count > 0:
            stats["count"] = count
            stats["min"] = min(scores)
            stats["max"] = max(scores)
            stats["mean"] = sum(scores) / count
        else:
            stats["count"] = 0
            stats["min"] = 0
            stats["max"] = 0
            stats["mean"] = 0

    positions = compute_tree_layout("-1", children_dict, nodes_dict, mutate_children_order=True)

    # 未配置ノードのフォールバック
    for nid in nodes_dict:
        if nid not in positions:
            positions[nid] = 0.0

    # 最終的な固定座標
    base_positions = {
        "-1": {
            "depth": 0,
            "breadth_center": positions.get("-1", 0.0),
        }
    }

    for nid, node in nodes_dict.items():
        base_positions[nid] = {
            "depth": node["turn"],
            "breadth_center": positions.get(nid, 0.0),
        }

    processed = {
        "current_data": data,
        "nodes_dict": nodes_dict,
        "children_dict": children_dict,
        "snapshots_dict": snapshots_dict,
        "valid_scores": valid_scores,
        "turn_stats": turn_stats,
        "base_positions": base_positions,
    }

    max_t = max([n["turn"] for n in nodes]) if nodes else 1
    marks = {i: str(i) for i in range(0, max_t + 1) if i % 10 == 0 or i == max_t}

    return processed, max_t, marks
