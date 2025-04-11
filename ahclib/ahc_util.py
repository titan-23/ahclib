from typing import Optional
import math


def to_red(arg) -> str:
    return f"\u001b[91m{arg}\u001b[0m"


def to_blue(arg) -> str:
    return f"\u001b[94m{arg}\u001b[0m"


def to_green(arg) -> str:
    return f"\u001b[92m{arg}\u001b[0m"


def to_bold(arg) -> str:
    return f"\u001b[1m{arg}\u001b[0m"


def avg_score(scores: list[Optional[float]]) -> float:
    scores = list(filter(lambda x: x is not None, scores))
    return sum(scores) / len(scores)


def geo_score(scores: list[Optional[float]]) -> float:
    scores = list(filter(lambda x: x is not None, scores))
    log_sum = sum(math.log(s) for s in scores)
    return math.exp(log_sum / len(scores))
