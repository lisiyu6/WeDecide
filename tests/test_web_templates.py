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
          console.log(JSON.stringify({editor:preferenceEditor({room,prefStep:0})}));
        """
        result = subprocess.run(
            ['node', '--input-type=module', '-e', script],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        cls.html = json.loads(result.stdout)['editor']
        cls.elements = Elements(cls.html)

    def test_all_five_cards_and_confirmation_are_real_elements(self):
        self.assertEqual(len(self.elements.matching('data-pref-page')), 5)
        self.assertEqual(len(self.elements.matching('data-pref-confirm')), 1)
        self.assertEqual(len(self.elements.matching('data-pref-validation')), 1)

    def test_notes_placeholder_cannot_consume_following_markup(self):
        notes = [attrs for tag, attrs in self.elements.nodes if tag == 'textarea' and attrs.get('name') == 'notes']
        self.assertEqual(len(notes), 1)
        self.assertNotIn('<', notes[0]['placeholder'])
        self.assertNotIn('>', notes[0]['placeholder'])


if __name__ == '__main__':
    unittest.main()
