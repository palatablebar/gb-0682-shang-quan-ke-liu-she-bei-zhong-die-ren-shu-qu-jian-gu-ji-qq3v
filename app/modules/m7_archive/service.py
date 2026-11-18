from app.modules.m7_archive.export_out import checksum
from app.modules.m8_disclosure.rules import adjudicate


def execute(state):
    # 归档与披露页共用同一保护判断：在归档阶段对当前计算结果做一次确定性裁决，
    # 供 evidence_count、归档摘要与导出复用；M8 再次调用同一纯函数结论不变。
    adjudicate(state)
    disclosure = state['disclosure']
    state['archive'] = {
        'sha256': checksum(state),
        'evidence_count': len(state.get('calculations', [])) + len(state['quarantine']),
        'ready': state.get('reconcile', {}).get('balanced', False),
        'disclosure_summary': dict(disclosure['summary']),
        'publishable': disclosure['publishable'],
    }
    return state
