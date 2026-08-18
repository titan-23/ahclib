import json
import os
from collections import deque
from typing import Any


def compute_tree_layout(
    root_id: str,
    children_dict: dict[str, list[str]],
    nodes_dict: dict[str, dict[str, Any]],
    MIN_GAP: float = 1.0,
    mutate_children_order: bool = False,
) -> dict[str, float]:
    """Reingold-Tilford に近い方法で木の横位置を計算する

    ``mutate_children_order`` が ``True`` の場合は重い枝が中央に来るよう
    ``children_dict`` の順番を変更する
    """
    minimum_gap = MIN_GAP
    if mutate_children_order:
        effective_children = children_dict
    else:
        effective_children = {
            parent_id: list(child_ids) for parent_id, child_ids in children_dict.items()
        }

    subtree_sizes: dict[str, int] = {}
    postorder_nodes: list[str] = []
    traversal_stack = [(root_id, False)]
    while traversal_stack:
        node_id, processed = traversal_stack.pop()
        if processed:
            child_ids = effective_children.get(node_id, [])
            subtree_sizes[node_id] = 1 + sum(
                subtree_sizes.get(child_id, 1) for child_id in child_ids
            )
            postorder_nodes.append(node_id)
        else:
            traversal_stack.append((node_id, True))
            for child_id in effective_children.get(node_id, []):
                traversal_stack.append((child_id, False))

    for parent_id in list(effective_children.keys()):
        child_ids = effective_children[parent_id]
        if len(child_ids) <= 1:
            continue
        sorted_children = sorted(
            child_ids,
            key=lambda child_id: subtree_sizes.get(child_id, 0),
            reverse=True,
        )
        arranged = deque()
        for i, child_id in enumerate(sorted_children):
            if i % 2 == 0:
                arranged.append(child_id)
            else:
                arranged.appendleft(child_id)
        effective_children[parent_id] = list(arranged)

    node_offsets: dict[str, float] = {}
    left_contours: dict[str, dict[int, float]] = {}
    right_contours: dict[str, dict[int, float]] = {}

    for node_id in postorder_nodes:
        child_ids = effective_children.get(node_id, [])
        depth = nodes_dict[node_id]["turn"] if node_id in nodes_dict else 0

        if not child_ids:
            node_offsets[node_id] = 0.0
            left_contours[node_id] = {depth: 0.0}
            right_contours[node_id] = {depth: 0.0}
            continue

        first_child = child_ids[0]
        merged_left = dict(left_contours[first_child])
        merged_right = dict(right_contours[first_child])

        child_shifts = [0.0]

        for i in range(1, len(child_ids)):
            child_id = child_ids[i]
            child_left = left_contours[child_id]
            child_right = right_contours[child_id]

            shift = 0.0
            if len(child_left) < len(merged_right):
                for contour_depth, left_position in child_left.items():
                    right_position = merged_right.get(contour_depth)
                    if right_position is not None:
                        required_shift = right_position - left_position + minimum_gap
                        if required_shift > shift:
                            shift = required_shift
            else:
                for contour_depth, right_position in merged_right.items():
                    left_position = child_left.get(contour_depth)
                    if left_position is not None:
                        required_shift = right_position - left_position + minimum_gap
                        if required_shift > shift:
                            shift = required_shift

            child_shifts.append(shift)

            for contour_depth, position in child_left.items():
                shifted_position = position + shift
                current_position = merged_left.get(contour_depth)
                if current_position is None or shifted_position < current_position:
                    merged_left[contour_depth] = shifted_position

            for contour_depth, position in child_right.items():
                shifted_position = position + shift
                current_position = merged_right.get(contour_depth)
                if current_position is None or shifted_position > current_position:
                    merged_right[contour_depth] = shifted_position

        for child_id in child_ids:
            left_contours.pop(child_id, None)
            right_contours.pop(child_id, None)

        parent_position = (child_shifts[0] + child_shifts[-1]) / 2.0

        for i, child_id in enumerate(child_ids):
            node_offsets[child_id] = child_shifts[i] - parent_position

        if parent_position != 0.0:
            for contour_depth in merged_left:
                merged_left[contour_depth] -= parent_position
            for contour_depth in merged_right:
                merged_right[contour_depth] -= parent_position

        current_left = merged_left.get(depth)
        if current_left is None or 0.0 < current_left:
            merged_left[depth] = 0.0
        current_right = merged_right.get(depth)
        if current_right is None or 0.0 > current_right:
            merged_right[depth] = 0.0

        left_contours[node_id] = merged_left
        right_contours[node_id] = merged_right

    left_contours.clear()
    right_contours.clear()

    positions: dict[str, float] = {}
    position_stack = [(root_id, 0.0)]
    while position_stack:
        node_id, current_position = position_stack.pop()
        positions[node_id] = current_position
        for child_id in effective_children.get(node_id, []):
            child_position = current_position + node_offsets.get(child_id, 0.0)
            position_stack.append((child_id, child_position))

    return positions


def compute_compact_layout(
    active_set: set[str],
    children_dict_full: dict[str, list[str]],
    nodes_dict: dict[str, dict[str, Any]],
    root_id: str = "-1",
) -> dict[str, float]:
    """active_set に含まれるノードだけで木の横位置を計算する"""
    active_children: dict[str, list[str]] = {}

    root_children = children_dict_full.get(root_id)
    if root_children:
        filtered_children = [
            child_id for child_id in root_children if child_id in active_set
        ]
        if filtered_children:
            active_children[root_id] = filtered_children

    for parent_id in active_set:
        child_ids = children_dict_full.get(parent_id)
        if not child_ids:
            continue
        filtered_children = [
            child_id for child_id in child_ids if child_id in active_set
        ]
        if filtered_children:
            active_children[parent_id] = filtered_children

    return compute_tree_layout(
        root_id,
        active_children,
        nodes_dict,
        mutate_children_order=True,
    )


def load_and_process_data(
    filepath: str = "history.json",
) -> tuple[dict[str, Any], int, dict[int, str]]:
    """探索履歴を読み込み、描画と集計に使うデータへ変換する"""
    if not os.path.exists(filepath):
        return {"current_data": {}}, 1, {0: "0"}

    with open(filepath, "r", encoding="utf-8") as history_file:
        raw_data = json.load(history_file)

    if "nodes" not in raw_data:
        infinite_score = raw_data.get("INF", 1e18)
        parent_ids = raw_data.get("parent_ids", [])
        scores = raw_data.get("scores", [])
        actions = raw_data.get("actions", [])
        hashes = raw_data.get("hashes", [])
        statuses = raw_data.get("statuses", [])
        turn_starts = raw_data.get("turn_start_indices", [])
        answer_indices = set(raw_data.get("answer_indices", []))
        state_infos = raw_data.get("state_infos", {})

        node_count = len(parent_ids)
        nodes = []

        turn_index = 0
        turn_count = len(turn_starts)
        turns = [0] * node_count
        for i in range(node_count):
            if turn_index + 1 < turn_count and i >= turn_starts[turn_index + 1]:
                turn_index += 1
            turns[i] = turn_index + 1

        active_nodes_by_turn: dict[int, list[int]] = {}
        for i in range(node_count):
            turn = turns[i]
            status = statuses[i]
            nodes.append(
                {
                    "node_id": i,
                    "parent_id": parent_ids[i],
                    "turn": turn,
                    "score": scores[i],
                    "hash": hashes[i],
                    "action": actions[i],
                    "state_info": state_infos.get(str(i), {}),
                    "status": status,
                    "is_answer": i in answer_indices,
                }
            )
            if status == 0:
                if turn not in active_nodes_by_turn:
                    active_nodes_by_turn[turn] = []
                active_nodes_by_turn[turn].append(i)

        snapshots = [
            {"turn": turn, "active_node_ids": active_node_ids}
            for turn, active_node_ids in active_nodes_by_turn.items()
        ]

        history_data = {
            "INF": infinite_score,
            "nodes": nodes,
            "snapshots": snapshots,
        }
    else:
        history_data = raw_data

    nodes = history_data.get("nodes", [])
    infinite_score = history_data.get("INF", 1e18)

    nodes_by_id = {str(node["node_id"]): node for node in nodes}

    # vis_beam.py が描画するデータも重複を除いた内容に差し替える
    history_data["nodes"] = list(nodes_by_id.values())

    children_by_parent: dict[str, list[str]] = {}
    for node_id, node in nodes_by_id.items():
        parent_id = str(node["parent_id"])
        if parent_id not in children_by_parent:
            children_by_parent[parent_id] = []
        children_by_parent[parent_id].append(node_id)

    turn_statistics: dict[int, dict[str, Any]] = {}
    for node in nodes_by_id.values():
        turn = node["turn"]
        score = node["score"]
        status = node.get("status", 0)

        if turn not in turn_statistics:
            turn_statistics[turn] = {
                "scores": [],
                "generated": 0,
                "invalid": 0,
                "pruned": 0,
                "unique_parents": 0,
            }

        turn_statistics[turn]["generated"] += 1

        if status == 2:
            turn_statistics[turn]["invalid"] += 1
        elif score >= infinite_score or status == 1:
            turn_statistics[turn]["pruned"] += 1
        else:
            turn_statistics[turn]["scores"].append(score)

    snapshots_by_turn = {
        snapshot["turn"]: {
            "active": snapshot["active_node_ids"],
            "threshold": snapshot.get("threshold", infinite_score),
        }
        for snapshot in history_data.get("snapshots", [])
    }

    # 生存中のノードが持つ親の種類数を計算する
    for turn, snapshot in snapshots_by_turn.items():
        active_ids = snapshot["active"]
        parents = set()
        for active_id in active_ids:
            active_node_id = str(active_id)
            if active_node_id in nodes_by_id:
                parents.add(nodes_by_id[active_node_id]["parent_id"])
        if turn in turn_statistics:
            turn_statistics[turn]["unique_parents"] = len(parents)

    for turn, snapshot in snapshots_by_turn.items():
        active_ids = snapshot["active"]
        parents = set()
        valid_active_ids = []

        for active_id in active_ids:
            active_node_id = str(active_id)
            if active_node_id in nodes_by_id:
                parents.add(nodes_by_id[active_node_id]["parent_id"])
                node_data = nodes_by_id[active_node_id]
                if node_data["score"] < infinite_score and node_data.get(
                    "status", 0
                ) not in (1, 2):
                    valid_active_ids.append(active_node_id)

        if turn in turn_statistics:
            turn_statistics[turn]["unique_parents"] = len(parents)

            paths = []
            for node_id in valid_active_ids:
                path = []
                current_node_id = node_id
                while current_node_id != "-1" and current_node_id in nodes_by_id:
                    path.append(current_node_id)
                    current_node_id = str(nodes_by_id[current_node_id]["parent_id"])
                path.append("-1")
                paths.append(path[::-1])

            common_count = 0
            if paths:
                minimum_length = min(len(path) for path in paths)
                for i in range(minimum_length):
                    if all(path[i] == paths[0][i] for path in paths):
                        common_count += 1
                    else:
                        break

            turn_statistics[turn]["common_ancestor_depth"] = (
                max(0, common_count - 1) if paths else 0
            )

    valid_scores = [
        node["score"]
        for node in history_data["nodes"]
        if node["score"] < infinite_score
    ]

    for statistics in turn_statistics.values():
        turn_scores = statistics["scores"]
        count = len(turn_scores)
        if count > 0:
            statistics["count"] = count
            statistics["min"] = min(turn_scores)
            statistics["max"] = max(turn_scores)
            statistics["mean"] = sum(turn_scores) / count
        else:
            statistics["count"] = 0
            statistics["min"] = 0
            statistics["max"] = 0
            statistics["mean"] = 0

    positions = compute_tree_layout(
        "-1",
        children_by_parent,
        nodes_by_id,
        mutate_children_order=True,
    )

    for node_id in nodes_by_id:
        if node_id not in positions:
            positions[node_id] = 0.0

    base_positions = {
        "-1": {
            "depth": 0,
            "breadth_center": positions.get("-1", 0.0),
        }
    }

    for node_id, node in nodes_by_id.items():
        base_positions[node_id] = {
            "depth": node["turn"],
            "breadth_center": positions.get(node_id, 0.0),
        }

    processed = {
        "current_data": history_data,
        "nodes_dict": nodes_by_id,
        "children_dict": children_by_parent,
        "snapshots_dict": snapshots_by_turn,
        "valid_scores": valid_scores,
        "turn_stats": turn_statistics,
        "base_positions": base_positions,
    }

    max_turn = max([node["turn"] for node in nodes]) if nodes else 1
    marks = {
        turn: str(turn)
        for turn in range(0, max_turn + 1)
        if turn % 10 == 0 or turn == max_turn
    }

    return processed, max_turn, marks
