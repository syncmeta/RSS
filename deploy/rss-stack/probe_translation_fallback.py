"""Small read-only real API probe; never print keys or API error bodies."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from core.models import OpenAIAgent
import json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--model', help='probe this model in memory only; do not change the database')
args = parser.parse_args()

agent = OpenAIAgent.objects.get(pk=int(os.environ['RSS_PROBE_AGENT_ID']))
if args.model:
    agent.model = args.model
print(json.dumps(dict(model=agent.model, valid=agent.valid, max_tokens=agent.max_tokens)), flush=True)
try:
    response = agent._init().with_options(timeout=30, max_retries=0).chat.completions.create(
        model=agent.model,
        messages=[{'role': 'user', 'content': 'Translate Hello into Simplified Chinese. Return only the translation.'}],
        max_tokens=100,
    )
    choice = response.choices[0]
    print(json.dumps(dict(success=True, finish_reason=choice.finish_reason,
                          translation=choice.message.content)), flush=True)
except Exception as error:
    print(json.dumps(dict(success=False, error=type(error).__name__,
                          status=getattr(error, 'status_code', None), code=getattr(error, 'code', None))), flush=True)
    try:
        models = agent._init().with_options(timeout=30, max_retries=0).models.list()
        print(json.dumps(dict(available_lite_models=[m.id for m in models if 'flash' in m.id.lower() and 'lite' in m.id.lower()])), flush=True)
    except Exception as catalog_error:
        print(json.dumps(dict(catalog_error=type(catalog_error).__name__, status=getattr(catalog_error, 'status_code', None))), flush=True)
