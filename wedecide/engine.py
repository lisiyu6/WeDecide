"""Bounded one-day planning with explicit hard constraints and soft preferences."""
from statistics import mean
from .store import new_id


def active_members(room):
    return [m for m in room["members"] if m["status"] == "approved"]


def attribute_match(resources, criterion):
    expected = criterion.get("rating", 100) != 0
    values = []
    for resource in resources:
        attributes = {key.casefold(): value for key, value in resource.get("attributes", {}).items()}
        actual = attributes.get(criterion["name"].casefold())
        values.append(None if actual is None else actual == expected)
    if criterion.get("scope", "any") == "all":
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def evaluate_decision(room, option, fairness=None, members=None):
    members = members if members is not None else active_members(room)
    count = len(members)
    cost = None if option["cost"] is None else option["cost"] + option["fixed_cost"] / max(1, count)
    upper = None if cost is None else (option["cost_upper"] if option["cost_upper"] is not None else option["cost"]) + option["fixed_cost"] / max(1, count)
    violations, unknown, utilities = [], [], []
    if not option["confirmed"]:
        unknown.append("方案事实尚未由房主核对")
    for member in members:
        preference = member.get("preference")
        if not preference or not member.get("confirmed"):
            unknown.append("存在未确认的成员需求")
            continue
        dimensions = []
        if preference["allowed_locations"]:
            if not option["location"]:
                unknown.append("通用备选缺少地点，无法核对一位成员的必要地点要求")
            elif option["location"] not in preference["allowed_locations"]:
                violations.append({"member_id":member["id"],"field":"allowed_locations","message":"不满足一位成员的必要地点要求"})
        if preference["available_start"] != 0 or preference["available_end"] != 1440 or preference["max_duration"] is not None:
            unknown.append("通用备选未提供活动行程，无法核对一位成员的必要时间或时长要求")
        if preference["budget_max"] is not None:
            if upper is None:
                unknown.append("方案缺少费用，无法判断一位成员的必要预算")
            elif upper > preference["budget_max"]:
                violations.append({"member_id": member["id"], "field": "budget_max", "message": "超出一位成员确认的预算上限"})
        if preference["budget_target"] is not None or preference.get("cost_preference") == "lower":
            target = preference["budget_target"]
            known = [r["cost"] for r in room["resources"] if r["cost"] is not None]
            scale = max(1, mean(known)) if known else 1
            value = None if cost is None else max(0, 100 - 100 * max(0, cost-target) / max(target, 50)) if target is not None else 100 * scale / (scale + cost)
            dimensions.append({"label": "费用偏好", "score": value, "weight": preference["budget_weight"]})
        if option["category"] in preference["excluded_categories"]:
            violations.append({"member_id": member["id"], "field": "excluded_categories", "message": "属于一位成员明确排除的类别"})
        if option["category"] in preference["categories"]:
            dimensions.append({"label": "类别偏好", "score": preference["categories"][option["category"]], "weight": preference["activity_weight"]})
        for criterion in preference.get("criteria", []):
            matched = attribute_match([option], criterion)
            value = None if matched is None else 50 if criterion.get("rating") == 50 else 100 if matched else 0
            if criterion.get("hard"):
                if matched is None:
                    unknown.append("一位成员的必要要求缺少方案事实依据")
                elif matched is False:
                    violations.append({"member_id": member["id"], "field": "criteria", "message": "不满足一位成员明确确认的必要属性要求"})
            dimensions.append({"label": criterion["name"], "score": value, "weight": criterion.get("weight",3)})
        if preference["other"]:
            dimensions.append({"label": "原话与主观要求（由 AI 解释，未强行量化）", "score": None, "weight": 3})
        valid = [dimension for dimension in dimensions if dimension["score"] is not None]
        utility = sum(d["score"]*d["weight"] for d in valid)/sum(d["weight"] for d in valid) if valid else None
        utilities.append({"member_id": member["id"], "score": round(utility,2) if utility is not None else None, "dimensions": dimensions, "coverage": [len(valid),len(dimensions)]})
    numbers = [utility["score"] for utility in utilities if utility["score"] is not None]
    average, minimum = (mean(numbers),min(numbers)) if numbers else (None,None)
    weight = room["rules"]["fairness"] if fairness is None else fairness
    score = None if average is None else (1-weight)*average+weight*minimum
    return {"kind":"decision", "status":"INFEASIBLE" if violations else "UNKNOWN" if unknown else "FEASIBLE", "violations":violations, "unknown":list(dict.fromkeys(unknown)), "cost":round(cost,2) if cost is not None else None, "cost_upper":round(upper,2) if upper is not None else None, "start":None,"end":None,"duration":None,"transfers":0,"wait_minutes":0,"utilities":utilities,"average":average,"minimum":minimum,"score":score,"coverage":[len(numbers),count],"partial":len(numbers)!=count or any(u["coverage"][0]<u["coverage"][1] for u in utilities),"source_status":"VERIFIED_BY_ORGANIZER" if option["verified"] else "USER_PROVIDED" if option["confirmed"] else "UNCONFIRMED","cost_breakdown":{"activities":option["cost"],"shared":option["fixed_cost"]/max(1,count),"transfer":0,"people":count}}


def evaluate(room, itinerary, fairness=None, members=None):
    if len(itinerary) == 1 and itinerary[0]["resource"].get("kind") == "decision":
        return evaluate_decision(room, itinerary[0]["resource"], fairness, members)
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
    if any(resource.get("kind") == "decision" for resource in resources):
        violations.append({"member_id":None,"field":"kind","message":"通用备选方案应独立比较，不能拼成活动行程"})
    if not room["scenario"].get("city", "").strip():
        unknown.append("活动城市尚未确认")
    if not room["scenario"].get("date"):
        unknown.append("活动日期尚未确认")
    if not count:
        unknown.append("尚无有效成员")
    if not known_cost:
        unknown.append("候选活动缺少费用")
    if any(not r["confirmed"] for r in resources):
        unknown.append("候选数据尚未由房主确认")
    if not rules.get("min_activities", 1) <= len(resources) <= rules["max_activities"]:
        violations.append({"member_id": None, "field": "activities", "message": "活动数量不在房间设置的范围内"})
    if end > 1440:
        violations.append({"member_id": None, "field": "day", "message": "行程超出同一天的时间范围"})
    for previous, following in zip(itinerary, itinerary[1:]):
        if following["start"] < previous["end"] + rules["transfer_minutes"]:
            violations.append({"member_id": None, "field": "transfer", "message": "活动重叠或预留转场时间不足"})
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
        elif p.get("cost_preference") == "lower":
            known = [r["cost"] + r["fixed_cost"] / max(1, count) for r in room["resources"] if r["cost"] is not None]
            scale = max(1, mean(known)) if known else 1
            score("价格（偏好更低费用）", 100 * scale / (scale + cost) if cost is not None else None, p["budget_weight"])
        for criterion in p.get("criteria", []):
            matched = attribute_match(resources, criterion)
            value = None if matched is None else 100 if matched else 0
            if criterion.get("rating", 100) == 50:
                value = 50 if matched is not None else None
            if criterion.get("hard"):
                if matched is False:
                    fail("criteria", "不满足一位成员明确确认的必要属性要求")
                elif matched is None:
                    unknown.append("一位成员的必要属性要求缺少候选资料依据")
            score(criterion["name"], value, criterion.get("weight", 3))
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
    return {"status": "INFEASIBLE" if violations else "UNKNOWN" if unknown else "FEASIBLE", "violations": violations, "unknown": list(dict.fromkeys(unknown)), "cost": round(cost, 2) if cost is not None else None, "cost_upper": round(upper, 2) if upper is not None else None, "start": start, "end": end, "utilities": utilities, "average": round(avg, 2) if avg is not None else None, "minimum": round(minimum, 2) if minimum is not None else None, "score": round(group, 2) if group is not None else None, "coverage": [len(numbers), count], "partial": len(numbers) != count or any(u["coverage"][0] < u["coverage"][1] for u in utilities), "duration": end - start, "transfers": transfers, "wait_minutes": sum(max(0, following["start"] - previous["end"] - rules["transfer_minutes"]) for previous, following in zip(itinerary, itinerary[1:])), "cost_breakdown": {"activities": round(sum(r["cost"] for r in resources), 2) if known_cost else None, "shared": round(sum(r["fixed_cost"] for r in resources) / max(1, count), 2), "transfer": round(transfers * rules["transfer_cost"], 2), "people": count}, "source_status": "VERIFIED_BY_ORGANIZER" if all(r["verified"] for r in resources) else "USER_PROVIDED" if all(r["confirmed"] for r in resources) else "UNCONFIRMED"}


def rank_key(proposal):
    e = proposal["evaluation"]
    return ({"FEASIBLE": 0, "UNKNOWN": 1, "INFEASIBLE": 2}[e["status"]], -(e["score"] if e["score"] is not None else -1), len(e["violations"]), e["cost_upper"] if e["cost_upper"] is not None else float("inf"), (e["start"] or 0))


def generate(room):
    resources, members, rules = [r for r in room["resources"] if r.get("kind", "activity") == "activity"], active_members(room), room["rules"]
    prefs = [m["preference"] for m in members if m.get("preference")]
    hard_start = max((p["available_start"] for p in prefs), default=0)
    candidates, considered, bounded = {}, 0, False
    combinations, feasible_count = 0, 0
    beam = [()]
    max_depth = min(len(resources), rules["max_activities"])
    for length in range(1, max_depth + 1):
        stage, used = [], 0
        for prefix in beam:
            for resource in resources:
                if any(item["id"] == resource["id"] for item in prefix):
                    continue
                sequence = (*prefix, resource)
                duration = sum(r["duration"] for r in sequence) + (length - 1) * rules["transfer_minutes"]
                starts = {sequence[0]["start"], max(sequence[0]["start"], hard_start)}
                for preference in prefs:
                    if preference["preferred_start"] is not None:
                        starts.add(max(sequence[0]["start"], hard_start, preference["preferred_start"]))
                    if preference["preferred_end"] is not None:
                        starts.add(max(sequence[0]["start"], hard_start, preference["preferred_end"] - duration))
                offset = 0
                for item in sequence:
                    starts.add(max(sequence[0]["start"], hard_start, item["start"] - offset))
                    offset += item["duration"] + rules["transfer_minutes"]
                if len(starts) > 12:
                    bounded = True
                best = None
                for start in sorted(starts)[:12]:
                    if used >= 2000:
                        bounded = True
                        break
                    itinerary, cursor = [], start
                    for item in sequence:
                        cursor = max(cursor, item["start"])
                        itinerary.append({"resource": item, "start": cursor, "end": cursor + item["duration"]})
                        cursor += item["duration"] + rules["transfer_minutes"]
                    used += 1
                    considered += 1
                    proposal = {"title": " + ".join(r["name"] for r in sequence), "itinerary": itinerary, "evaluation": evaluate(room, itinerary)}
                    if best is None or rank_key(proposal) < rank_key(best):
                        best = proposal
                if best:
                    combinations += 1
                    stage.append((sequence, best))
                    if len(stage) > 96:
                        stage.sort(key=lambda value: rank_key(value[1]))
                        stage = stage[:48]
                        bounded = True
                    if length >= rules.get("min_activities", 1):
                        feasible_count += best["evaluation"]["status"] == "FEASIBLE"
                        signature = tuple(sorted(item["resource"]["id"] for item in best["itinerary"]))
                        previous = candidates.get(signature)
                        if previous is None or rank_key(best) < rank_key(previous):
                            candidates[signature] = best
                        if len(candidates) > 12:
                            worst = max(candidates, key=lambda key: rank_key(candidates[key]))
                            del candidates[worst]
                if used >= 2000:
                    break
            if used >= 2000:
                break
        stage.sort(key=lambda value: rank_key(value[1]))
        if len(stage) > 48 and length < max_depth:
            bounded = True
        beam = [sequence for sequence, _ in stage[:48]]
    chosen = sorted(candidates.values(), key=rank_key)[:6]
    for option in room["resources"]:
        if option.get("kind") != "decision":
            continue
        proposal = {"kind":"decision", "title":option["name"], "description":option.get("description", ""), "itinerary":[{"resource":option,"start":0,"end":0}], "evaluation":evaluate_decision(room,option)}
        chosen.append(proposal)
        feasible_count += proposal["evaluation"]["status"] == "FEASIBLE"
        combinations += 1
        considered += 1
    by_id = {resource["id"]: resource for resource in resources}
    warnings = []
    for plan in room.get("manual_plans", []):
        if any(step["resource_id"] not in by_id for step in plan["steps"]):
            warnings.append(f"自定义方案「{plan['title']}」引用了已移除的活动，请重新编辑")
            continue
        itinerary = [{"resource": by_id[step["resource_id"]], "start": step["start"], "end": step["start"] + by_id[step["resource_id"]]["duration"]} for step in plan["steps"]]
        proposal = {"title": plan["title"], "description": plan["description"], "plan_id": plan["id"], "itinerary": itinerary, "evaluation": evaluate(room, itinerary)}
        chosen.append(proposal)
        feasible_count += proposal["evaluation"]["status"] == "FEASIBLE"
        combinations += 1
        considered += 1
    chosen.sort(key=rank_key)
    for index, proposal in enumerate(chosen):
        proposal.update(id=new_id(), code=str(index+1) if index>=26 else chr(65 + index), version=room["analysis_version"] + 1, input_version=room["input_version"])
    scope = f"通用备选独立比较；活动工具支持单城市单日，最少 {rules.get('min_activities', 1)}、最多 {rules['max_activities']} 项活动；每层最多 2000 个时间安排、保留 48 条路径，另评价房主自定义行程。有限搜索不保证全局最优。"
    return {"proposals": chosen, "considered": considered, "resource_combinations": combinations, "scope": scope, "bounded": bounded, "warnings": warnings, "feasible_count": feasible_count}


def demo_resources():
    from .models import Resource
    options = [("城市公园漫步", "户外", "城市公园", 0, 90, 540, 1080), ("美术馆看展", "文化", "市美术馆", 30, 120, 600, 1020), ("桌游与下午茶", "室内", "桌游空间", 58, 120, 720, 1320), ("一起吃晚餐", "美食", "街区餐厅", 65, 90, 1020, 1320), ("湖畔骑行", "运动", "城市公园", 35, 120, 540, 1080)]
    return [Resource(id=new_id(), name=n, category=c, location=l, cost=cost, start=s, end=e, duration=d, source="演示数据，非真实报价", confirmed=True).model_dump() for n, c, l, cost, d, s, e in options]
