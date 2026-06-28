from __future__ import annotations
import json
from unittest.mock import MagicMock, patch
from shared import supabase_mirror as sm

def _mock_json_response(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode('utf-8')
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp

@patch('shared.supabase_mirror._anon_key', return_value='anon')
@patch('shared.supabase_mirror._base_url', return_value='https://test.supabase.co')
@patch('urllib.request.urlopen')
def test_list_storage_rows_paginates(mock_urlopen, _base, _anon):
    page_one = [{'name': f'default/games_{idx}.json'} for idx in range(200)]
    page_two = [{'name': 'default/games_extra.json'}]
    mock_urlopen.side_effect = [_mock_json_response(page_one), _mock_json_response(page_two)]
    rows = sm._list_storage_rows(prefix='uid/default/', bearer_token='token')
    assert len(rows) == 201
    assert mock_urlopen.call_count == 2
    second_body = json.loads(mock_urlopen.call_args_list[1][0][0].data.decode('utf-8'))
    assert second_body['offset'] == 200