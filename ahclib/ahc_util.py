import math
from typing import Optional


def to_red(arg: object) -> str:
    return f"\u001b[91m{arg}\u001b[0m"


def to_blue(arg: object) -> str:
    return f"\u001b[94m{arg}\u001b[0m"


def to_green(arg: object) -> str:
    return f"\u001b[92m{arg}\u001b[0m"


def to_bold(arg: object) -> str:
    return f"\u001b[1m{arg}\u001b[0m"


def avg_score(scores: list[Optional[float]]) -> float:
    valid_scores = [score for score in scores if score is not None]
    return sum(valid_scores) / len(valid_scores)


def geo_score(scores: list[Optional[float]]) -> float:
    valid_scores = [score for score in scores if score is not None]
    log_sum = sum(math.log(score) for score in valid_scores)
    return math.exp(log_sum / len(valid_scores))
