"""Use the official SDK with a local HTTP transport; never call a live provider."""
import json

import httpx
import pytest
from google import genai
from google.genai import types

from app.adapters.gemini import GeminiConversationAdapter, GeminiResponseAdapter


@pytest.mark.parametrize('adapter_type,payload', [
    (GeminiConversationAdapter, {'action': 'reply', 'reason': 'Relevant public facts.', 'content': 'Which sandbox callback endpoint will you use?'}),
    (GeminiResponseAdapter, {'should_respond': False, 'reason': 'No additional facts are needed.', 'comment': None}),
])
@pytest.mark.parametrize('model,disable_thinking', [
    ('gemini-2.5-flash', True),
    ('models/gemini-2.5-flash-lite', True),
    ('gemini-2.5-pro', False),
])
def test_sdk_sends_strict_json_schema_in_supported_wire_field(monkeypatch, adapter_type, payload, model, disable_thinking):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if 'responseSchema' in body['generationConfig']:
            return httpx.Response(400, json={'error': {'code': 400, 'status': 'INVALID_ARGUMENT',
                'message': 'Unknown name additional_properties at generation_config.response_schema'}})
        return httpx.Response(200, json={'candidates': [{'content': {'role': 'model',
            'parts': [{'text': json.dumps(payload)}]}, 'finishReason': 'STOP'}]})

    original_client = genai.Client

    def local_client(**kwargs):
        kwargs['http_options'].client_args = {'transport': httpx.MockTransport(respond)}
        return original_client(**kwargs)

    monkeypatch.setattr(genai, 'Client', local_client)
    value = adapter_type(api_key='unit-test-key', model=model).generate('Evaluate the request.', 'Public sandbox facts only.')
    parsed = adapter_type.decision_schema.model_validate_json(value) if isinstance(value, str) else adapter_type.decision_schema.model_validate(value)
    assert parsed.model_dump(exclude_unset=True) == payload
    config = requests[0]['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert 'responseSchema' not in config
    assert config['responseJsonSchema']['additionalProperties'] is False
    assert config['responseJsonSchema']['properties']['reason']['maxLength'] <= 500
    if disable_thinking:
        budget = config['thinkingConfig'].get('thinkingBudget', config['thinkingConfig'].get('thinking_budget'))
        assert budget == 0
    else:
        assert 'thinkingConfig' not in config
