"""Local UI tools for the private part of the room's decision agent.

The model chooses a branch and algorithm target. The application owns control
kinds and limits; requesting a control neither answers a question nor saves a
formal preference. JSON tool dispatch also works with custom text-only APIs.
"""
from .models import InterviewInputCall


def input_control(field):
    if field in {"budget_max", "budget_target"}:
        return {"kind": "number", "unit": "元/人", "min": 0, "max": 1000000, "step": 0.01}
    if field == "max_duration":
        return {"kind": "number", "unit": "分钟", "min": 15, "max": 1440, "step": 1}
    if field in {"budget_weight", "time_weight", "activity_weight"}:
        return {"kind": "number", "unit": "", "min": 1, "max": 5, "step": 1}
    if field in {"available_start", "available_end", "preferred_start", "preferred_end"}:
        return {"kind": "time", "unit": "", "allow_midnight_end": field.endswith("end")}
    return {"kind": "text", "unit": "", "max_length": 1000}


def input_tool_contract():
    return {"name": "request_input", "description": "当某个选择需要具体金额、时刻、时长或本人说明时调用。仅在成员选择该分支后展示输入，填完才提交本题；暂未确定/跳过分支不调用。每个选项最多一次，不增加追问张数，不修改正式条件。", "arguments_schema": InterviewInputCall.model_json_schema()}


def dispatch_input_tools(interview):
    if interview["ready"]:
        return {}
    cards = {}
    for call in interview["tool_calls"]:
        if call["field"] not in interview["targets"]:
            raise ValueError("request_input.field 必须属于本题 targets")
        if call["choice"] in cards:
            raise ValueError("同一选项最多调用一次 request_input")
        cards[call["choice"]] = {**input_control(call["field"]), **{key: call[key] for key in ("field", "label", "placeholder")}}
    return cards
