"""Creation must preserve the goal even when structured model output is imperfect."""
import asyncio,json,unittest,subprocess
from pathlib import Path
from unittest.mock import AsyncMock,patch
from wedecide import ai

class ScenarioDraftTests(unittest.TestCase):
    def complete(self,answers,text='周日晚上去学校附近吃饭，吃什么还没有决定'):
        request=AsyncMock(side_effect=answers)
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            result=asyncio.run(ai.complete({},None,'member','scenario',text))
        return result,request

    def test_one_invalid_candidate_does_not_discard_the_valid_scenario(self):
        result,request=self.complete([json.dumps({'scenario':{'title':'周日晚餐'},'resources':[{'name':'未经核对的建议','duration':0},{'name':'有效草稿','kind':'decision','confirmed':True,'verified':True}]})])
        self.assertEqual(result[1]['scenario']['title'],'周日晚餐')
        self.assertEqual(len(result[1]['resources']),1)
        self.assertFalse(result[1]['resources'][0]['confirmed'])
        self.assertFalse(result[1]['resources'][0]['verified'])
        self.assertTrue(result[1]['warnings'])
        self.assertEqual(request.await_count,1)

    def test_core_format_is_repaired_once_using_schema_and_calendar(self):
        result,request=self.complete([json.dumps({'scenario':{'title':'周日晚餐','date':'这周日'}}),json.dumps({'scenario':{'title':'周日晚餐','date':'2026-10-25'},'resources':[]})])
        self.assertEqual(result[1]['scenario']['date'],'2026-10-25')
        self.assertEqual(request.await_count,2)
        self.assertIn('Scenario Draft JSON Schema',request.call_args.args[1])
        self.assertIn('calendar',request.call_args.args[2][-1]['content'])

    def test_optional_nulls_and_json_with_explanation_are_accepted(self):
        result,request=self.complete(['整理如下：\n```json\n'+json.dumps({'scenario':{'title':'周日晚餐','city':None,'date':None,'description':None},'resources':None})+'\n```'])
        self.assertEqual(result[1]['scenario']['date'],'')
        self.assertEqual(result[1]['scenario']['city'],'')
        self.assertEqual(result[1]['resources'],[])
        self.assertEqual(request.await_count,1)

    def test_unusable_output_keeps_raw_goal_and_does_not_fake_ai_success(self):
        raw='周日晚上去学校附近吃饭，吃什么还没有决定'
        result,request=self.complete(['没有有效 JSON','仍然没有有效 JSON'],raw)
        self.assertEqual(request.await_count,2)
        self.assertEqual(result[1]['scenario']['description'],raw)
        self.assertEqual(result[1]['scenario']['date'],'')
        self.assertEqual(result[1]['mode'],'local')
        self.assertTrue(result[1]['warnings'])

class CreationPayloadTests(unittest.TestCase):
    def test_raw_goal_survives_ai_failure_stale_results_and_manual_overrides(self):
        script="""
          import {buildCreationScenario} from './web/creation.js';
          const raw='这个周日晚上在学校附近吃饭，还没决定吃什么';
          const first=buildCreationScenario({raw,error:'AI 整理失败'});
          const stale=buildCreationScenario({raw,source:'旧的旅游目标',scenario:{title:'旧旅游',city:'旧城市',date:'2026-01-01'}});
          const manual=buildCreationScenario({raw,source:raw,scenario:{title:'AI 名称',description:'整理的背景'},manual:{title:'我的名称',date:'2026-10-25'}});
          console.log(JSON.stringify({raw,first,stale,manual}));
        """
        out=subprocess.run(['node','--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True)
        data=json.loads(out.stdout)
        self.assertEqual(data['first']['description'],data['raw'])
        self.assertEqual(data['stale']['city'],'')
        self.assertEqual(data['stale']['date'],'')
        self.assertNotEqual(data['stale']['title'],'旧旅游')
        self.assertEqual(data['manual']['title'],'我的名称')
        self.assertIn(data['raw'],data['manual']['description'])
        self.assertEqual(data['manual']['date'],'2026-10-25')

if __name__=='__main__':unittest.main()
