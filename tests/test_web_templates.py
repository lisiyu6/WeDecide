"""Render real browser templates with Node and check their HTML structure."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def matching(self, attribute):
        return [attrs for _, attrs in self.nodes if attribute in attrs]


class PreferenceTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = """
          import {preferenceEditor} from './web/preferences.js';
          const room={id:'test-room',state:'COLLECTING',scenario:{title:'共同决定'},resources:[],
            me:{preference:null,preference_version:0,confirmed:false}};
          console.log(JSON.stringify({editor:preferenceEditor({room,prefStep:0,messages:[]})}));
        """
        result = subprocess.run(
            ['node', '--input-type=module', '-e', script],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        cls.html = json.loads(result.stdout)['editor']
        cls.elements = Elements(cls.html)

    def test_ai_interview_and_real_editable_table_have_separate_confirmation(self):
        forms=[attrs.get('id') for tag,attrs in self.elements.nodes if tag=='form']
        self.assertIn('interview-form',forms)
        self.assertIn('preference-form',forms)
        self.assertIn('data-pref-summary',self.html)
        self.assertIn('data-pref-edit-area hidden',self.html)
        self.assertEqual(len(self.elements.matching('data-pref-confirm')), 1)
        self.assertEqual(len(self.elements.matching('data-pref-validation')), 1)

    def test_swipe_card_stays_present_after_summary_and_confirmation(self):
        script="""
          import {preferenceEditor} from './web/preferences.js';
          const room={id:'r',state:'COLLECTING',scenario:{title:'共同决定'},resources:[],me:{preference:{},preference_version:1,confirmed:true}};
          const messages=[{id:2,role:'assistant',kind:'interview',metadata:{preference_version:1,draft:{},interview:{ready:true,summary:'已整理你的想法'}}}];
          console.log(JSON.stringify([preferenceEditor({room,messages:[],prefStep:0}),preferenceEditor({room,messages,prefStep:0})]));
        """
        output=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        for html in json.loads(output.stdout):
            elements=Elements(html)
            self.assertEqual(len(elements.matching('data-interview-card')),1)
            self.assertNotIn('hidden',elements.matching('data-interview-panel')[0])
            self.assertEqual(len(elements.matching('data-choice')),2)

    def test_notes_textarea_cannot_consume_the_confirmation_controls(self):
        notes = [attrs for tag, attrs in self.elements.nodes if tag == 'textarea' and attrs.get('name') == 'notes']
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(self.elements.matching('data-pref-confirm')),1)
        self.assertEqual(self.html.count('<textarea'),self.html.count('</textarea>'))


class AccountTemplateTests(unittest.TestCase):
    def test_login_and_registration_only_require_username_and_password(self):
        script = """
          import * as pages from './web/pages.js';
          const bootstrap={account:null,has_legacy_rooms:true};
          console.log(JSON.stringify(['login','register'].map(mode=>pages.accountPage?pages.accountPage(bootstrap,mode,'/new'):'')));
        """
        result = subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        for html in json.loads(result.stdout):
            with self.subTest(html=html[:40]):
                elements=Elements(html)
                fields=[attrs['name'] for tag,attrs in elements.nodes if tag=='input' and 'name' in attrs]
                self.assertEqual(fields,['username','password'])
                self.assertEqual(len([attrs for tag,attrs in elements.nodes if tag=='form' and attrs.get('id')=='account-form']),1)


class RoomSettingsTemplateTests(unittest.TestCase):
    def test_delete_button_is_available_only_to_host_in_all_room_phases(self):
        script = """
          import {settings} from './web/room-views.js';
          const room={id:'room',host_id:'host',me:{id:'host'},members:[],resources:[],
            scenario:{title:'开错的空间'},rules:{},round:0,vote:null,vote_history:[]};
          const state={room,bootstrap:{providers:[],limits:{max_members:8}}};
          console.log(JSON.stringify(['COLLECTING','VOTING','CANCELLED','APPROVED'].flatMap(phase=>
            ['host','member'].map(id=>{room.state=phase;room.me.id=id;return {phase,id,html:settings(state)};}))));
        """
        result = subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        for sample in json.loads(result.stdout):
            with self.subTest(phase=sample['phase'], identity=sample['id']):
                buttons=[attrs for tag,attrs in Elements(sample['html']).nodes if tag=='button' and attrs.get('data-action')=='delete-room']
                self.assertEqual(len(buttons), 1 if sample['id']=='host' else 0)
                if buttons:
                    self.assertNotIn('disabled', buttons[0])


class DecisionFlowTemplateTests(unittest.TestCase):
    def test_comparison_codes_and_details_survive_a_different_fairness_order(self):
        from wedecide import domain
        from wedecide.models import CreateRoom, Preference, Resource
        room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'统一决策'}),8)
        room['members'][0].update(preference=Preference().model_dump(),confirmed=True)
        room['resources']=[Resource(id=str(i),kind='decision',name=f'备选{i}',confirmed=True).model_dump() for i in range(2)]
        domain.analyze(room)
        room['proposals'][0]['evaluation'].update(average=100,minimum=0)
        room['proposals'][1]['evaluation'].update(average=50,minimum=50)
        script="""
          import {comparisonPage} from './web/decision.js';
          import {overview} from './web/room-views.js';
          let raw='';for await(const chunk of process.stdin)raw+=chunk;
          const room=JSON.parse(raw),state={room,messages:[],simFairness:1};
          console.log(JSON.stringify({compare:comparisonPage(state),overview:overview(state)}));
        """
        rendered=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(domain.view(room,'host')),cwd=ROOT,check=True,capture_output=True,text=True)
        html=json.loads(rendered.stdout)
        compare=html['compare']
        self.assertLess(compare.index('方案 B · V1'),compare.index('方案 A · V1'))
        details=[x for x in Elements(compare).matching('data-proposal-detail')]
        self.assertEqual(len(details),2)
        self.assertIn('查看具体方案、费用依据与我的匹配',compare)
        self.assertNotIn('自定义活动行程',compare)
        self.assertNotIn('YOUR NEXT STEP',html['overview'])
        self.assertNotIn('请房主先添加候选活动',html['overview'])
        self.assertEqual(domain.display_view(room)['proposals'][0]['evaluation']['kind'],'decision')


class ContinuousInputTemplateTests(unittest.TestCase):
    def test_drawer_and_optional_date_conversion_are_part_of_real_forms(self):
        script="""
          import {contextDrawer,dateField} from './web/context.js';
          import {creation} from './web/pages.js';
          const room={state:'COLLECTING',host_id:'host',me:{id:'host',status:'approved'},members:[],supplements:[]};
          console.log(JSON.stringify({knowledge:contextDrawer({room,contextOpen:true,contextTab:'knowledge'}),notes:contextDrawer({room,contextOpen:true}),create:creation({account:{username:'test'},limits:{max_members:8}})}));
        """
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        html=json.loads(result.stdout)
        self.assertEqual(len([attrs for tag,attrs in Elements(html['knowledge']).nodes if tag=='form' and attrs.get('id')=='knowledge-form']),1)
        self.assertIn('name="visibility"',html['notes'])
        self.assertIn('<option value="private" selected>仅自己</option>',html['notes'])
        self.assertIn('data-action="resolve-date"',html['create'])
        self.assertIn('name="date_expression"',html['create'])


class SideCardTemplateTests(unittest.TestCase):
    def test_left_suggestions_and_right_information_have_separate_content_and_drafts(self):
        script="""
          import {contextDrawer} from './web/context.js';
          const room={code:'r',state:'COLLECTING',host_id:'host',members:[{id:'host',name:'房主'}],me:{id:'host',status:'approved'},supplements:[{id:'p',kind:'suggestion',member_id:'host',text:'公开候选想法',visibility:'shared',at:1},{id:'n',kind:'information',member_id:'host',text:'私密补充文字',visibility:'private',at:1}]};
          const base={room,contextOpen:true,contextTab:'supplements',suggestionDraft:{text:'尚未提交的提议'},contextDraft:{text:'尚未提交的补充'}};
          console.log(JSON.stringify({left:contextDrawer({...base,contextSide:'left'}),right:contextDrawer({...base,contextSide:'right'})}));
        """
        output=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        pages=json.loads(output.stdout)
        self.assertIn('id="suggestion-form"',pages['left'])
        self.assertIn('尚未提交的提议',pages['left'])
        self.assertIn('公开候选想法',pages['left'])
        self.assertNotIn('私密补充文字',pages['left'])
        self.assertNotIn('尚未提交的补充',pages['left'])
        self.assertIn('id="supplement-form"',pages['right'])
        self.assertIn('私密补充文字',pages['right'])
        self.assertNotIn('公开候选想法',pages['right'])
        self.assertNotIn('尚未提交的提议',pages['right'])


class DecisionGuidanceTests(unittest.TestCase):
    def test_next_step_tracks_confirmed_data_and_real_vote_state(self):
        script="""
          import {decisionFlow,taskPanel} from './web/flow.js';
          const guided=state=>decisionFlow(state)+taskPanel(state);
          const room={code:'R',state:'COLLECTING',host_id:'h',input_version:1,context_version:1,me:{id:'h',confirmed:false},members:[{id:'h',status:'approved',confirmed:false}],resources:[],proposals:[]};
          const initial=guided({room,tab:'overview'});
          room.me.confirmed=true;room.members[0].confirmed=true;room.resources=[{confirmed:true}];room.proposals=[{id:'p',input_version:1,evaluation:{status:'FEASIBLE'}}];room.selected_id='p';room.state='COMPARING';
          const ready=guided({room,tab:'overview'});
          room.state='VOTING';room.vote={my_vote:null};const voting=guided({room,tab:'overview'});
          room.state='APPROVED';const finished=guided({room,tab:'overview'});
          console.log(JSON.stringify({initial,ready,voting,finished}));
        """
        out=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
        pages=json.loads(out.stdout)
        self.assertIn('view=preferences',pages['initial'])
        self.assertIn('确认',pages['initial'])
        self.assertIn('正式投票',pages['ready'])
        self.assertIn('view=vote',pages['voting'])
        self.assertIn('view=result',pages['finished'])
        for html in pages.values():self.assertEqual(html.count('aria-current="step"'),1)


class ZenFlowTemplateTests(unittest.TestCase):
    def test_comparison_keeps_all_options_and_one_mobile_focus_with_reachable_navigation(self):
        from wedecide import domain
        from wedecide.models import CreateRoom,Preference,Resource
        room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'禅模式'}),8)
        room['members'][0].update(confirmed=True,preference=Preference().model_dump())
        room['resources']=[Resource(id=str(i),kind='decision',name=f'备选{i}',confirmed=True).model_dump() for i in range(3)]
        domain.analyze(room)
        script="""
          import {comparisonPage} from './web/decision.js';
          import {layout} from './web/room-views.js';
          let raw='';for await(const chunk of process.stdin)raw+=chunk;
          const room=JSON.parse(raw),state={room,zen:true,messages:[],tab:'compare',bootstrap:{account:null,providers:[],limits:{max_members:8}}};
          console.log(JSON.stringify({compare:comparisonPage(state),layout:layout(state)}));
        """
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(domain.view(room,'host')),cwd=ROOT,check=True,capture_output=True,text=True)
        html=json.loads(result.stdout)
        proposals=Elements(html['compare']).matching('data-proposal-id')
        self.assertEqual(len(proposals),3)
        self.assertEqual(sum('is-focused' in element.get('class','') for element in proposals),1)
        self.assertIn('aria-label="选择要查看的方案"',html['compare'])
        self.assertIn('aria-label="空间操作"',html['layout'])
        self.assertIn('退出禅模式',html['layout'])



class DisclosureContent(HTMLParser):
    """Read the default content of native disclosures, without relying on CSS."""
    def __init__(self, html):
        super().__init__()
        self.closed = 0
        self.summary = 0
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'details':
            self.closed += 1
        if tag == 'summary':
            self.summary += 1

    def handle_endtag(self, tag):
        if tag == 'details':
            self.closed -= 1
        if tag == 'summary':
            self.summary -= 1

    def handle_data(self, data):
        if not self.closed or self.summary:
            self.text.append(data)

    def visible(self):
        return ' '.join(self.text)


class FocusedJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from wedecide import domain
        from wedecide.models import CreateRoom,Preference,Resource
        room=domain.new_room('host',CreateRoom(username='房主',scenario={'title':'统一体验'}),8)
        room['members'][0].update(confirmed=True,preference=Preference().model_dump())
        room['resources']=[Resource(id='a',kind='decision',name='已核对的选择',description='先讨论目标，再分工执行',cost=100,confirmed=True,source='核对依据全文').model_dump()]
        domain.analyze(room)
        room['selected_id']=room['proposals'][0]['id']
        room['agent']={'summary':'Agent 的当前结论','next_step':'核对已选方案','goal':'共同决定','questions':['仍待澄清的背景全文'],'input_version':room['input_version'],'context_version':room['context_version'],'enabled':True}
        room['events']=[{'at':1,'text':'历史事件全文','kind':'test'}]
        negotiation=domain.view(room,'host')
        negotiation['requests']=[{'id':'pending-1','status':'PENDING','field':'budget_max','before':100,'after':120,'reason':'可选调整说明','preference_version':1,'expires':2000000000},{'id':'past-1','status':'REJECTED','field':'budget_max','before':100,'after':150,'reason':'旧调整历史全文','preference_version':1,'expires':2000000000}]
        negotiation['feedback']=[{'summary':'允许公开的摘要全文','version':1}]
        domain.mutate(room,'host','start_vote',{},room['revision'],{})
        voting=domain.view(room,'host')
        voting['proposals'][0]['title']='后来出现的草稿标题'
        domain.mutate(room,'host','vote',{'session_id':room['vote']['id'],'choice':'accept','reason':'私密理由全文'},room['revision'],{})
        finished=domain.view(room,'host')
        script="""
          import {overview,negotiate,vote,result} from './web/room-views.js';
          let raw='';for await(const chunk of process.stdin)raw+=chunk;
          const [n,v,r]=JSON.parse(raw),base={zen:true,messages:[{id:1,role:'user',kind:'interview',content:'旧访谈原文',created:1,metadata:{}},{id:2,role:'assistant',kind:'negotiate',content:'继续讨论当前方案',created:2,metadata:{}}],bootstrap:{},chatMode:'private'};
          console.log(JSON.stringify({overview:overview({...base,room:n}),negotiate:negotiate({...base,room:n}),vote:vote({...base,room:v}),result:result({...base,room:r})}));
        """
        output=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps([negotiation,voting,finished]),cwd=ROOT,check=True,capture_output=True,text=True)
        cls.pages=json.loads(output.stdout)

    def test_overview_exposes_actual_selected_plan_and_folds_followup_questions(self):
        html=self.pages['overview'];visible=DisclosureContent(html).visible()
        self.assertIn('已核对的选择',visible)
        self.assertIn('Agent 的当前结论',visible)
        self.assertNotIn('仍待澄清的背景全文',visible)
        self.assertIn('仍待澄清的背景全文',html)

    def test_negotiation_prioritizes_pending_decisions_over_optional_forms_and_history(self):
        html=self.pages['negotiate'];visible=DisclosureContent(html).visible()
        self.assertIn('可选调整说明',visible)
        self.assertIn('继续讨论当前方案',visible)
        self.assertNotIn('旧访谈原文',html)
        self.assertNotIn('旧调整历史全文',visible)
        self.assertNotIn('允许公开的摘要全文',visible)
        forms=[attrs.get('id') for tag,attrs in Elements(html).nodes if tag=='form']
        self.assertEqual(forms.count('chat-form'),1)
        self.assertEqual(forms.count('feedback-form'),1)
        self.assertIn('data-id="pending-1"',html)
        self.assertIn('旧调整历史全文',html)

    def test_voting_uses_frozen_plan_and_one_real_ballot_with_optional_details_closed(self):
        html=self.pages['vote'];visible=DisclosureContent(html).visible()
        self.assertIn('已核对的选择',visible)
        self.assertNotIn('后来出现的草稿标题',html)
        self.assertNotIn('核对依据全文',visible)
        elements=Elements(html)
        self.assertEqual(len([x for tag,x in elements.nodes if tag=='form' and x.get('id')=='vote-form']),1)
        self.assertEqual({x.get('value') for tag,x in elements.nodes if tag=='input' and x.get('name')=='choice'},{'accept','revise','reject'})
        self.assertEqual(len(elements.matching('data-deadline')),1)

    def test_result_leads_with_final_choice_and_keeps_records_and_participation_optional(self):
        html=self.pages['result'];visible=DisclosureContent(html).visible()
        self.assertIn('已核对的选择',visible)
        self.assertIn('先讨论目标，再分工执行',visible)
        self.assertNotIn('历史事件全文',visible)
        self.assertNotIn('我的实际参与意愿',visible)
        self.assertIn('历史事件全文',html)
        self.assertIn('id="attendance-form"',html)
        self.assertIn('/report',html)

if __name__ == '__main__':
    unittest.main()
