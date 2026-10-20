"""The room agent uses real algorithm results and the administrator's presets."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from wedecide import ai, agent, app, domain, engine, store
from wedecide.models import CreateRoom, Preference, Resource


def prepared_room():
    room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'共同选择'}),8)
    room['members'][0].update(confirmed=True,preference=Preference(cost_preference='lower').model_dump())
    room['resources']=[Resource(id='a',kind='decision',name='方向甲',cost=50,confirmed=True).model_dump(),Resource(id='b',kind='decision',name='方向乙',cost=100,confirmed=True).model_dump()]
    return room


class PromptPresetTests(unittest.TestCase):
    def test_every_stage_has_an_effective_preset_and_customization_keeps_output_contracts(self):
        from wedecide import prompts
        self.assertEqual(set(prompts.PRESETS),{'context','agent','interview','explain','scenario','preferences','negotiate','chat','date'})
        config={'prompts':{'context':'组织背景示例','agent':'主持规则示例','interview':'访谈规则示例','explain':'比较规则示例'}}
        for key in ('agent','interview','explain'):
            system=prompts.system_prompt(config,key)
            self.assertIn(config['prompts'][key],system)
            self.assertIn('组织背景示例',system)
            self.assertIn(prompts.OUTPUT_RULES[key],system)
        self.assertEqual(prompts.effective_prompt({'prompts':{'agent':'  '}},'agent'),prompts.PRESETS['agent'])

    def test_admin_roundtrip_preserves_other_stages_and_restores_a_preset(self):
        async def run():
            with tempfile.TemporaryDirectory(prefix='wedecide-prompts-') as directory,patch.object(store,'DATA_DIR',Path(directory)),patch.object(store,'DB_PATH',Path(directory)/'fixture.sqlite'),patch.object(app,'authenticated',return_value='admin'):
                store.init()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://fixture') as client:
                    current=(await client.get('/api/admin/settings')).json()
                    self.assertIn('prompt_catalog',current)
                    response=await client.put('/api/admin/settings',json={'revision':current['revision'],'prompts':{'agent':'自定义主持','interview':'自定义卡片','explain':'自定义解释'}})
                    self.assertEqual(response.status_code,200,response.text)
                    current=response.json()
                    current=(await client.put('/api/admin/settings',json={'revision':current['revision'],'prompts':{'chat':'自定义对话'}})).json()
                    self.assertEqual(current['prompts']['agent'],'自定义主持')
                    self.assertEqual(current['prompts']['interview'],'自定义卡片')
                    current=(await client.put('/api/admin/settings',json={'revision':current['revision'],'prompts':{'agent':''}})).json()
                    entry=next(x for x in current['prompt_catalog'] if x['key']=='agent')
                    self.assertFalse(entry['customized']);self.assertEqual(entry['effective'],entry['preset'])
                    self.assertEqual(current['prompts']['explain'],'自定义解释')
        asyncio.run(run())


class AlgorithmAgentTests(unittest.TestCase):
    def test_ready_inputs_are_computed_even_when_the_model_initially_only_responds(self):
        room=prepared_room();before=deepcopy(room)
        request=AsyncMock(side_effect=[json.dumps({'summary':'先看看需求'}),json.dumps({'summary':'已根据实际校核比较两个方向'})])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            _,metadata=asyncio.run(agent.run({},room,'host','推进'))
        self.assertIsNotNone(metadata['_prepared_analysis'])
        self.assertEqual(request.await_count,2)
        self.assertTrue(metadata['agent']['tool_results'])
        self.assertEqual(room,before)

    def test_simulation_returns_actual_scores_without_changing_formal_rules(self):
        from wedecide.decision_tools import simulate
        from wedecide.models import DecisionSimulation
        room=prepared_room();domain.analyze(room);before=deepcopy(room)
        result=simulate(room,DecisionSimulation(fairness=.9))
        self.assertTrue(result['hypothetical'])
        self.assertEqual(result['fairness'],.9)
        self.assertEqual(result['input_version'],room['input_version'])
        self.assertEqual(room,before)
        self.assertTrue(result['candidates'])
        self.assertNotIn('member_id',json.dumps(result))

    def test_analysis_progress_explains_real_changes_and_classifies_missing_facts(self):
        room=prepared_room();room['members'][0]['preference']['budget_max']=75
        domain.analyze(room)
        first=domain.view(room,'host')['decision_progress']
        self.assertEqual(first['counts']['FEASIBLE'],1)
        room['resources'][0]['cost']=90
        domain.invalidate(room,'已核对候选费用')
        progress=domain.view(room,'host')['decision_progress']
        self.assertEqual(progress['stage'],'conflict')
        self.assertEqual(progress['change']['previous_feasible'],1)
        self.assertEqual(progress['change']['current_feasible'],0)
        self.assertIn('重新',progress['next_step'])
        room['resources'][0]['cost']=None;domain.invalidate(room,'费用待核对')
        progress=domain.view(room,'host')['decision_progress']
        self.assertEqual(progress['stage'],'needs_facts')
        self.assertNotIn('75',json.dumps(progress,ensure_ascii=False))
        self.assertNotIn('budget_max',json.dumps(progress))

    def test_question_context_distinguishes_candidate_evidence_from_member_questions(self):
        room=prepared_room();member=room['members'][0]
        room['resources'][0]['attributes']={'安静':True};room['resources'][1]['attributes']={'安静':False}
        contract=ai.interview_algorithm_context(room,member,member['preference'])
        self.assertIn('decision_gaps',contract)
        self.assertTrue(any(gap['fields']==['criteria'] and gap['scope']=='member' for gap in contract['decision_gaps']))
        room['resources'][0]['confirmed']=False
        contract=ai.interview_algorithm_context(room,member,member['preference'])
        self.assertTrue(any(gap['scope']=='organizer' for gap in contract['decision_gaps']))
