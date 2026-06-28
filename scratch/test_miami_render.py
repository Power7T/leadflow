import sys, os, json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_facebook_leads
from jinja2 import Environment, FileSystemLoader

from pathlib import Path
env = Environment(loader=FileSystemLoader(Path(__file__).parents[2] / "templates"))
template = env.get_template("miami_group.html")

leads = get_facebook_leads()
for l in leads:
    try:
        l["interactions"] = json.loads(l.get("interactions_json") or "[]")
    except:
        l["interactions"] = []

class MockRequest:
    def __init__(self):
        self.url = type('obj', (object,), {'path': '/miami-group'})()
        self.query_params = {}

html = template.render(request=MockRequest(), leads=leads)
for line in html.split('\n'):
    if 'data-lead' in line and 'Jaybees' in line:
        print("FOUND DATA-LEAD:")
        print(line)
