"""Checks for one group workflow, automatic shared work and independent private input."""
import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from wedecide import ai,agent,domain,store
from wedecide.models import AIInput,CreateRoom,Preference,Resource

app=importlib.import_module('wedecide.app')
ROOT=Path(__file__).resolve().parents[1]

class GroupJourneyTests(unittest.TestCase):
    def room(self):
        value=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'一起决定'}),8)
        value['code']='GROUP001'
        return value

    def test_shared_work_starts_without_a_launch_and_does_not_repeat_unchanged_input(self):
        async def run():
            room=self.room();queue=AsyncMock()
            with patch.object(app,'queue_room_ai',queue),patch.object(ai,'resolve_provider',return_value={"enabled":True}),patch.object(store,'settings',return_value={}),patch.object(app.coordinator,'pending',{(room['id'],'host'):object()}):
                await app.maybe_advance_agent(room)
                queue.assert_awaited_once()  # Host private input must not block public organization.
                room['agent'].update(attempted_input_version=room['input_version'],attempted_context_version=room['context_version'])
                queue.reset_mock();await app.maybe_advance_agent(room);queue.assert_not_awaited()
                room['context_version']+=1
                await app.maybe_advance_agent(room);queue.assert_awaited_once()
                queue.reset_mock();room['agent'].update(attempted_context_version=room['context_version']);room['round']=1;room['state']='NEGOTIATING';room['members'][0]['confirmed']=True
                await app.maybe_advance_agent(room);queue.assert_awaited_once()
                queue.reset_mock();room['state']='VOTING'
                await app.maybe_advance_agent(room);queue.assert_not_awaited()
        asyncio.run(run())

    def test_host_can_answer_a_card_while_shared_work_is_still_running(self):
        async def run():
            room=self.room();release=asyncio.Event();coordinator=ai.Coordinator()
            async def shared(*args):
                await release.wait()
                return '共同进展',{'agent':{'summary':'共同进展','resources':[],'plans':[]},'mode':'ai'}
            async def private(*args):
                await release.wait()
                return '个人回答已整理',{'draft':{},'interview':{'ready':True,'summary':'个人草稿'},'mode':'ai'}
            with tempfile.TemporaryDirectory(prefix='wedecide-group-') as directory:
                with patch.object(store,'DATA_DIR',Path(directory)),patch.object(store,'DB_PATH',Path(directory)/'check.sqlite'),patch.object(app,'coordinator',coordinator),patch.object(app.agent,'run',side_effect=shared),patch.object(ai,'complete',side_effect=private):
                    store.init()
                    with store.transaction() as db:
                        db.execute('INSERT INTO rooms VALUES(?,?,?,?,?,?)',(room['id'],room['code'],room['state'],room['revision'],room['updated'],store.dumps(room)))
                    await app.queue_room_ai(room,'host',AIInput(kind='agent',text='整理共同资料'))
                    await app.queue_room_ai(room,'host',AIInput(kind='interview',text='我的独立回答'))
                    self.assertIn(app.shared_ai_key(room),coordinator.pending)
                    self.assertIn((room['id'],'host'),coordinator.pending)
                    tasks=list(coordinator.pending.values());release.set()
                    await asyncio.wait_for(asyncio.gather(*tasks),timeout=2)
                    with store.connect() as db:
                        saved=store.load_room(db,room['id'])
                    self.assertEqual(saved['agent']['summary'],'共同进展')
                    self.assertFalse(saved['members'][0]['confirmed'])
                    self.assertFalse(coordinator.pending)
        asyncio.run(run())

    def test_reorganizing_current_results_does_not_reset_the_hosts_selected_plan(self):
        room=self.room();room['members'][0].update(confirmed=True,preference=Preference().model_dump())
        room['resources']=[Resource(id='option',kind='decision',name='已核对方向',cost=50,confirmed=True).model_dump()]
        domain.analyze(room);room['selected_id']=room['proposals'][0]['id']
        request=AsyncMock(side_effect=[json.dumps({'tool':'analyze','summary':'查看共同校核'}),json.dumps({'tool':'respond','summary':'现有方案仍可继续比较'})])
        with patch.object(ai,'resolve_provider',return_value={'timeout':5}),patch.object(ai,'request',request):
            text,metadata=asyncio.run(agent.run({},room,'host','结合现有结果解释取舍'))
        self.assertIsNone(metadata['_prepared_analysis'])
        self.assertEqual(room['analysis_version'],1)
        self.assertEqual(room['selected_id'],room['proposals'][0]['id'])

    def test_pages_form_one_journey_with_no_separate_assistant_launch(self):
        room=self.room()
        script="""
          import {layout} from './web/room-views.js';
          import {defaultDecisionView} from './web/flow.js';
          let input='';for await(const chunk of process.stdin)input+=chunk;
          const room=JSON.parse(input),base={room,zen:true,messages:[],tab:'overview',bootstrap:{providers:[],limits:{max_members:8}}};
          const overview=layout(base),preferences=layout({...base,tab:'preferences'});
          const routes=[defaultDecisionView(room)];room.me.confirmed=true;routes.push(defaultDecisionView(room));room.state='VOTING';routes.push(defaultDecisionView(room));room.state='APPROVED';routes.push(defaultDecisionView(room));
          console.log(JSON.stringify({overview,preferences,routes}));
        """
        output=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(domain.view(room,'host')),cwd=ROOT,check=True,capture_output=True,text=True)
        pages=json.loads(output.stdout)
        self.assertNotIn('启动决策 Agent',pages['overview'])
        self.assertNotIn('id="agent-form"',pages['overview'])
        self.assertIn('大家的共同决定',pages['overview'])
        self.assertIn('查看伙伴准备情况',pages['overview'])
        self.assertIn('我们一起决定',pages['preferences'])
        self.assertIn('data-interview-card',pages['preferences'])
        self.assertEqual(pages['routes'],['preferences','overview','vote','result'])

if __name__=='__main__':unittest.main()
