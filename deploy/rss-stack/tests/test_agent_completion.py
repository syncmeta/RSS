"""Exercise the production completion method without Django or live API calls."""
import ast
import logging
import os
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rssbox-patches'))
from translation_integrity import translation_error, protect_media


class CompletionTests(unittest.TestCase):
    def agent(self, content, reason='stop', fallback=None, limit=100000,
              model='test', free_models=None, calls=None):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'rssbox-patches/agent.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OpenAIAgent')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'completions')
        env = dict(os=os, logger=logging.getLogger('test'), settings=NS(OPENAI_API_MAX_RETRIES=0),
                   timezone=NS(now=lambda: 'now'), get_token_count=lambda s: len(s or ''),
                   translation_error=translation_error, chunk_html_on_blocks=lambda t, n: ['first', 'second'])
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<production completions>', 'exec'), env)
        response = NS(choices=[NS(finish_reason=reason, message=NS(content=content))], usage=NS(total_tokens=5))
        def create(**kwargs):
            if calls is not None:
                calls.append(kwargs)
            return response
        client = NS(chat=NS(completions=NS(create=create)))
        client.with_options = lambda **kw: client
        agent = NS(name='test', model=model, max_tokens=limit, merge_system_prompt=False,
                   advanced_params={}, EXTRA_HEADERS={}, _init=lambda: client,
                   _wait_for_rate_limit=lambda: None,
                   _openrouter_free_model_fallbacks=lambda: free_models or [],
                   _fallback_agent=lambda: fallback, save=lambda **kw: None)
        agent.completions = lambda **kw: env['completions'](agent, **kw)
        return agent

    def test_classification_falls_back(self):
        fallback = self.agent('你好')
        primary = self.agent('User Safety: unsafe\nSafety Categories: Political', fallback=fallback)
        result = primary.completions(text='Hello', system_prompt='', _translation_guard=True)
        self.assertEqual(result['text'], '你好')

    def test_truncation_falls_back(self):
        primary = self.agent('partial', reason='length', fallback=self.agent('完整译文'))
        self.assertEqual(primary.completions(text='Hello', system_prompt='')['text'], '完整译文')

    def test_missing_media_falls_back(self):
        masked, _ = protect_media('<p>Hello</p><img src="a">')
        primary = self.agent('你好', fallback=self.agent(masked.replace('Hello', '你好')))
        self.assertEqual(primary.completions(text=masked, system_prompt='', _translation_guard=True)['text'], masked.replace('Hello', '你好'))

    def test_both_invalid_produce_no_translation(self):
        bad = 'User Safety: unsafe\nSafety Categories: Political'
        primary = self.agent(bad, fallback=self.agent(bad))
        self.assertEqual(primary.completions(text='Hello', system_prompt='', _translation_guard=True)['text'], '')

    def test_failed_chunk_cannot_be_published_as_partial_article(self):
        agent = self.agent('unused', limit=2500)
        actual = agent.completions
        agent.completions = lambda **kw: {'text': '一' if kw['text'] == 'first' else '', 'tokens': 1}
        self.assertEqual(actual(text='x' * 5000, system_prompt='', _translation_guard=True)['text'], '')

    def test_paid_luna_does_not_fall_back_to_free_openrouter_models(self):
        calls = []
        agent = self.agent('你好', model='openai/gpt-6-luna',
                           free_models=['nvidia/example:free'], calls=calls)
        self.assertEqual(agent.completions(text='Hello', system_prompt='')['text'], '你好')
        self.assertNotIn('extra_body', calls[0])

    def test_free_primary_keeps_free_openrouter_fallbacks(self):
        calls = []
        agent = self.agent('你好', model='nvidia/example:free',
                           free_models=['meta-llama/example:free'], calls=calls)
        agent.completions(text='Hello', system_prompt='')
        self.assertEqual(
            calls[0]['extra_body']['models'], ['meta-llama/example:free']
        )


if __name__ == '__main__':
    unittest.main()
