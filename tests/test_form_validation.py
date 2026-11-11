"""입력 검증의 기존 경계값·오류 계약. DB 없이 리팩토링 전후 동작을 검증한다."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from lcomfine.app.util import forms


@pytest.mark.parametrize('fn,args,kwargs,expected', [
    (forms.s, ('  값  ', '항목'), {}, '값'),
    (forms.s, ('  ', '항목'), {}, None),
    (forms.need, (' 값 ', '항목'), {}, '값'),
    (forms.pk, (' 1 ',), {}, 1),
    (forms.ref_id, ('0', '항목'), {}, 0),
    (forms.ref_id, (None, '항목'), {'required': False}, None),
    (forms.qty, ('99,999,999,999.999', '수량'), {}, Decimal('99999999999.999')),
    (forms.qty, ('-1', '수량'), {'positive': False}, Decimal('-1')),
    (forms.integer, ('-2', '횟수'), {'minimum': -2}, -2),
    (forms.day, ('2024-02-29', '날짜'), {}, date(2024, 2, 29)),
    (forms.yn, (None,), {}, 'Y'),
    (forms.choice, (' Y ', '구분', ('Y', 'N')), {}, 'Y'),
    (forms.kv_text, ('색=파랑\n크기=\n', '속성'), {}, {'색': '파랑', '크기': ''}),
    (forms.kv_lines, ({'색': '파랑', '크기': ''},), {}, '색=파랑\n크기='),
    (forms.like, (' a%_ ',), {}, '%a\\%\\_%'),
    (forms.text_in, (' abc ', '항목'), {'max_len': 3}, 'abc'),
    (forms.num_in, ('99,999,999,999', '수량'), {}, Decimal('99999999999')),
    (forms.num_in, ('0', '수량'), {'allow_zero': True}, Decimal(0)),
    (forms.int_in, ('0001', '횟수'), {}, 1),
    (forms.date_in, (None, '날짜'), {}, None),
    (forms.id_in, ('0', '항목'), {}, 0),
    (forms.path_id, ('0',), {}, 0),
])
def test_valid_inputs(fn, args, kwargs, expected):
    assert fn(*args, **kwargs) == expected


@pytest.mark.parametrize('fn,args,kwargs,status,message', [
    (forms.need, (None, '항목'), {}, 422, '필수 항목을 입력해 주세요 — 항목'),
    (forms.s, ('a\x00', '항목'), {}, 422, '항목: 글자에 NUL(0x00)을 넣을 수 없습니다'),
    (forms.pk, ('0',), {}, 404, '대상을 찾을 수 없습니다'),
    (forms.pk, ('9223372036854775808',), {}, 404, '대상을 찾을 수 없습니다'),
    (forms.ref_id, ('abc', '항목'), {}, 422, '항목: 목록에서 고른 값이 아닙니다'),
    (forms.qty, ('NaN', '수량'), {}, 422, '수량: 숫자여야 합니다'),
    (forms.qty, ('1.0000', '수량'), {}, 422, '수량: 정수 11자리 · 소수 3자리까지 입력할 수 있습니다'),
    (forms.qty, ('0', '수량'), {}, 422, '수량: 0 보다 커야 합니다'),
    (forms.day, ('2023-02-29', '날짜'), {}, 422, '날짜: 날짜 형식(YYYY-MM-DD)이 아닙니다'),
    (forms.kv_text, ('a=1\na=2', '속성'), {}, 422, '속성: 항목 `a` 이(가) 두 번 나옵니다'),
    (forms.text_in, (None, '항목'), {'required': True}, 422, '항목을(를) 입력하세요'),
    (forms.text_in, ('abcd', '항목'), {'max_len': 3}, 422, '항목: 3자를 넘을 수 없습니다'),
    (forms.num_in, ('99999999999.001', '수량'), {}, 422, '수량: 숫자가 저장할 수 있는 범위를 넘었습니다'),
    (forms.num_in, ('1.0000', '수량'), {}, 422, '수량: 소수점 아래 세 자리까지 입력할 수 있습니다'),
    (forms.num_in, ('Infinity', '수량'), {}, 422, '수량: 숫자가 아닙니다: Infinity'),
    (forms.num_in, ('-1', '수량'), {'allow_zero': True}, 422, '수량: 0 이상이어야 합니다'),
    (forms.int_in, ('-1', '횟수'), {}, 422, '횟수: 0 이상의 정수가 아닙니다: -1'),
    (forms.id_in, (None, '항목'), {}, 422, '항목을(를) 고르세요'),
    (forms.path_id, (' 1 ',), {}, 404, '대상을 찾을 수 없습니다'),
    (forms.date_in, ('2023-02-29', '날짜'), {}, 422, '날짜: 날짜 형식(YYYY-MM-DD)이 아닙니다: 2023-02-29'),
])
def test_invalid_inputs_preserve_http_contract(fn, args, kwargs, status, message):
    with pytest.raises(HTTPException) as raised:
        fn(*args, **kwargs)
    error = raised.value
    assert error.status_code == status
    assert error.detail['message'] == message
    assert error.detail['code'] == ('not_found' if status == 404 else 'validation_error')
    if status == 422:
        assert error.detail['fields'][0]['name'] == args[1]
        assert error.detail['fields'][0]['reason']


def test_query_filter_trims_and_defaults():
    request = Request({'type': 'http', 'query_string': b'q=%20abc%20'})
    assert forms.qs(request, 'q') == 'abc'
    assert forms.qs(request, 'missing') == ''
