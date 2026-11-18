from app.workflow import run
from app.modules.m8_disclosure.rules import (
    adjudicate_entry, MIN_INTERVAL_WIDTH,
    STATUS_PUBLIC, STATUS_WIDENED, STATUS_WITHHELD,
)

HEADER = 'id,bucket,version,kind,left,right,count,unit,note\n'


def _row(i, hour, kind, left, right, count):
    return f'{i:05d},2026-11-16T{hour}:00:00+08:00,1,{kind},{left},{right},{count},人,x\n'


def make_csv(rows):
    return HEADER + ''.join(rows)


def test_normal_wide_interval_is_public():
    r = adjudicate_entry(230, 250, 120, 3)
    assert r['status'] == STATUS_PUBLIC and r['reasons'] == []
    assert (r['public_lower'], r['public_upper']) == (230, 250)


def test_exact_interval_must_be_widened_and_keeps_both_bounds():
    r = adjudicate_entry(150, 150, 100, 2)
    assert r['status'] == STATUS_WIDENED and 'INFERABLE' in r['reasons']
    assert r['public_lower'] <= 150 < r['public_upper']
    assert r['public_upper'] - r['public_lower'] >= MIN_INTERVAL_WIDTH


def test_widening_actually_extends_boundary_aligned_values():
    # 上界 30 恰好压在带宽边界上，扩大后必须严格变宽，不能原地不动。
    r = adjudicate_entry(30, 30, 0, 1)
    assert r['status'] == STATUS_WIDENED and r['public_upper'] > 30


def test_small_sample_is_withheld_without_any_usable_bound():
    r = adjudicate_entry(8, 8, 5, 1)
    assert r['status'] == STATUS_WITHHELD
    assert 'SMALL_SAMPLE' in r['reasons']
    assert 'public_lower' not in r and 'public_upper' not in r


def test_complement_inference_small_sample_is_withheld():
    # 联合 100 与单区域 95 的差额把其余商户夹到 5，可反推小样本，暂缓。
    r = adjudicate_entry(100, 100, 95, 2)
    assert r['status'] == STATUS_WITHHELD and 'INFERABLE' in r['reasons']


def test_single_zone_has_no_complement_risk():
    # 单区域不存在“其余商户”，精确大值只需扩区间，不应被补集规则暂缓。
    assert adjudicate_entry(120, 120, 0, 1)['status'] == STATUS_WIDENED


def test_real_samples_remain_public(raw):
    s = run(raw, {})
    assert s['disclosure']['summary'][STATUS_PUBLIC] == len(s['calculations'])
    assert s['disclosure']['publishable'] is True


def test_adjudication_is_deterministic(raw):
    a = run(raw, {})['disclosure']
    b = run(raw, {})['disclosure']
    assert a == b


def test_pipeline_flags_withheld_and_widened(client):
    csv_text = make_csv([
        _row(1, '09', 'zone', '东门', '', 8),
        _row(2, '10', 'zone', '东门', '', 100),
        _row(3, '10', 'zone', '中庭', '', 80),
        _row(4, '10', 'pair', '东门', '中庭', 30),
    ])
    s = client.post('/api/runs', json={'csv': csv_text}).get_json()
    summary = s['disclosure']['summary']
    assert summary == {'public': 0, 'widened': 1, 'withheld': 1}
    withheld = next(e for e in s['disclosure']['entries'] if e['status'] == STATUS_WITHHELD)
    assert 'public_lower' not in withheld


def test_supplement_relieves_sensitivity_and_readjudicates(client):
    sensitive = make_csv([_row(1, '09', 'zone', '东门', '', 8)])
    first = client.post('/api/runs', json={'csv': sensitive}).get_json()
    assert first['disclosure']['summary'][STATUS_WITHHELD] == 1
    # 补录把小样本抬过门槛后重跑：组合不再敏感，旧批次保留、新批次重新裁决。
    supplemented = make_csv([_row(1, '09', 'zone', '东门', '', 120)])
    second = client.post('/api/runs', json={'csv': supplemented}).get_json()
    assert second['run_id'] != first['run_id']
    assert second['disclosure']['summary'][STATUS_WITHHELD] == 0
    ids = {r['id'] for r in client.get('/api/runs').get_json()}
    assert {first['run_id'], second['run_id']} <= ids


def test_export_uses_same_protection_and_hides_withheld_bounds(client):
    import csv as _csv, io
    csv_text = make_csv([
        _row(1, '09', 'zone', '东门', '', 8),
        _row(2, '10', 'zone', '东门', '', 100),
        _row(3, '10', 'zone', '中庭', '', 80),
        _row(4, '10', 'pair', '东门', '中庭', 30),
    ])
    s = client.post('/api/runs', json={'csv': csv_text}).get_json()
    export = client.get('/api/archive/' + s['run_id'] + '/export.csv').data.decode('utf-8-sig')
    rows = list(_csv.reader(io.StringIO(export)))
    disclosure = [r for r in rows if r[0] == '披露']
    assert any(r[0] == '披露裁决' for r in rows)
    assert any('withheld' in r[5] and 'public_lower' not in r[5] for r in disclosure)
    widened = [r for r in disclosure if 'widened' in r[5]][0]
    assert 'public_lower' in widened[5] and 'public_upper' in widened[5]


def test_same_batch_rerun_creates_no_duplicate_run_or_version(client):
    csv_text = make_csv([_row(1, '09', 'zone', '东门', '', 120)])
    a = client.post('/api/runs', json={'csv': csv_text}).get_json()
    before = len(client.get('/api/runs').get_json())
    b = client.post('/api/runs', json={'csv': csv_text}).get_json()
    after = client.get('/api/runs').get_json()
    assert a['run_id'] == b['run_id'] and len(after) == before
    assert all(r['version'] == 1 for r in after if r['id'] == a['run_id'])


def test_failed_switch_keeps_old_version_and_all_records(client):
    csv_text = make_csv([_row(1, '09', 'zone', '东门', '', 120)])
    s = client.post('/api/runs', json={'csv': csv_text}).get_json()
    latest_before = client.get('/api/runs').get_json()[0]['id']
    count_before = len(client.get('/api/runs').get_json())
    resp = client.post('/api/runs/missing-batch/activate')
    assert resp.status_code == 404
    listing = client.get('/api/runs').get_json()
    assert listing[0]['id'] == latest_before and len(listing) == count_before
    # 旧批次本身仍可读取，记录未丢失。
    assert client.get('/api/runs/' + s['run_id']).status_code == 200


def test_successful_switch_points_latest_without_deleting(client):
    a = client.post('/api/runs', json={'sample': 'dirty.csv'}).get_json()
    b = client.post('/api/runs', json={'sample': 'clean.csv'}).get_json()
    assert client.get('/api/runs').get_json()[0]['id'] == b['run_id']
    resp = client.post('/api/runs/' + a['run_id'] + '/activate')
    assert resp.status_code == 200
    listing = client.get('/api/runs').get_json()
    assert listing[0]['id'] == a['run_id']
    assert {r['id'] for r in listing} >= {a['run_id'], b['run_id']}


def test_disclosure_page_renders(client):
    page = client.get('/m8_disclosure')
    assert page.status_code == 200 and '披露裁决'.encode() in page.data
