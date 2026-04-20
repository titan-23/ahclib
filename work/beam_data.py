import json
import os
import math
from collections import deque


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

    # 1. 各ノードのサブツリーの大きさを事前計算
    subtree_size = {}

    def get_subtree_size(nid):
        if nid in subtree_size:
            return subtree_size[nid]
        kids = children_dict.get(nid, [])
        size = 1 + sum((get_subtree_size(k) for k in kids))
        subtree_size[nid] = size
        return size

    get_subtree_size("-1")

    # 2. 子ノードの順序を最適化（重い枝を中央、軽い枝を外側に配置）
    for pdx, pid in enumerate(children_dict):
        kids = children_dict[pid]
        if not kids:
            continue
        kids.sort(key=lambda k: subtree_size.get(k, 0), reverse=True)
        arranged = deque()
        for i, k in enumerate(kids):
            if i % 2 == 0:
                arranged.append(k)
            else:
                arranged.appendleft(k)
        children_dict[pid] = list(arranged)

    MIN_GAP = 1.0

    def layout_subtree(nid):
        kids = children_dict.get(nid, [])
        depth = nodes_dict[nid]["turn"] if nid in nodes_dict else 0

        if not kids:
            return {nid: 0.0}, {depth: 0.0}, {depth: 0.0}

        child_layouts = [layout_subtree(k) for k in kids]

        merged_pos, left_contour, right_contour = child_layouts[0]

        for i in range(1, len(kids)):
            curr_pos, curr_left, curr_right = child_layouts[i]

            shift = 0.0
            for d in right_contour:
                if d in curr_left:
                    req = right_contour[d] - curr_left[d] + MIN_GAP
                    if req > shift:
                        shift = req

            for k in curr_pos:
                merged_pos[k] = curr_pos[k] + shift

            for d, val in curr_left.items():
                shifted_val = val + shift
                if d not in left_contour or shifted_val < left_contour[d]:
                    left_contour[d] = shifted_val

            for d, val in curr_right.items():
                shifted_val = val + shift
                if d not in right_contour or shifted_val > right_contour[d]:
                    right_contour[d] = shifted_val

        # # 3. 親の位置は、「両端の子の中央」に配置（平均値による偏りを排除）
        kid_centers = [merged_pos[k] for k in kids]
        parent_x = (kid_centers[0] + kid_centers[-1]) / 2.0
        merged_pos[nid] = parent_x

        if depth not in left_contour or parent_x < left_contour[depth]:
            left_contour[depth] = parent_x
        if depth not in right_contour or parent_x > right_contour[depth]:
            right_contour[depth] = parent_x

        return merged_pos, left_contour, right_contour

    # ルートから一括で計算を実行
    positions, _, _ = layout_subtree("-1")

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
