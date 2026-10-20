"""Conditional card tools collect actual answers before advancing the interview."""
import asyncio
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from wedecide import ai

ROOT = Path(__file__).resolve().parents[1]


def question(**changes):
    return {"question": "人均费用最多可以接受多少？", "left": "填写具体上限", "right": "暂时待定，之后再补", "targets": ["budget_max"], "purpose": "筛掉超过本人费用上限的候选。", "draft": {}, **changes}


class InputToolTests(unittest.TestCase):
    def read(self, value, reason=""):
        return ai.read_interview(json.dumps(value), {"reason": reason, "seen": []}, {"supported_fields": {"budget_max": "人均上限", "criteria": "具体偏好"}})

    def test_agent_tool_produces_a_number_card_only_for_the_selected_branch(self):
        result = self.read(question(tool_calls=[{"tool": "request_input", "choice": "left", "field": "budget_max", "label": "可接受的人均上限"}]))
        self.assertEqual(result["input_cards"]["left"]["kind"], "number")
        self.assertEqual(result["input_cards"]["left"]["unit"], "元/人")
        self.assertNotIn("right", result["input_cards"])
        self.assertIsNone(result["draft"]["budget_max"])

    def test_tool_cannot_request_an_unrelated_algorithm_field(self):
        with self.assertRaises(ValueError):
            self.read(question(tool_calls=[{"tool": "request_input", "choice": "left", "field": "criteria", "label": "补充"}]))

    def test_finished_round_does_not_dispatch_input_tools(self):
        result = self.read(question(tool_calls=[{"tool": "request_input", "choice": "left", "field": "budget_max", "label": "人均上限"}]), "question_limit")
        self.assertEqual(result["input_cards"], {})
        self.assertTrue(result["ready"])

    def test_tool_is_available_in_the_private_agent_and_dispatched_without_an_extra_model_call(self):
        from wedecide import domain
        from wedecide.models import CreateRoom
        room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'共同聚餐'}),8)
        value=question(tool_calls=[{"tool":"request_input","choice":"left","field":"budget_max","label":"人均上限"}])
        upstream=AsyncMock(return_value=json.dumps(value))
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',upstream),patch.object(ai.store,'messages',return_value=[]):
            _,metadata=asyncio.run(ai.complete({},room,'host','interview','我有费用上限'))
        self.assertEqual(upstream.await_count,1)
        context=upstream.call_args.args[2][-1]['content']
        self.assertIn('available_tools',context)
        self.assertIn('request_input',context)
        self.assertEqual(metadata['interview']['input_cards']['left']['field'],'budget_max')
        self.assertIsNone(metadata['draft']['budget_max'])
        self.assertFalse(room['members'][0]['confirmed'])

    def test_duplicate_branch_tools_are_rejected_and_time_controls_are_typed(self):
        from wedecide.interview_tools import input_control
        call={"tool":"request_input","choice":"left","field":"budget_max","label":"上限"}
        with self.assertRaises(ValueError):self.read(question(tool_calls=[call,call]))
        self.assertTrue(input_control('available_end')['allow_midnight_end'])
        self.assertFalse(input_control('available_start')['allow_midnight_end'])
        self.assertEqual(input_control('criteria')['kind'],'text')


class InputInteractionTests(unittest.TestCase):
    def test_legacy_and_tool_cards_require_actual_input_and_keep_card_identity(self):
        script = r"""
          import assert from 'node:assert/strict';
          import * as cards from './web/interview-input.js';
          import {preferenceEditor} from './web/preferences.js';
          assert.equal(typeof cards.chooseInterviewAnswer, 'function', 'a branch must be handled before sending a reply');
          const room={id:'room',state:'COLLECTING',scenario:{title:'一起吃饭'},resources:[],me:{id:'host',preference_version:0,preference:{}}};
          const turn={id:7,role:'assistant',kind:'interview',metadata:{preference_version:0,interview:{question:'请填写能接受的人均上限',left:'我填写具体上限（元/人）',right:'暂时待定，之后再补',targets:['budget_max']},draft:{}}};
          const state={room,messages:[turn],zen:true,prefStep:0,savingPreferences:new Set()};
          const choice=cards.chooseInterviewAnswer(state, 'left');
          assert.equal(choice.text, undefined, 'opening an input branch must not send its promise as an answer');
          state.interviewInput=choice.input;
          assert.equal(cards.currentInterviewInput(state).spec.kind, 'number');
          const html=preferenceEditor(state);
          assert.match(html,/id="interview-value-form"/);
          assert.match(html,/type="number"/);
          assert.match(html,/提交并继续/);
          assert.doesNotMatch(html,/data-action="interview-answer" data-choice="left"/);
          assert.throws(()=>cards.interviewInputAnswer(state, ''),/填写/);
          assert.throws(()=>cards.interviewInputAnswer(state, '-1'),/金额/);
          assert.match(cards.interviewInputAnswer(state, '0'),/0 元\/人/);
          assert.match(cards.interviewInputAnswer(state, '88.50'),/88.5 元\/人/);
          assert.equal(cards.chooseInterviewAnswer(state,'right').input, undefined);
          assert.match(cards.chooseInterviewAnswer(state,'right').text,/暂时待定/);
          state.messages=[{...turn,id:8}];
          assert.equal(cards.currentInterviewInput(state),null, 'an old form cannot answer a new question');
          assert.throws(()=>cards.interviewInputAnswer(state, '88'),/变化/);
          // Tool-selected text controls must also collect a concrete statement.
          const textTurn={...turn,metadata:{...turn.metadata,interview:{...turn.metadata.interview,input_cards:{left:{kind:'text',field:'criteria',label:'具体要求',unit:''}}}}};
          state.messages=[textTurn];state.interviewInput=cards.chooseInterviewAnswer(state,'left').input;
          assert.match(cards.interviewInputAnswer(state, '需要安静一点'),/需要安静一点/);
          // A clock input accepts 24:00 only as an end and never invents a time.
          state.messages=[{...turn,metadata:{...turn.metadata,interview:{...turn.metadata.interview,input_cards:{left:{kind:'time',field:'available_end',label:'最晚结束',unit:''}}}}}];
          state.interviewInput=cards.chooseInterviewAnswer(state,'left').input;
          assert.match(cards.interviewInputAnswer(state, '24:00'),/24:00/);
          assert.throws(()=>cards.interviewInputAnswer(state, '24:30'),/时间/);
        """
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
