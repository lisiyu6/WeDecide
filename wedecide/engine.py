"""Deterministic one-day, one/two-activity constraint and utility engine."""
from itertools import permutations
from statistics import mean
from .store import new_id


def active_members(room):
    return [m for m in room["members"] if m["status"] == "approved"]


def evaluate(room, itinerary, fairness=None, members=None):
    members = members if members is not None else active_members(room)
    rules = room["rules"]
    resources = [item["resource"] for item in itinerary]
    count = len(members)
    transfers = max(0, len(resources) - 1)
    known_cost = all(r["cost"] is not None for r in resources)
    cost = (sum(r["cost"] + r["fixed_cost"] / max(1, count) for r in resources) + transfers * rules["transfer_cost"]) if known_cost else None
    upper = (sum((r["cost_upper"] if r["cost_upper"] is not None else r["cost"]) + r["fixed_cost"] / max(1, count) for r in resources) + transfers * rules["transfer_cost"]) if known_cost else None
    start, end = itinerary[0]["start"], itinerary[-1]["end"]
    violations, unknown = [], []
    if not count:
        unknown.append("尚无有效成员")
    if not known_cost:
        unknown.append("候选活动缺少费用")
    if any(not r["confirmed"] for r in resources):
        unknown.append("候选数据尚未由房主确认")
    for item in itinerary:
        if item["start"] < item["resource"]["start"] or item["end"] > item["resource"]["end"]:
            violations.append({"member_id": None, "field": "opening", "message": "行程超出候选活动开放时间"})
    utilities = []
    for m in members:
        p = m.get("preference")
        if not p or not m.get("confirmed"):
            unknown.append("存在未确认的成员需求")
            continue
        def fail(field, message):
            violations.append({"member_id": m["id"], "field": field, "message": message})
        if p["budget_max"] is not None and upper is not None and upper > p["budget_max"] + 0.00001:
            fail("budget_max", "超出一位成员确认的预算上限")
        if start < p["available_start"] or end > p["available_end"]:
            fail("availability", "不在一位成员可参加的时间窗口内")
        if any(r["category"] in p["excluded_categories"] for r in resources):
            fail("excluded_categories", "包含一位成员明确排除的活动类别")
        if p["max_duration"] is not None and end - start > p["max_duration"]:
            fail("max_duration", "超过一位成员确认的最长时长")
        if p["allowed_locations"]:
            if any(not r["location"] for r in resources):
                unknown.append("地点限制无法判断：活动地点缺失")
            elif any(r["location"] not in p["allowed_locations"] for r in resources):
                fail("allowed_locations", "活动地点不满足一位成员的地点限制")
        if p["unresolved"]:
            unknown.append("仍有影响决策的待澄清条件")
        scores = []
        def score(label, value, weight):
            scores.append({"label": label, "score": round(value, 2) if value is not None else None, "weight": weight})
        if p["budget_target"] is not None:
            b = p["budget_target"]
            score("预算", max(0, 100 - 100 * max(0, cost - b) / max(b, 50)) if cost is not None else None, p["budget_weight"])
        if p["preferred_start"] is not None:
            score("开始时间", max(0, 100 - max(0, p["preferred_start"] - start) / 60 * 20), p["time_weight"])
        if p["preferred_end"] is not None:
            score("结束时间", max(0, 100 - max(0, end - p["preferred_end"]) / 60 * 20), p["time_weight"])
        if p["categories"]:
            ratings = [(p["categories"].get(r["category"]), r["duration"]) for r in resources]
            rated = [(v, d) for v, d in ratings if v is not None]
            # Missing positive/neutral categories stay unknown. Avoiding all disliked
            # categories satisfies a solely negative category preference.
            if not rated and all(v == 0 for v in p["categories"].values()):
                score("活动类别", 100, p["activity_weight"])
            elif len(rated) == len(ratings):
                score("活动类别", sum(v * d for v, d in rated) / sum(d for _, d in rated), p["activity_weight"])
            else:
                score("活动类别", None, p["activity_weight"])
        if p["other"]:
            score("其他主观要求（未评分）", None, 3)
        valid = [s for s in scores if s["score"] is not None]
        utility = sum(s["score"] * s["weight"] for s in valid) / sum(s["weight"] for s in valid) if valid else None
        utilities.append({"member_id": m["id"], "score": round(utility, 2) if utility is not None else None, "dimensions": scores, "coverage": [len(valid), len(scores)]})
    numbers = [u["score"] for u in utilities if u["score"] is not None]
    avg, minimum = (mean(numbers), min(numbers)) if numbers else (None, None)
    weight = rules["fairness"] if fairness is None else fairness
    group = (1 - weight) * avg + weight * minimum if numbers else None
    return {"status": "INFEASIBLE" if violations else "UNKNOWN" if unknown else "FEASIBLE", "violations": violations, "unknown": list(dict.fromkeys(unknown)), "cost": round(cost, 2) if cost is not None else None, "cost_upper": round(upper, 2) if upper is not None else None, "start": start, "end": end, "utilities": utilities, "average": round(avg, 2) if avg is not None else None, "minimum": round(minimum, 2) if minimum is not None else None, "score": round(group, 2) if group is not None else None, "coverage": [len(numbers), count], "partial": len(numbers) != count or any(u["coverage"][0] < u["coverage"][1] for u in utilities), "source_status": "VERIFIED_BY_ORGANIZER" if all(r["verified"] for r in resources) else "USER_PROVIDED" if all(r["confirmed"] for r in resources) else "UNCONFIRMED"}


def rank_key(proposal):
    e = proposal["evaluation"]
    return ({"FEASIBLE": 0, "UNKNOWN": 1, "INFEASIBLE": 2}[e["status"]], -(e["score"] if e["score"] is not None else -1), len(e["violations"]), e["cost_upper"] if e["cost_upper"] is not None else float("inf"), e["start"])


def generate(room):
    resources, members = room["resources"], active_members(room)
    rules = room["rules"]
    prefs = [m["preference"] for m in members if m.get("preference")]
    hard_start = max((p["available_start"] for p in prefs), default=0)
    candidates = []
    considered = 0
    for length in range(1, min(len(resources), rules["max_activities"]) + 1):
        for sequence in permutations(resources, length):
            duration = sum(r["duration"] for r in sequence) + (length - 1) * rules["transfer_minutes"]
            starts = {sequence[0]["start"], max(sequence[0]["start"], hard_start)}
            for p in prefs:
                if p["preferred_start"] is not None:
                    starts.add(max(sequence[0]["start"], hard_start, p["preferred_start"]))
                if p["preferred_end"] is not None:
                    starts.add(max(sequence[0]["start"], hard_start, p["preferred_end"] - duration))
            # Align the first activity to later activities' opening times to avoid
            # artificial idle time causing duration/time constraints to fail.
            offset = 0
            for resource in sequence:
                starts.add(max(sequence[0]["start"], hard_start, resource["start"] - offset))
                offset += resource["duration"] + rules["transfer_minutes"]
            best = None
            for start in sorted(starts):
                itinerary, cursor = [], start
                for resource in sequence:
                    cursor = max(cursor, resource["start"])
                    itinerary.append({"resource": resource, "start": cursor, "end": cursor + resource["duration"]})
                    cursor += resource["duration"] + rules["transfer_minutes"]
                if itinerary[-1]["end"] > 1440:
                    continue
                considered += 1
                proposal = {"title": " + ".join(r["name"] for r in sequence), "itinerary": itinerary, "evaluation": evaluate(room, itinerary)}
                if best is None or rank_key(proposal) < rank_key(best):
                    best = proposal
            if best:
                candidates.append(best)
    candidates.sort(key=rank_key)
    chosen, seen = [], set()
    for p in candidates:
        signature = tuple(sorted(i["resource"]["id"] for i in p["itinerary"]))
        if signature in seen:
            continue
        seen.add(signature)
        p.update(id=new_id(), version=room["analysis_version"] + 1, input_version=room["input_version"])
        chosen.append(p)
        if len(chosen) == 3:
            break
    return {"proposals": chosen, "considered": considered, "resource_combinations": len(candidates), "scope": f"单日 1–{rules['max_activities']} 项活动；在开放时间、共同可用时间和偏好时间边界安排，未搜索任意多活动行程", "feasible_count": sum(p["evaluation"]["status"] == "FEASIBLE" for p in candidates)}


def demo_resources():
    from .models import Resource
    options = [("城市公园漫步", "户外", "城市公园", 0, 90, 540, 1080), ("美术馆看展", "文化", "市美术馆", 30, 120, 600, 1020), ("桌游与下午茶", "室内", "桌游空间", 58, 120, 720, 1320), ("一起吃晚餐", "美食", "街区餐厅", 65, 90, 1020, 1320), ("湖畔骑行", "运动", "城市公园", 35, 120, 540, 1080)]
    return [Resource(id=new_id(), name=n, category=c, location=l, cost=cost, start=s, end=e, duration=d, source="演示数据，非真实报价", confirmed=True).model_dump() for n, c, l, cost, d, s, e in options]
