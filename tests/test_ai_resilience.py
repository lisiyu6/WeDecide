"""AI assistance should make progress without infinite questions or format retry loops."""
import asyncio,json,unittest
from unittest.mock import AsyncMock,patch
import httpx
from wedecide import ai,agent,domain
from wedecide.models import CreateRoom,Preference,Provider

def room():
    value=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'一起决定'}),8)
    return value

def question(text='更想安静聊天还是热闹一点？'):
    return {'ready':False,'targets':['criteria'],'purpose':'用于比较方案与具体偏好的匹配。','question':text,'left':'安静聊天','right':'热闹一点','summary':'已了解目前的偏好。','draft':{'budget_max':200}}

class InterviewProgressTests(unittest.TestCase):
    def complete(self,history,answers,**options):
        current=room();request=AsyncMock(side_effect=[json.dumps(x,ensure_ascii=False) if isinstance(x,dict) else x for x in answers])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request),patch.object(ai.store,'messages',return_value=history):
            result=asyncio.run(ai.complete({},current,'host','interview','我的回答',**options))
        return result,request

    def history(self,count):
        return [{'role':'assistant','kind':'interview','content':'问题','metadata':{'preference_version':0,'interview':question('不同问题'+str(i)),'draft':{'budget_max':200}}} for i in range(count)]

    def test_four_questions_end_in_a_draft_even_if_model_keeps_asking(self):
        (text,metadata),request=self.complete(self.history(4),[question('再来第五个问题')])
        self.assertTrue(metadata['interview']['ready'])
        self.assertEqual(metadata['interview']['question'],'')
        self.assertEqual(metadata['draft']['budget_max'],200)
        self.assertEqual(metadata['interview_progress']['reason'],'question_limit')
        self.assertEqual(request.await_count,1)

    def test_repeated_question_is_not_shown_again(self):
        (text,metadata),_=self.complete(self.history(1),[question('不同问题0')])
        self.assertTrue(metadata['interview']['ready'])
        self.assertEqual(metadata['interview_progress']['reason'],'repeated_question')

    def test_explicit_finish_stops_questions_and_repairs_schema_once(self):
        (text,metadata),request=self.complete([],['格式坏了',question()],interview_action='finish')
        self.assertEqual(request.await_count,2)
        self.assertTrue(metadata['interview']['ready'])
        self.assertEqual(metadata['interview_progress']['reason'],'user_finished')

    def test_bad_format_preserves_last_draft_and_explains_that_no_new_conditions_were_guessed(self):
        (text,metadata),request=self.complete(self.history(1),['bad format','still bad'])
        self.assertEqual(request.await_count,2)
        self.assertTrue(metadata['interview']['ready'])
        self.assertEqual(metadata['draft']['budget_max'],200)
        self.assertEqual(metadata['mode'],'preserved')
        self.assertTrue(metadata['warnings'])

    def test_continue_explicitly_starts_another_bounded_round(self):
        (text,metadata),_=self.complete(self.history(4),[question('继续一轮的新问题')],interview_action='continue')
        self.assertFalse(metadata['interview']['ready'])
        self.assertEqual(metadata['interview_progress']['asked'],1)

class AlgorithmContractTests(unittest.TestCase):
    def test_questions_are_grounded_in_real_fields_and_candidate_evidence(self):
        from wedecide.models import Resource
        current=room();member=current['members'][0]
        current['resources']=[Resource(id='a',kind='decision',name='甲',cost=50,confirmed=True,attributes={'安静':False}).model_dump(),Resource(id='b',kind='decision',name='乙',cost=None,confirmed=False).model_dump()]
        preference=Preference(budget_max=100,criteria=[{'name':'安静','hard':True}]).model_dump()
        contract=ai.interview_algorithm_context(current,member,preference)
        self.assertIn('budget_max',contract['known_fields'])
        self.assertNotIn('available_start',contract['supported_fields'])
        self.assertEqual([item['value'] for item in contract['candidate_axes'][0]['evidence']],[False,None])
        self.assertTrue(contract['candidate_fact_gaps'])
        self.assertFalse(member['confirmed'])

    def test_question_without_calculation_target_is_rejected_instead_of_becoming_a_card(self):
        policy={'reason':'','seen':[]};contract={'supported_fields':{'cost_preference':'费用倾向'}}
        answer=question();answer.update(targets=[],purpose='')
        with self.assertRaises(ai.AlgorithmQuestionError):ai.read_interview(json.dumps(answer),policy,contract)
        answer.update(targets=['available_start'],purpose='开始时间')
        with self.assertRaises(ai.AlgorithmQuestionError):ai.read_interview(json.dumps(answer),policy,contract)
        answer.update(targets=['cost_preference'],purpose='用于比较费用取舍。')
        self.assertEqual(ai.read_interview(json.dumps(answer),policy,contract)['targets'],['cost_preference'])

class StructuredGatewayTests(unittest.TestCase):
    def test_json_mode_is_used_and_an_unsupported_parameter_falls_back_only_once(self):
        provider=Provider(endpoint='https://fixture.invalid/v1',model='format-test').model_dump()
        bodies=[]
        def handler(request):
            body=json.loads(request.content);bodies.append(body)
            if 'response_format' in body:return httpx.Response(400,json={'error':{'message':'response_format json_object is not supported'}})
            return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
        original=httpx.AsyncClient
        def client(**options):return original(transport=httpx.MockTransport(handler),**options)
        with patch.object(ai.httpx,'AsyncClient',side_effect=client):
            first=asyncio.run(ai.request(provider,'Interview JSON Schema: {}',[{'role':'user','content':'json'}]))
            second=asyncio.run(ai.request(provider,'Interview JSON Schema: {}',[{'role':'user','content':'json'}]))
        self.assertEqual(first,'{}');self.assertEqual(second,'{}')
        self.assertEqual(len(bodies),3)
        self.assertEqual(bodies[0]['response_format'],{'type':'json_object'})
        self.assertNotIn('response_format',bodies[1])
        self.assertNotIn('response_format',bodies[2])

    def test_agent_keeps_real_tool_result_if_explanation_cannot_be_repaired(self):
        current=room();current['members'][0].update(confirmed=True,preference=Preference().model_dump())
        from wedecide.models import Resource
        current['resources']=[Resource(id='r',name='已核对的方向',kind='decision',cost=50,confirmed=True).model_dump()]
        request=AsyncMock(side_effect=[json.dumps({'tool':'analyze','summary':'先校核'}),'bad format','still bad'])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            text,metadata=asyncio.run(agent.run({},current,'host','请推进决策'))
        self.assertEqual(request.await_count,3)
        self.assertTrue(metadata['_prepared_analysis']['proposals'])
        self.assertTrue(metadata['agent']['notice'])
        self.assertEqual(metadata['mode'],'preserved')
        self.assertEqual(current['analysis_version'],0)

if __name__=='__main__':unittest.main()
