import json
import os
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

    nodes_dict = {str(n["node_id"]): n for n in nodes}
    data["nodes"] = list(nodes_dict.values())

    children_dict = {}
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

    for t, snapshot in snapshots_dict.items():
        active_ids = snapshot["active"]
        parents = set()
        valid_active_ids = []

        for active_id in active_ids:
            active_nid = str(active_id)
            if active_nid in nodes_dict:
                parents.add(nodes_dict[active_nid]["parent_id"])
                node_data = nodes_dict[active_nid]
                if node_data["score"] < inf_val and node_data.get("status", 0) not in (1, 2):
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

    subtree_size = {}

    def get_subtree_size(nid):
        if nid in subtree_size:
            return subtree_size[nid]
        kids = children_dict.get(nid, [])
        size = 1 + sum((get_subtree_size(k) for k in kids))
        subtree_size[nid] = size
        return size

    get_subtree_size("-1")

    for pid in children_dict:
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
    node_offsets = {}

    def calculate_layout_pass1(nid):
        kids = children_dict.get(nid, [])
        depth = nodes_dict[nid]["turn"] if nid in nodes_dict else 0

        if not kids:
            node_offsets[nid] = 0.0
            return {depth: 0.0}, {depth: 0.0}

        c_left_0, c_right_0 = calculate_layout_pass1(kids[0])
        left_contour = dict(c_left_0)
        right_contour = dict(c_right_0)

        kid_shifts = [0.0]

        for i in range(1, len(kids)):
            c_left, c_right = calculate_layout_pass1(kids[i])

            shift = 0.0
            for d in right_contour:
                if d in c_left:
                    req = right_contour[d] - c_left[d] + MIN_GAP
                    if req > shift:
                        shift = req

            kid_shifts.append(shift)

            for d, val in c_left.items():
                shifted_val = val + shift
                if d not in left_contour or shifted_val < left_contour[d]:
                    left_contour[d] = shifted_val

            for d, val in c_right.items():
                shifted_val = val + shift
                if d not in right_contour or shifted_val > right_contour[d]:
                    right_contour[d] = shifted_val

        parent_x = (kid_shifts[0] + kid_shifts[-1]) / 2.0

        for i, child in enumerate(kids):
            node_offsets[child] = kid_shifts[i] - parent_x

        left_contour = {d: v - parent_x for d, v in left_contour.items()}
        right_contour = {d: v - parent_x for d, v in right_contour.items()}

        if depth not in left_contour or 0.0 < left_contour[depth]:
            left_contour[depth] = 0.0
        if depth not in right_contour or 0.0 > right_contour[depth]:
            right_contour[depth] = 0.0

        return left_contour, right_contour

    calculate_layout_pass1("-1")

    positions = {}

    def calculate_layout_pass2(nid, current_x):
        positions[nid] = current_x
        for child in children_dict.get(nid, []):
            child_x = current_x + node_offsets.get(child, 0.0)
            calculate_layout_pass2(child, child_x)

    calculate_layout_pass2("-1", 0.0)

    for nid in nodes_dict:
        if nid not in positions:
            positions[nid] = 0.0

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

    nodes_sorted = sorted(nodes, key=lambda x: x.get("turn", 0))

    processed = {
        "current_data": data,
        "nodes_dict": nodes_dict,
        "children_dict": children_dict,
        "snapshots_dict": snapshots_dict,
        "valid_scores": valid_scores,
        "turn_stats": turn_stats,
        "base_positions": base_positions,
        "nodes_sorted": nodes_sorted,
    }

    max_t = max([n["turn"] for n in nodes]) if nodes else 1
    marks = {i: str(i) for i in range(0, max_t + 1) if i % 10 == 0 or i == max_t}

    return processed, max_t, marks
