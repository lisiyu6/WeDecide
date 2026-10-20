"""Bounded third-party AI gateway. Credentials and injected context stay server-side."""
import asyncio
from collections import OrderedDict
from difflib import SequenceMatcher
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit
import httpx
from . import store
from .context import calendar_context, visible_supplements
from .interview_tools import dispatch_input_tools, input_tool_contract
from .models import DateResolution, ComparisonExplanation, InterviewResult, Preference, Resource, Scenario, ScenarioDraft

from .prompts import system_prompt
from .decision_tools import interview_algorithm_context



class AIError(Exception):
    pass


class StructuredOutputError(AIError):
    pass


class AlgorithmQuestionError(ValueError):
    pass


_json_mode_unsupported=OrderedDict()


def redact_provider(provider):
    if not provider:
        return None
    result = dict(provider)
    result["api_key"] = ""
    result["has_key"] = bool(provider.get("api_key"))
    result["clear_key"] = False
    # Additional headers may themselves contain API credentials.
    result["headers"] = {k: "" for k in provider.get("headers", {})}
    result["saved_header_names"] = list(provider.get("headers", {}))
    return result


def merge_provider(new, old=None):
    from .models import Provider
    old = old or {}
    clean = {k: v for k, v in new.items() if k not in {"has_key", "saved_header_names"}}
    provider = Provider(**clean).model_dump()
    if not provider["api_key"] and not provider["clear_key"]:
        provider["api_key"] = old.get("api_key", "")
    provider["headers"] = {k: v or old.get("headers", {}).get(k, "") for k, v in provider["headers"].items()}
    provider["clear_key"] = False
    return provider


def resolve_provider(config, room=None):
    if room and room.get("provider"):
        p = room["provider"]
        if p["enabled"]:
            return p
        return None
    selected = room.get("provider_id") if room else None
    selected = selected or config.get("default_provider")
    return next((p for p in config["providers"] if p["id"] == selected and p["enabled"]), None)


def headers(provider):
    result = {"Content-Type": "application/json", **provider.get("headers", {})}
    if provider["protocol"] == "anthropic":
        result.setdefault("anthropic-version", "2023-06-01")
    if provider.get("api_key"):
        result[provider["auth_header"]] = provider["auth_prefix"] + provider["api_key"]
    return result


def substitute(value, variables):
    if isinstance(value, str) and value in variables:
        return variables[value]
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    return value


def contains_messages(value):
    if isinstance(value, str):
        return value == "$messages"
    if isinstance(value, dict):
        return any(contains_messages(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_messages(v) for v in value)
    return False


def extract_path(value, path):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, list):
        value = "\n".join(x.get("text", "") for x in value if isinstance(x, dict))
    if not isinstance(value, str):
        raise AIError("响应字段不是文本，请检查响应路径")
    return value


def request_endpoint(provider):
    """Accept common OpenAI bases while preserving complete/custom request URLs."""
    endpoint = provider.get("endpoint", "").strip()
    if provider.get("protocol") != "openai" or not endpoint:
        return endpoint
    url = urlsplit(endpoint)
    path = url.path.rstrip("/")
    if not path:
        path = "/v1/chat/completions"
    elif path.endswith("/v1"):
        path += "/chat/completions"
    else:
        return endpoint
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


async def request(provider, system, messages):
    if not provider.get("endpoint") or not provider.get("model"):
        raise AIError("AI 接口尚未填写完整端点或模型名称")
    body = {"model": provider["model"], "max_tokens": provider["max_tokens"], "temperature": provider["temperature"], "stream": False}
    extra = {k: v for k, v in provider.get("extra_body", {}).items() if k not in {"messages", "system", "model", "max_tokens", "stream"}}
    body.update(extra)
    if provider["protocol"] == "anthropic":
        body.update(system=system, messages=messages)
        path = "content"
    elif provider["protocol"] == "custom":
        variables = {"$model": provider["model"], "$system": system, "$messages": [{"role": "system", "content": system}, *messages], "$conversation": messages, "$input": messages[-1]["content"], "$max_tokens": provider["max_tokens"], "$temperature": provider["temperature"]}
        template = provider.get("request_template")
        if not template or not contains_messages(template):
            raise AIError("自定义请求模板必须含 $messages，确保系统上下文被传递")
        body = substitute(template, variables)
        path = provider["response_path"]
    else:
        body["messages"] = [{"role": "system", "content": system}, *messages]
        path = provider["response_path"] or "choices.0.message.content"
    capability=(request_endpoint(provider),provider.get("model",""))
    automatic_json=provider["protocol"]=="openai" and "JSON Schema" in system and "response_format" not in body and _json_mode_unsupported.get(capability,0)<time.monotonic()
    if automatic_json:body["response_format"]={"type":"json_object"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(provider["timeout"], connect=10), limits=httpx.Limits(max_connections=1, max_keepalive_connections=0), follow_redirects=False, trust_env=False) as client:
            for attempt in range(2):
                async with client.stream("POST", request_endpoint(provider), headers=headers(provider), json=body) as response:
                    if response.status_code >= 300:
                        if automatic_json and response.status_code in {400,422}:
                            detail=bytearray()
                            async for chunk in response.aiter_bytes():
                                detail.extend(chunk[:4096-len(detail)])
                                if len(detail)>=4096:break
                            if any(marker in bytes(detail).lower() for marker in (b"response_format",b"json_object")):
                                _json_mode_unsupported[capability]=time.monotonic()+600
                                _json_mode_unsupported.move_to_end(capability)
                                while len(_json_mode_unsupported)>64:_json_mode_unsupported.popitem(last=False)
                                body.pop("response_format",None);automatic_json=False
                                continue
                        raise AIError(f"第三方接口返回 HTTP {response.status_code}，请检查端点、模型和鉴权配置")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 2 * 1024 * 1024:
                            raise AIError("第三方响应超过 2 MB 限制")
                    data = json.loads(chunks)
                    if provider['protocol']=='openai' and data.get('choices',[{}])[0].get('finish_reason')=='length':
                        raise AIError('模型输出达到长度上限，回答尚未完整。请在房间接口中提高输出上限后重试')
                    content=extract_path(data,path)
                    if not content.strip():raise AIError('模型没有返回回答正文，请换用其他模型或调整输出上限后重试')
                    return content[:30000]
        raise AIError("接口未返回可用内容")
    except AIError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise AIError("AI 请求失败或响应结构不匹配，请检查接口配置后重试") from None


def models_endpoint(provider):
    explicit = provider.get("models_endpoint", "").strip()
    if explicit:
        return explicit
    endpoint = request_endpoint(provider)
    if not endpoint:
        raise AIError("请先填写接口地址，或单独填写模型列表地址")
    url = urlsplit(endpoint)
    path = url.path.rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/responses"):
        if path.endswith(suffix):
            path = path[:-len(suffix)] + "/models"
            break
    else:
        if not path or path.endswith("/v1"):
            path += "/models"
        elif not path.endswith("/models"):
            raise AIError("无法从这个端点推导模型列表地址，请在表单中填写模型列表地址")
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def lookup_path(value, path):
    if path:
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def model_ids(data, provider):
    path = provider.get("models_path", "data")
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and path == "data" and "data" not in data and isinstance(data.get("models"), list):
        items = data["models"]
    else:
        try:
            items = lookup_path(data, path)
        except (KeyError, IndexError, TypeError, ValueError):
            raise AIError("模型列表路径不存在，请检查列表路径配置") from None
    if not isinstance(items, list):
        raise AIError("模型列表路径必须指向 JSON 数组")
    field = provider.get("model_id_field", "id")
    result = set()
    for item in items:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            try:
                value = lookup_path(item, field)
            except (KeyError, IndexError, TypeError, ValueError):
                value = item.get("name") if field == "id" else None
        else:
            value = None
        if isinstance(value, str) and 0 < len(value.strip()) <= 200:
            result.add(value.strip())
    if items and not result:
        raise AIError("返回的模型条目中没有有效 ID，请检查模型 ID 字段配置")
    return sorted(result)[:1000]


async def discover_models(provider):
    endpoint = models_endpoint(provider)
    try:
        async with asyncio.timeout(min(provider.get("timeout", 60), 45)):
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), limits=httpx.Limits(max_connections=1, max_keepalive_connections=0), follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", endpoint, headers=headers(provider)) as response:
                    if response.status_code >= 300:
                        if response.status_code in {401, 403}:
                            raise AIError(f"模型列表鉴权失败（HTTP {response.status_code}），请检查密钥、鉴权头及前缀")
                        if response.status_code == 404:
                            raise AIError("模型列表地址不存在（HTTP 404），请填写供应商提供的模型列表地址")
                        raise AIError(f"模型列表请求返回 HTTP {response.status_code}")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1024 * 1024:
                            raise AIError("模型列表超过 1 MB 限制")
                    data = json.loads(raw)
        return model_ids(data, provider)
    except AIError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise AIError("拉取模型超时，请稍后重试或检查模型列表地址") from None
    except httpx.HTTPError:
        raise AIError("无法连接模型列表服务，请检查地址与连接配置") from None
    except (ValueError, KeyError, TypeError):
        raise AIError("模型列表不是有效 JSON，或返回结构与配置不匹配") from None


def parse_json(text):
    text = text.strip()
    # Some compatible providers wrap structured content in a short explanation/fence.
    try:
        return json.loads(text)
    except ValueError:
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            return json.loads(fenced.group(1).strip())
        start = re.search(r"[\[{]", text)
        if start:
            return json.JSONDecoder().raw_decode(text[start.start():])[0]
        raise ValueError("没有可解析的 JSON") from None


def scenario_output(answer, original):
    obj=parse_json(answer)
    if not isinstance(obj,dict):
        raise ValueError("场景需要对象")
    core=obj.get("scenario",{key:value for key,value in obj.items() if key!="resources"})
    if not isinstance(core,dict):
        raise ValueError("场景需要对象")
    core={**core}
    for field in ("city","date","description"):
        if core.get(field) is None:core[field]=""
    if not core.get("description"):core["description"]=original[:2000]
    scenario=Scenario(**core).model_dump()
    if not scenario["title"].strip():raise ValueError("缺少决策名称")
    candidates=obj.get("resources") or []
    warnings=[];resources=[]
    if not isinstance(candidates,list):
        candidates=[];warnings.append("候选草稿格式有误，已保留场景，可在房间左侧继续提议。")
    for candidate in candidates[:20]:
        try:
            resource=Resource(**{**candidate,"id":store.new_id(),"confirmed":False,"verified":False}).model_dump()
            resources.append(resource)
        except (ValueError,TypeError):
            warnings.append("有候选草稿缺少有效资料，已略过该条；场景和其他候选仍保留。")
    return {"scenario":scenario,"resources":resources,"warnings":list(dict.fromkeys(warnings)),"mode":"ai"}


async def validate_output(answer,provider,system,messages,validator,started,budget=None):
    try:
        return validator(answer)
    except (ValueError,KeyError,TypeError) as error:
        if hasattr(error,"errors"):
            issues=[{"field":list(item["loc"]),"message":item["msg"][:300]} for item in error.errors(include_input=False,include_url=False)[:8]]
        else:issues=[{"message":str(error) if isinstance(error,AlgorithmQuestionError) else "需要有效 JSON 对象及约定字段"}]
    remaining=provider["timeout"]+5-(time.monotonic()-started)
    if remaining<=0 or (budget is not None and budget["remaining"]<=0):
        raise StructuredOutputError("本轮未形成有效结构")
    if budget is not None:budget["remaining"]-=1
    repair=[*messages,{"role":"assistant","content":answer[:12000]},{"role":"user","content":"只修复上一份输出的 JSON 与字段结构，遵循系统 JSON Schema，不新增或猜测事实。保留原始目标、已知条件以及原始 calendar 日期和时区。校验提示："+store.dumps(issues)}]
    try:
        fixed=await asyncio.wait_for(request(provider,system,repair),timeout=remaining)
        return validator(fixed)
    except (ValueError,KeyError,TypeError,AIError,TimeoutError):
        raise StructuredOutputError("结构修复未成功，保留已有数据") from None


def interview_policy(history,version,action,text):
    asked=0;seen=[]
    for row in history:
        meta=row.get("metadata",{})
        if meta.get("preference_version",version)!=version:continue
        if row["role"]=="user" and meta.get("interview_action") in {"start","continue"}:asked=0;seen=[]
        turn=meta.get("interview") if row["role"]=="assistant" else None
        if turn:
            if turn.get("ready"):asked=0;seen=[]
            elif turn.get("question"):asked+=1;seen.append(turn["question"])
    if action in {"start","continue"}:asked=0;seen=[]
    finish=action=="finish" or any(marker in text for marker in ("请先把已有回答整合","请整合当前回答","结束卡片"))
    return {"asked":asked,"seen":seen,"limit":4,"reason":"user_finished" if finish else "question_limit" if asked>=4 else ""}





def read_interview(answer,policy,algorithm=None):
    obj=parse_json(answer)
    if not isinstance(obj,dict):raise ValueError("访谈结果需要对象")
    # Older history used this equivalent envelope; accept it without wasting a repair call.
    if isinstance(obj.get('interview'),dict):
        nested=obj['interview'];obj={**nested,'draft':obj.get('draft',nested.get('draft',{}))}
    for key in ('question','left','right','summary','purpose'):
        if obj.get(key) is None:obj[key]=''
    for key in ('insights','targets','tool_calls'):
        if obj.get(key) is None:obj[key]=[]
    clean=lambda value:re.sub(r"[\W_]+","",str(value)).casefold()
    if not policy["reason"] and not obj.get("ready") and clean(obj.get("question","")) in {clean(q) for q in policy["seen"]}:
        policy["reason"]="repeated_question"
    if policy["reason"]:obj.update(ready=True,question="",left="",right="",tool_calls=[])
    result=InterviewResult(**obj).model_dump()
    if not result["ready"] and algorithm is not None:
        if not result["targets"] or not result["purpose"].strip() or any(key not in algorithm["supported_fields"] for key in result["targets"]):
            raise AlgorithmQuestionError("非 ready 卡片必须有非空 targets 与 purpose；targets 只选 algorithm_contract.supported_fields 中的字段，purpose 用普通语言说明对可行性或候选排序的作用。没有实际用途时请结束整理，不继续问。")
    try:
        result["input_cards"]=dispatch_input_tools(result)
    except ValueError as error:
        raise AlgorithmQuestionError(str(error)) from None
    result["summary"]=result["summary"] or "已整理目前表达的想法，请核对需求结果后再确认。"
    return result


def keep_unanswered_options_optional(interview,history,policy,version):
    """Ending a model's optional follow-up cannot create a new member obligation."""
    if policy['reason'] not in {'user_finished','question_limit','repeated_question'}:
        return
    current=[row for row in history if row.get('metadata',{}).get('preference_version',version)==version]
    questions=[(index,row['metadata']['interview']) for index,row in enumerate(current) if row['role']=='assistant' and row.get('metadata',{}).get('interview',{}).get('question')]
    if not questions:return
    index,question=questions[-1]
    optional={'criteria','categories','cost_preference','budget_target','budget_weight','preferred_start','preferred_end','time_weight','activity_weight'}
    if not question.get('targets') or not set(question['targets'])<=optional:return
    controls={'start','continue','finish'}
    if any(row['role']=='user' and row.get('metadata',{}).get('interview_action') not in controls for row in current[index+1:]):return
    authored=[row['content'] for row in current if row['role']=='user' and row.get('metadata',{}).get('interview_action') not in controls and not row['content'].startswith('针对问题')]
    # Be conservative whenever the member actually expressed a qualitative bottom line.
    if any(re.search(r'必须|不能|一定要|禁止|过敏|绝不|只能',text) for text in authored):return
    clean=lambda value:re.sub(r'[\W_]+','',value)
    draft=interview['draft'];remaining=[]
    for item in draft['unresolved']:
        if SequenceMatcher(None,clean(item),clean(question['question'])).ratio()<.55:
            remaining.append(item)
    draft['unresolved']=remaining


def local_preferences(text):
    p = Preference().model_dump()
    match = re.search(r"(?:最多|不能超过|不超过|上限)\s*(\d+(?:\.\d+)?)\s*(?:元|块)", text)
    if match:
        p["budget_max"] = min(float(match[1]), 1000000)
    match = re.search(r"(?:最好|希望|预算)\s*(?:控制在|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)", text)
    if match:
        p["budget_target"] = min(float(match[1]), 1000000)
    times = re.search(r"(\d{1,2}):(\d{2})\s*(?:到|至|[-~—])\s*(\d{1,2}):(\d{2})", text)
    if times:
        values = [int(v) for v in times.groups()]
        begin, end = values[0] * 60 + values[1], values[2] * 60 + values[3]
        if 0 <= begin < end <= 1440 and values[1] < 60 and values[3] < 60:
            p.update(available_start=begin, available_end=end)
    p["other"] = text[:2000]
    p["notes"] = ["规则提取仅识别明确预算与 HH:MM 时间段，请核对全文并补齐其他条件"]
    return p


async def complete(config, room, user_id, kind, text, draft=None, interview_action="answer"):
    provider = resolve_provider(config, room)
    context = {"calendar":calendar_context()}
    if room:
        me = next(m for m in room["members"] if m["id"] == user_id)
        context = {"scenario": room["scenario"], "resources": room["resources"], "my_preference": me.get("preference"), "phase": room["state"], "proposals": [{"title": p["title"], "evaluation": {k: p["evaluation"][k] for k in ("status", "cost", "start", "end", "score", "coverage")}} for p in room["proposals"]], "my_feedback": [f["text"] for f in room["feedback"] if f["member_id"] == user_id], "authorized_summaries": [f["summary"] for f in room["feedback"] if f["summary"]]}
    if room:
        members=[member for member in room["members"] if member["status"]=="approved"]
        context["group_progress"]={"member_count":len(members),"confirmed_count":sum(member["confirmed"] for member in members),"my_confirmed":me["confirmed"],"meaning":"当前是同一次群体决策；本次仅私密了解此成员，以便随后核对全体必要条件及公平性，不代表为个人单独推荐或已达成共识。"}
        context["decision_agent"]={key:room.get("agent",{}).get(key) for key in ("goal","summary","next_step") } if room.get("agent") else {}
        context.update(knowledge=room.get("knowledge",""),supplements=visible_supplements(room,user_id),calendar=calendar_context())
        from .decision_tools import decision_progress
        context["decision_progress"]=decision_progress(room)
    if room and kind == "explain":
        from .domain import view
        context["comparison"] = view(room, user_id)
    if draft is not None and kind == "interview":
        context["my_current_draft"] = draft.model_dump()
    if not provider:
        if kind in {"interview", "explain"}:
            raise AIError("当前没有可用 AI 接口，请房主在房间设置配置后继续；也可直接编辑需求表")
        if kind == "preferences":
            return "当前未启用 AI 接口。已用本地规则提取明确字段，请逐项补充、编辑并确认。", {"draft": local_preferences(text), "mode": "local"}
        if kind == "scenario":
            return "当前未启用 AI 接口，已保存目标文字；可先创建空间，再配置接口让 Agent 继续。", {"scenario": Scenario(title=text[:60], description=text[:2000]).model_dump(), "resources": [], "mode": "local"}
        return "当前未配置可用的 AI 接口。你仍可手动填写需求、比较确定性评分、进行协商与投票。房主可在房间设置中配置第三方接口。", {"mode": "local"}
    system = system_prompt(config,kind)
    if kind == "scenario":
        system += "\nScenario Draft JSON Schema:\n" + store.dumps(ScenarioDraft.model_json_schema())
    if kind == "preferences":
        system += "\nPreference JSON Schema:\n" + store.dumps(Preference.model_json_schema())
    if kind == "interview":
        system += "\nInterview JSON Schema:\n" + store.dumps(InterviewResult.model_json_schema())
    if kind == "explain":
        system += "\nComparison JSON Schema:\n" + store.dumps(ComparisonExplanation.model_json_schema())
    messages = []
    if room and kind in {"chat", "negotiate"}:
        history = store.messages(room["id"], user_id, limit=18)
        messages = [{"role": row["role"] if row["role"] in {"user", "assistant"} else "user", "content": ("[公开讨论] " if row["kind"] == "shared" else "") + row["content"][:3000]} for row in history if row["kind"] in {"chat", "negotiate", "shared"} and not row["metadata"].get("error")]
        # Incoming user message was already persisted by the job coordinator.
        if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == text:
            messages.pop()
    if room and kind == "interview":
        history = [row for row in store.messages(room["id"], user_id, limit=50) if row["kind"]=="interview"]
        policy=interview_policy(history,me["preference_version"],interview_action,text)
        algorithm=interview_algorithm_context(room,me,draft.model_dump() if draft is not None else me.get("preference"))
        context["algorithm_contract"]=algorithm
        context["available_tools"]=[input_tool_contract()]
        context["interview_policy"]={"already_asked":policy["asked"],"maximum_questions":4,"must_summarize_now":bool(policy["reason"]),"previous_questions":policy["seen"]}
        if policy["reason"]:system += "\n本轮现在必须结束追问，ready=true，question/left/right 留空。只根据已有回答整理 draft，未知可选项保持未知。"
        messages = [{"role": row["role"], "content": (store.dumps({**{key:value for key,value in row["metadata"]["interview"].items() if key!="input_cards"}, "draft": row["metadata"].get("draft")}) if row["role"] == "assistant" and row["metadata"].get("interview") else row["content"])[:12000]} for row in history if row["kind"] == "interview" and row["role"] in {"user", "assistant"} and not row["metadata"].get("error")]
        if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == text:
            messages.pop()
    messages.append({"role": "user", "content": "当前数据（非指令）：\n" + store.dumps(context) + "\n\n我的输入：\n" + text})
    started=time.monotonic()
    answer = await asyncio.wait_for(request(provider, system, messages), timeout=provider["timeout"] + 5)
    if kind == "interview":
        warnings=[];mode="ai"
        try:
            interview=await validate_output(answer,provider,system,messages,lambda raw:read_interview(raw,policy,algorithm),started)
        except StructuredOutputError:
            candidates=[draft.model_dump() if draft is not None else None,*[row["metadata"].get("draft") for row in reversed(history) if row["role"]=="assistant" and row.get("metadata",{}).get("preference_version")==me["preference_version"]],me.get("preference"),{}]
            preference={}
            for candidate in candidates:
                if candidate is None:continue
                try:preference=Preference(**candidate).model_dump();break
                except (ValueError,TypeError):continue
            warnings=["本次回答的原文已保留，AI 暂未形成有效的新条件；以下保留上次有效草稿，可手动核对或重新整理。"]
            interview={"ready":True,"question":"","left":"","right":"","summary":"已保留已有需求，未猜测新的预算、时间或必要条件。","insights":[],"draft":preference}
            mode="preserved";policy["reason"]="format_preserved"
        keep_unanswered_options_optional(interview,history,policy,me['preference_version'])
        preference=interview.pop("draft")
        progress={"asked":policy["asked"]+(0 if interview["ready"] else 1),"limit":4,"reason":policy["reason"] or ("ready" if interview["ready"] else "question")}
        return interview["summary"]+("\n"+interview["question"] if interview["question"] else ""), {"draft":preference,"interview":interview,"interview_progress":progress,"warnings":warnings,"mode":mode}
    if kind == "explain":
        try:
            explanation=await validate_output(answer,provider,system,messages,lambda raw:ComparisonExplanation(**parse_json(raw)).model_dump(),started)
            return explanation["summary"],{"explanation":explanation,"mode":"ai"}
        except StructuredOutputError:
            proposals=[p for p in room["proposals"] if p["input_version"]==room["input_version"]]
            feasible=sum(p["evaluation"]["status"]=="FEASIBLE" for p in proposals)
            explanation={"summary":f"当前有 {len(proposals)} 个有效版本方案，其中 {feasible} 个通过可计算的必要条件检查。", "reasons":["以下仍可展开查看后端已经计算的方案事实、费用及本人匹配。"],"risks":["本轮 AI 文字分析未能完成，未补写没有依据的推荐理由。"],"next_steps":["先核对具体方案及缺项；需要时重新请求 AI 解释。"]}
            return explanation["summary"],{"explanation":explanation,"mode":"preserved","warnings":["AI 解释暂不可用，已保留实际计算结果。"]}
    if kind == "preferences":
        try:
            preference=await validate_output(answer,provider,system,messages,lambda raw:Preference(**parse_json(raw)).model_dump(),started)
            return "已整理为待确认的条件草稿，请核对后由你确认。",{"draft":preference,"mode":"ai"}
        except StructuredOutputError:
            return "AI 暂未形成有效结构，原文已保留，以下为明确字段的本地提取草稿。",{"draft":local_preferences(text),"mode":"local"}
    if kind == "scenario":
        try:
            result=await validate_output(answer,provider,system,messages,lambda raw:scenario_output(raw,text),started)
        except StructuredOutputError:
            return "AI 暂未整理成有效场景，原话已保留；可以直接创建空间后继续讨论。", {"scenario":Scenario(title=text.strip()[:60] or "待讨论的决定",description=text[:2000]).model_dump(),"resources":[],"warnings":["未采用格式不完整的 AI 结果，日期和候选未自动填写。"],"mode":"local"}
        return "场景已整理，请核对后创建；候选提议仍需核对。",result
    return answer, {"mode": "ai"}


async def resolve_date(config, room, text):
    provider=resolve_provider(config,room)
    if not provider:
        raise AIError("日期换算需要可用 AI 接口，请先配置接口或选择具体日期")
    clock=calendar_context()
    system=system_prompt(config,"date")+"\nDate Resolution JSON Schema:\n"+store.dumps(DateResolution.model_json_schema())
    messages=[{"role":"user","content":store.dumps({"calendar":clock,"scenario":room["scenario"] if room else None,"text":text})}]
    started=time.monotonic()
    raw=await asyncio.wait_for(request(provider,system,messages),timeout=provider["timeout"]+5)
    try:
        result=await validate_output(raw,provider,system,messages,lambda answer:DateResolution(**parse_json(answer)).model_dump(),started)
    except StructuredOutputError:
        result={"date":"","explanation":"日期暂未确定，原话已保留。","needs_clarification":True,"question":"本次未能可靠换算日期，请选择一个具体日期。"}
    return {**result,"reference_date":clock["date"],"timezone":clock["timezone"],"original":text}


class Coordinator:
    def __init__(self):
        self.pending = {}
        self.running = 0
        self.condition = asyncio.Condition()

    async def run(self, operation):
        async with self.condition:
            await self.condition.wait_for(lambda: self.running < store.settings()["ai_concurrency"])
            self.running += 1
        try:
            return await operation()
        finally:
            async with self.condition:
                self.running -= 1
                self.condition.notify_all()

    def submit(self, key, coroutine, callback):
        config = store.settings()
        if key in self.pending:
            raise AIError("你上一次的 AI 请求仍在处理中")
        if len(self.pending) >= config["ai_queue_limit"]:
            raise AIError("当前 AI 队列已满，请稍后再试")
        async def work():
            try:
                result = await asyncio.wait_for(self.run(coroutine), timeout=600)
                await callback(result, None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = str(exc) if isinstance(exc, AIError) else "AI 处理超时或暂时不可用，请稍后重试"
                await callback(None, error)
            finally:
                if self.pending.get(key) is asyncio.current_task():
                    self.pending.pop(key, None)
        self.pending[key] = asyncio.create_task(work())

    async def cancel_room(self, room_id):
        tasks = [task for key, task in self.pending.items() if key[0] == room_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A queued task cancelled before its first instruction cannot run its finally block.
        for key, task in list(self.pending.items()):
            if key[0] == room_id and task.done():
                self.pending.pop(key, None)

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
