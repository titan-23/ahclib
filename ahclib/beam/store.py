from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Generic, Optional, TypeVar

from dash.development.base_component import Component

Key = TypeVar("Key")
Value = TypeVar("Value")


class LRUCache(Generic[Key, Value]):
    """件数と重みの上限を持つ LRU cache"""

    def __init__(
        self,
        max_entries: int,
        *,
        max_weight: Optional[int] = None,
        get_weight: Optional[Callable[[Value], int]] = None,
    ) -> None:
        self.max_entries = max_entries
        self.max_weight = max_weight
        self.get_weight = get_weight or (lambda _: 1)
        self._values: OrderedDict[Key, tuple[Value, int]] = OrderedDict()
        self._total_weight = 0
        self._lock = RLock()

    def get(self, key: Key, default: Optional[Value] = None) -> Optional[Value]:
        with self._lock:
            cached = self._values.pop(key, None)
            if cached is None:
                return default
            self._values[key] = cached
            return cached[0]

    def __setitem__(self, key: Key, value: Value) -> None:
        weight = max(0, self.get_weight(value))
        with self._lock:
            previous = self._values.pop(key, None)
            if previous is not None:
                self._total_weight -= previous[1]
            self._values[key] = (value, weight)
            self._total_weight += weight
            while len(self._values) > self.max_entries or (
                self.max_weight is not None and self._total_weight > self.max_weight
            ):
                _, (_, removed_weight) = self._values.popitem(last=False)
                self._total_weight -= removed_weight

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._total_weight = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


@dataclass(frozen=True)
class PathData:
    node_ids: tuple[str, ...]
    action_sequence: str
    node_selector: str
    edge_selector: str


@dataclass(frozen=True)
class SubtreeData:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    node_selector: str
    edge_selector: str


@dataclass
class BeamStore:
    """1 つの vis_beam app が使う履歴と cache を保持する"""

    history_path: str
    generate_board_visual: Callable[[str], Component]
    processed: dict[str, Any] = field(default_factory=dict)
    max_turn: int = 1
    file_signature: Optional[tuple[int, int]] = None
    elements_cache: LRUCache[tuple[Any, ...], list[dict[str, Any]]] = field(
        default_factory=lambda: LRUCache(
            64,
            max_weight=1_000_000,
            get_weight=len,
        )
    )
    active_path_cache: LRUCache[int, set[str]] = field(
        default_factory=lambda: LRUCache(128, max_weight=500_000, get_weight=len)
    )
    compact_layout_cache: LRUCache[int, dict[str, dict[str, float]]] = field(
        default_factory=lambda: LRUCache(64, max_weight=500_000, get_weight=len)
    )
    board_cache: LRUCache[str, Component] = field(default_factory=lambda: LRUCache(32))
    path_cache: LRUCache[str, PathData] = field(
        default_factory=lambda: LRUCache(
            512,
            max_weight=200_000,
            get_weight=lambda value: len(value.node_ids),
        )
    )
    subtree_cache: LRUCache[str, SubtreeData] = field(
        default_factory=lambda: LRUCache(
            128,
            max_weight=1_000_000,
            get_weight=lambda value: len(value.node_ids) + len(value.edge_ids),
        )
    )
    all_graph_cache: LRUCache[tuple[int, int], Any] = field(default_factory=lambda: LRUCache(16))
    turn_stats_content: Any = None

    def replace(
        self,
        processed: dict[str, Any],
        max_turn: int,
        file_signature: Optional[tuple[int, int]],
    ) -> None:
        """履歴を差し替え、古い履歴に依存する cache を消す"""
        self.processed = processed
        self.max_turn = max_turn
        self.file_signature = file_signature
        self.elements_cache.clear()
        self.active_path_cache.clear()
        self.compact_layout_cache.clear()
        self.board_cache.clear()
        self.path_cache.clear()
        self.subtree_cache.clear()
        self.all_graph_cache.clear()
        self.turn_stats_content = None

    def node_path(self, node_id: str) -> PathData:
        """対象 node から根までの ID と操作列を返す"""
        cached = self.path_cache.get(node_id)
        if cached is not None:
            return cached

        nodes_by_id = self.processed.get("nodes_dict", {})
        path_ids = []
        current_id = node_id
        while current_id != "-1" and current_id in nodes_by_id:
            path_ids.append(current_id)
            current_id = nodes_by_id[current_id]["spid"]
        path_ids.append("-1")
        action_sequence = "".join(
            nodes_by_id[path_id].get("action", "") for path_id in reversed(path_ids) if path_id in nodes_by_id
        )
        edge_ids = [f"e{path_ids[i + 1]}_{path_ids[i]}" for i in range(len(path_ids) - 1)]
        result = PathData(
            node_ids=tuple(path_ids),
            action_sequence=action_sequence,
            node_selector=",".join(f'node[id="{path_id}"]' for path_id in path_ids),
            edge_selector=",".join(f'edge[id="{edge_id}"]' for edge_id in edge_ids),
        )
        self.path_cache[node_id] = result
        return result

    def subtree(self, node_id: str) -> SubtreeData:
        """対象 node を除く子孫 ID と子孫へ向かう edge ID を返す"""
        cached = self.subtree_cache.get(node_id)
        if cached is not None:
            return cached

        children_by_parent = self.processed.get("children_dict", {})
        subtree_node_ids = []
        subtree_edge_ids = []
        stack = [node_id]
        while stack:
            current_id = stack.pop()
            if current_id != node_id:
                subtree_node_ids.append(current_id)
            for child_id in children_by_parent.get(current_id, []):
                subtree_edge_ids.append(f"e{current_id}_{child_id}")
                stack.append(child_id)

        result = SubtreeData(
            node_ids=tuple(subtree_node_ids),
            edge_ids=tuple(subtree_edge_ids),
            node_selector=",".join(f'node[id="{descendant_id}"]' for descendant_id in subtree_node_ids),
            edge_selector=",".join(f'edge[id="{edge_id}"]' for edge_id in subtree_edge_ids),
        )
        self.subtree_cache[node_id] = result
        return result
