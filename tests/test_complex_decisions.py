"""Confirmed preferences must affect real evaluation, including custom itineraries."""
import json
from pathlib import Path
import subprocess
import unittest
from pydantic import ValidationError
from wedecide import domain, engine, agent
from wedecide.models import CreateRoom, Preference, Resource, Rules

ROOT = Path(__file__).resolve().parents[1]


class ComplexDecisionTests(unittest.TestCase):
    def room(self, preference=None, **rules):
        room = domain.new_room('host', CreateRoom(username='房主', scenario={'title':'复杂决策', 'city':'杭州', 'date':'2026-10-24'}, rules=rules), 8)
        room['members'][0].update(preference=Preference(**(preference or {})).model_dump(), confirmed=True)
        room['resources'] = [Resource(id=f'r{i}', name=f'活动{i}', cost=20+i*20, duration=45, start=540, end=1260, confirmed=True).model_dump() for i in range(5)]
        return room

    def evaluate(self, room, index=0):
        resource=room['resources'][index]
        return engine.evaluate(room,[{'resource':resource,'start':600,'end':645}])

    def test_agent_continues_public_goal_without_pending_members_or_private_requirements(self):
        room=self.room({'criteria':[{'name':'私密要求','hard':True}]})
        room['members'].append(domain.new_member('pending','未批准姓名'))
        room['agent']={'goal':'比较长期方案','summary':'已明确优先考虑维护成本','next_step':'补齐资料','questions':['已有资料有哪些？'],'resources':[{'id':'draft','name':'待采纳方向'}]}
        domain.analyze(room)
        context=agent.public_context(room,'host')
        self.assertEqual(context['agent_memory']['goal'],'比较长期方案')
        self.assertEqual(context['pending_drafts']['resources'][0]['id'],'draft')
        self.assertEqual([m['id'] for m in context['members']],['host'])
        raw=json.dumps(context,ensure_ascii=False)
        self.assertNotIn('私密要求',raw)
        self.assertNotIn('未批准姓名',raw)
        self.assertNotIn('dimensions',raw)
        self.assertNotIn('share_token',context)
        room['agent']['applied']=True
        self.assertNotIn('pending_drafts',agent.public_context(room,'host'))

    def test_generic_option_does_not_require_city_or_invent_a_schedule(self):
        room=self.room({'criteria':[{'name':'可扩展','hard':True}]})
        room['scenario'].update(city='',date='')
        option=Resource(id='general',kind='decision',name='可扩展方向',attributes={'可扩展':True},confirmed=True).model_dump()
        room['resources']=[option]
        result=engine.generate(room)['proposals'][0]['evaluation']
        self.assertEqual(result['status'],'FEASIBLE')
        self.assertIsNone(result['start'])
        room['members'][0]['preference']['max_duration']=60
        self.assertEqual(engine.generate(room)['proposals'][0]['evaluation']['status'],'UNKNOWN')

    def test_hard_attribute_distinguishes_missing_false_and_true(self):
        room=self.room({'criteria':[{'name':'自助','hard':True}]})
        self.assertEqual(self.evaluate(room)['status'],'UNKNOWN')
        room['resources'][0]['attributes']={'自助':False}
        self.assertEqual(self.evaluate(room)['status'],'INFEASIBLE')
        room['resources'][0]['attributes']={'自助':True}
        self.assertEqual(self.evaluate(room)['status'],'FEASIBLE')

    def test_soft_attribute_and_price_preference_affect_scores_without_hardening(self):
        room=self.room({'criteria':[{'name':'安静','rating':100}], 'cost_preference':'lower'})
        room['resources'][0]['attributes']={'安静':True}
        room['resources'][1]['attributes']={'安静':False}
        cheap,loud=self.evaluate(room,0),self.evaluate(room,1)
        self.assertEqual(cheap['status'],loud['status'])
        self.assertGreater(cheap['score'],loud['score'])
        self.assertTrue(any(d['label']=='安静' for d in cheap['utilities'][0]['dimensions']))
        self.assertIsNone(room['members'][0]['preference']['budget_max'])

    def test_all_scope_checks_every_activity_and_neutral_cannot_be_hard(self):
        room=self.room({'criteria':[{'name':'无障碍','hard':True,'scope':'all'}]})
        for resource in room['resources']:resource['attributes']={'无障碍':True}
        room['resources'][1]['attributes']['无障碍']=False
        itinerary=[{'resource':room['resources'][i],'start':600+i*75,'end':645+i*75} for i in range(2)]
        self.assertEqual(engine.evaluate(room,itinerary)['status'],'INFEASIBLE')
        with self.assertRaises(ValidationError):Preference(criteria=[{'name':'自助','hard':True,'rating':50}])

    def test_three_to_five_activity_search_is_bounded_and_explicit(self):
        room=self.room(min_activities=3,max_activities=5)
        result=engine.generate(room)
        self.assertTrue(result['proposals'])
        self.assertTrue(all(3<=len(p['itinerary'])<=5 for p in result['proposals']))
        self.assertIn('bounded',result)
        self.assertLessEqual(result['considered'],10000)
        self.assertIn('最多',result['scope'])
        self.assertEqual(len({p['code'] for p in result['proposals']}),len(result['proposals']))
        with self.assertRaises(ValidationError):Rules(min_activities=4,max_activities=2)

    def test_manual_plan_reappears_and_is_rechecked_after_preference_change(self):
        room=self.room()
        plan={'id':'custom','title':'先活动0再活动1','description':'按这个顺序安排','steps':[{'resource_id':'r0','start':600},{'resource_id':'r1','start':720}]}
        domain.mutate(room,'host','plans',{'plans':[plan]},room['revision'],{'max_members':8})
        first=engine.generate(room)
        proposal=next(p for p in first['proposals'] if p.get('plan_id')=='custom')
        self.assertEqual(proposal['evaluation']['status'],'FEASIBLE')
        room['members'][0]['preference']['budget_max']=10
        second=engine.generate(room)
        self.assertEqual(next(p for p in second['proposals'] if p.get('plan_id')=='custom')['evaluation']['status'],'INFEASIBLE')
        self.assertEqual(proposal['itinerary'][1]['start'],720)

    def test_manual_plan_overlap_and_too_short_transfer_fail_evaluation(self):
        room=self.room()
        itinerary=[{'resource':room['resources'][0],'start':600,'end':645},{'resource':room['resources'][1],'start':650,'end':695}]
        evaluation=engine.evaluate(room,itinerary)
        self.assertEqual(evaluation['status'],'INFEASIBLE')
        self.assertTrue(any(v['field']=='transfer' for v in evaluation['violations']))

    def test_attribute_names_of_other_members_remain_private(self):
        room=self.room({'criteria':[{'name':'私密要求','hard':True}]})
        room['members'].append(domain.new_member('other','其他人','approved'))
        room['members'][1].update(preference=Preference().model_dump(),confirmed=True)
        domain.analyze(room)
        visible=domain.view(room,'other')
        self.assertNotIn('私密要求',json.dumps(visible,ensure_ascii=False))
        self.assertIn('私密要求',json.dumps(domain.view(room,'host'),ensure_ascii=False))
