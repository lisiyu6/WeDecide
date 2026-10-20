"""Room knowledge, continuous supplements and model-assisted calendar conversion."""
import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from wedecide import ai, agent, domain
from wedecide.models import CreateRoom, Preference, Resource


class ContextInputTests(unittest.TestCase):
    def setUp(self):
        self.room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'协作决定'}),8)
        self.room['members'].append(domain.new_member('guest','伙伴','approved'))

    def action(self,uid,action,**payload):
        domain.mutate(self.room,uid,action,payload,self.room['revision'],{'max_members':8})

    def test_optional_knowledge_persists_and_has_its_own_edit_version(self):
        self.assertEqual(self.room.get('knowledge',''),'')
        self.action('host','knowledge',text='可用资料：已有三台设备，预算另行确认。',knowledge_version=0)
        self.assertEqual(domain.view(self.room,'guest')['knowledge'],self.room['knowledge'])
        self.assertEqual(self.room['knowledge_version'],1)
        self.assertEqual(agent.public_context(self.room,'host')['knowledge'],self.room['knowledge'])
        with self.assertRaises(HTTPException) as error:
            self.action('host','knowledge',text='旧页面覆盖',knowledge_version=0)
        self.assertEqual(error.exception.status_code,409)
        self.action('host','knowledge',text='',knowledge_version=1)
        self.assertEqual(self.room['knowledge'],'')

    def test_member_supplements_are_independent_and_private_by_default(self):
        self.action('guest','supplement',text='只给本人 AI 的资料',title='个人补充')
        self.action('host','supplement',text='提供给共同决策的资料',visibility='shared')
        self.assertEqual(len(domain.view(self.room,'guest')['supplements']),2)
        self.assertEqual(len(domain.view(self.room,'host')['supplements']),1)
        public=json.dumps(agent.public_context(self.room,'host'),ensure_ascii=False)
        self.assertIn('提供给共同决策的资料',public)
        self.assertNotIn('只给本人 AI 的资料',public)
        self.assertFalse(self.room['members'][1]['confirmed'])

    def test_new_information_during_vote_does_not_replace_the_locked_proposal(self):
        self.room['state']='VOTING'
        snapshot={'id':'vote','status':'OPEN','deadline':4102444800,'proposal':{'title':'锁定方案'}}
        self.room['vote']=snapshot.copy()
        version=self.room['input_version']
        self.action('guest','supplement',text='投票期间补充的新资料',visibility='shared')
        self.assertEqual(self.room['state'],'VOTING')
        self.assertEqual(self.room['input_version'],version)
        self.assertEqual(self.room['vote'],snapshot)
        self.assertTrue(self.room['supplements'][0]['during_vote'])

    def test_shared_agent_uses_anonymous_confirmed_algorithm_data(self):
        self.room['members'][1].update(confirmed=True,preference=Preference(budget_max=300,criteria=[{'name':'安静','rating':100}],other='不该进入公共推演的原文').model_dump())
        context=agent.planning_context(self.room,'host')
        self.assertEqual(context['algorithm_inputs'][0]['conditions']['budget_max'],300)
        self.assertEqual(context['algorithm_inputs'][0]['conditions']['criteria'][0]['name'],'安静')
        self.assertNotIn('不该进入公共推演的原文',json.dumps(context,ensure_ascii=False))
        self.assertNotIn('member_id',context['algorithm_inputs'][0])
        self.assertNotIn('algorithm_inputs',domain.view(self.room,'host'))

    def test_agent_normalized_fact_updates_wait_for_review_before_calculation(self):
        resource=Resource(id='existing',kind='decision',name='已有方案',cost=50,confirmed=True).model_dump()
        self.room['resources']=[resource]
        updated={**resource,'attributes':{'安静':True}}
        self.room['agent']={'input_version':self.room['input_version'],'context_version':self.room['context_version'],'resources':[],'resource_updates':[updated],'plans':[]}
        self.action('host','agent_draft')
        self.assertEqual(len(self.room['resources']),1)
        self.assertEqual(self.room['resources'][0]['attributes'],{'安静':True})
        self.assertFalse(self.room['resources'][0]['confirmed'])
        self.assertTrue(self.room['agent']['applied'])

    def test_date_conversion_uses_server_clock_and_does_not_save_the_scenario(self):
        from wedecide.context import calendar_context
        clock=calendar_context(datetime(2026,10,20,16,30,tzinfo=timezone.utc))
        self.assertEqual(clock['date'],'2026-10-21')
        request=AsyncMock(return_value=json.dumps({'date':'2026-10-24','explanation':'按当前时区换算三天后。','needs_clarification':False,'question':''}))
        provider={'timeout':5}
        with patch.object(ai,'resolve_provider',return_value=provider),patch.object(ai,'request',request),patch('wedecide.ai.calendar_context',return_value=clock):
            result=asyncio.run(ai.resolve_date({},self.room,'三天后'))
        self.assertEqual(result['date'],'2026-10-24')
        self.assertEqual(result['reference_date'],'2026-10-21')
        sent=request.call_args.args[2][-1]['content']
        self.assertIn('2026-10-21',sent)
        self.assertIn('Asia/Shanghai',sent)
        self.assertEqual(self.room['scenario']['date'],'')

    def test_ambiguous_dates_return_a_question_instead_of_inventing_one(self):
        request=AsyncMock(return_value=json.dumps({'date':'','explanation':'周末包含两天。','needs_clarification':True,'question':'你是指周六还是周日？'}))
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            result=asyncio.run(ai.resolve_date({},self.room,'周末'))
        self.assertTrue(result['needs_clarification'])
        self.assertEqual(result['date'],'')
        self.assertIn('周六',result['question'])

    def test_private_ai_receives_room_knowledge_and_only_visible_supplements(self):
        self.action('host','knowledge',text='项目背景资料',knowledge_version=0)
        self.action('guest','supplement',text='伙伴私密资料')
        self.action('host','supplement',text='房主私密资料')
        request=AsyncMock(return_value='已参考资料')
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request),patch.object(ai.store,'messages',return_value=[]):
            asyncio.run(ai.complete({},self.room,'guest','chat','请继续分析'))
        sent=request.call_args.args[2][-1]['content']
        self.assertIn('项目背景资料',sent)
        self.assertIn('伙伴私密资料',sent)
        self.assertNotIn('房主私密资料',sent)


if __name__=='__main__':unittest.main()
