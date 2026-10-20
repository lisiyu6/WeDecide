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
    def test_synthesis_receipts_only_reference_public_inputs_actually_read(self):
        room=prepared_room()
        room['supplements']=[{'id':'public-1','kind':'suggestion','visibility':'shared','member_id':'host','title':'方向建议','text':'考虑方向甲','at':1},{'id':'private-1','kind':'information','visibility':'private','member_id':'host','title':'私密','text':'私人原话','at':2}]
        answer={'summary':'已经合并公开方向，比较了代价。','synthesis':{'common_ground':['沿用共同目标'],'tradeoffs':['方向甲费用较低'],'source_ids':['public-1','private-1','invented']}}
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',AsyncMock(return_value=json.dumps(answer))):
            _,metadata=asyncio.run(agent.run({},room,'host','整理'))
        report=metadata['agent']
        self.assertEqual(report['synthesis']['source_ids'],['public-1'])
        self.assertEqual(report['intake']['suggestions'],1)
        self.assertEqual(report['intake']['confirmed_members'],1)
        self.assertNotIn('private-1',json.dumps(report,ensure_ascii=False))

    def test_host_can_review_ai_drafts_and_confirm_known_facts_in_one_step(self):
        room=prepared_room()
        resource=Resource(id='new',kind='decision',name='公开提议整理',cost=None).model_dump()
        room['agent']={'input_version':room['input_version'],'context_version':room['context_version'],'round':0,'resources':[resource]}
        reviewed={**resource,'cost':35,'cost_upper':40,'source':'房主提供的资料','confirmed':True}
        domain.mutate(room,'host','agent_draft',{'reviewed_resources':[reviewed]},room['revision'],{'max_members':8})
        saved=next(r for r in room['resources'] if r['id']=='new')
        self.assertEqual(saved['cost'],35)
        self.assertTrue(saved['confirmed'])
        self.assertTrue(room['agent']['applied'])
        self.assertEqual(len(room['resources']),3)

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

    def test_agent_reads_analysis_then_simulation_before_its_final_explanation(self):
        room=prepared_room();before=deepcopy(room)
        answers=[{'tool':'analyze','summary':'先校核'},{'tool':'simulate','simulation':{'fairness':.8},'summary':'比较公平性取舍'},{'tool':'respond','summary':'已根据实际结果说明取舍'}]
        request=AsyncMock(side_effect=[json.dumps(value) for value in answers])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            _,metadata=asyncio.run(agent.run({},room,'host','比较不同取舍'))
        self.assertEqual(request.await_count,3)
        self.assertEqual([r['tool'] for r in metadata['agent']['tool_results']],['analyze','simulate'])
        self.assertTrue(metadata['agent']['tool_results'][1]['hypothetical'])
        self.assertTrue(metadata['agent']['tool_results'][1]['candidates'])
        self.assertIn('simulate 工具实际结果',request.call_args.args[2][-1]['content'])
        self.assertEqual(room,before)

    def test_upstream_failure_after_calculation_keeps_the_actual_result(self):
        room=prepared_room();request=AsyncMock(side_effect=[json.dumps({'tool':'analyze','summary':'先校核'}),ai.AIError('上游暂时不可用')])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            _,metadata=asyncio.run(agent.run({},room,'host','推进'))
        self.assertTrue(metadata['_prepared_analysis']['proposals'])
        self.assertEqual(metadata['agent']['tool_results'][0]['tool'],'analyze')
        self.assertEqual(metadata['mode'],'preserved')

    def test_initial_model_outage_still_computes_ready_confirmed_data(self):
        room=prepared_room()
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',AsyncMock(side_effect=ai.AIError('上游不可用'))):
            _,metadata=asyncio.run(agent.run({},room,'host','继续'))
        self.assertTrue(metadata['_prepared_analysis']['proposals'])
        self.assertEqual(metadata['agent']['tool_results'][0]['tool'],'analyze')
        self.assertEqual(metadata['mode'],'preserved')

    def test_current_unadopted_drafts_survive_a_followup_explanation(self):
        room=prepared_room();domain.analyze(room)
        pending=Resource(id='pending',kind='decision',name='尚待核对方向').model_dump()
        room['agent']={'resources':[pending],'input_version':room['input_version'],'context_version':room['context_version'],'applied':False}
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',AsyncMock(return_value=json.dumps({'summary':'继续解释已有取舍'}))):
            _,metadata=asyncio.run(agent.run({},room,'host','解释'))
        self.assertEqual(metadata['agent']['resources'][0]['id'],'pending')

    def test_delayed_agent_does_not_replace_a_newly_computed_and_selected_formal_plan(self):
        from wedecide.models import AIInput
        async def run():
            room=prepared_room();release=asyncio.Event();coordinator=ai.Coordinator()
            async def delayed(*args):
                prepared=engine.generate(room);await release.wait()
                return '已校核',{'agent':{'summary':'已校核'},'_prepared_analysis':prepared}
            with tempfile.TemporaryDirectory(prefix='wedecide-agent-') as directory,patch.object(store,'DATA_DIR',Path(directory)),patch.object(store,'DB_PATH',Path(directory)/'fixture.sqlite'),patch.object(app,'coordinator',coordinator),patch.object(app.agent,'run',side_effect=delayed):
                store.init()
                with store.transaction() as db:
                    db.execute('INSERT INTO rooms VALUES(?,?,?,?,?,?)',(room['id'],room['code'],room['state'],room['revision'],room['updated'],store.dumps(room)))
                await app.queue_room_ai(room,'host',AIInput(kind='agent',text='校核'))
                await asyncio.sleep(0)
                with store.transaction() as db:
                    current=store.load_room(db,room['id']);domain.analyze(current);selected=current['proposals'][0]['id'];current['selected_id']=selected;store.save_room(db,current)
                tasks=list(coordinator.pending.values());release.set();await asyncio.gather(*tasks)
                with store.connect() as db:saved=store.load_room(db,room['id'])
                self.assertEqual(saved['analysis_version'],1)
                self.assertEqual(saved['selected_id'],selected)
        asyncio.run(run())

    def test_empty_bounded_search_is_a_completed_analysis_not_an_endless_compute_prompt(self):
        room=prepared_room();room['resources']=[Resource(id='one',name='活动',cost=20,confirmed=True).model_dump()]
        room['rules'].update(min_activities=2,max_activities=2)
        domain.analyze(room)
        from wedecide.decision_tools import algorithm_status
        self.assertFalse(room['proposals'])
        self.assertTrue(algorithm_status(room)['current_analysis'])
        self.assertFalse(algorithm_status(room)['needs_analysis'])
        self.assertEqual(domain.view(room,'host')['decision_progress']['stage'],'conflict')

    def test_question_context_distinguishes_candidate_evidence_from_member_questions(self):
        room=prepared_room();member=room['members'][0]
        room['resources'][0]['attributes']={'安静':True};room['resources'][1]['attributes']={'安静':False}
        contract=ai.interview_algorithm_context(room,member,member['preference'])
        self.assertIn('decision_gaps',contract)
        self.assertTrue(any(gap['fields']==['criteria'] and gap['scope']=='member' for gap in contract['decision_gaps']))
        room['resources'][0]['confirmed']=False
        contract=ai.interview_algorithm_context(room,member,member['preference'])
        self.assertTrue(any(gap['scope']=='organizer' for gap in contract['decision_gaps']))


class DecisionReadingTests(unittest.TestCase):
    def test_comparison_explains_real_progress_and_keeps_simulation_separate(self):
        import subprocess
        room=prepared_room();domain.analyze(room)
        room['resources'][0]['cost']=40;domain.invalidate(room,'核对费用')
        visible=domain.view(room,'host')
        visible['agent']={'input_version':room['input_version'],'context_version':room['context_version'],'summary':'已有两个共同方向','tool_results':[{'tool':'simulate','hypothetical':True,'fairness':.8,'input_version':room['input_version'],'summary':'只读比较','candidates':[]}]}
        script="""
          import {comparisonPage} from './web/decision.js';
          let input='';for await(const chunk of process.stdin)input+=chunk;
          const room=JSON.parse(input);
          console.log(comparisonPage({room,zen:true,messages:[],bootstrap:{}}));
        """
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(visible),capture_output=True,text=True,cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(visible['decision_progress']['summary'],result.stdout)
        self.assertIn('与第 1 版相比',result.stdout)
        self.assertIn('人均费用上界',result.stdout)
        self.assertEqual(next(item['fields']['cost_upper'] for item in visible['decision_progress']['change']['changed_options'] if 'cost_upper' in item['fields']),{'before':50.0,'after':40.0})
        self.assertIn('只读模拟',result.stdout)
        self.assertIn('正式规则',result.stdout)
