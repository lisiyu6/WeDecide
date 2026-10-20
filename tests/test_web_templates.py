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
          const room={id:'test-room',state:'COLLECTING',resources:[],
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
        self.assertGreaterEqual(len([tag for tag,_ in self.elements.nodes if tag=='table']),2)
        self.assertEqual(len(self.elements.matching('data-pref-confirm')), 1)
        self.assertEqual(len(self.elements.matching('data-pref-validation')), 1)

    def test_notes_placeholder_cannot_consume_following_markup(self):
        notes = [attrs for tag, attrs in self.elements.nodes if tag == 'textarea' and attrs.get('name') == 'notes']
        self.assertEqual(len(notes), 1)
        self.assertNotIn('<', notes[0]['placeholder'])
        self.assertNotIn('>', notes[0]['placeholder'])


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
        self.assertIn('方案事实、步骤、费用、我的匹配与冲突',compare)
        self.assertNotIn('自定义活动行程',compare)
        self.assertNotIn('YOUR NEXT STEP',html['overview'])
        self.assertNotIn('请房主先添加候选活动',html['overview'])
        self.assertEqual(domain.display_view(room)['proposals'][0]['evaluation']['kind'],'decision')


if __name__ == '__main__':
    unittest.main()
