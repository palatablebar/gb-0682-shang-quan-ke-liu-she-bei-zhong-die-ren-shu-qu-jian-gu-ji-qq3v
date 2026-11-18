import io,csv,json,hashlib
from app.modules.m8_disclosure.rules import adjudicate,STATUS_LABEL


def bundle(state):
    # 导出与披露页/归档共用同一保护判断：不缓存外部结论，导出前按同一引擎重判一次。
    adjudicate(state)
    out=io.StringIO(newline='');writer=csv.writer(out)
    rid=state.get('run_id','preview')
    writer.writerow(['记录类型','批次','来源行','业务ID','原因码','内容'])
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    disclosure=state.get('disclosure',{})
    writer.writerow(['披露裁决',rid,'','','',json.dumps(
        {'thresholds':disclosure.get('thresholds',{}),'summary':disclosure.get('summary',{}),
         'publishable':disclosure.get('publishable',False)},ensure_ascii=False,sort_keys=True)])
    for entry in disclosure.get('entries',[]):
        # 暂缓条目不输出任何可用上下界，仅留裁决记录与原因；公开/扩区间只输出保护后边界，
        # 扩区间与公开条目都保留上下界两个字段。
        content={'status':entry['status'],'status_label':STATUS_LABEL[entry['status']],
                 'reasons':entry['reasons'],'band':entry['band']}
        if entry['status']!='withheld':
            content.update(public_lower=entry['public_lower'],public_upper=entry['public_upper'])
        writer.writerow(['披露',rid,entry.get('line',''),entry.get('id',''),
                         '|'.join(entry['reasons']) or 'OK',json.dumps(content,ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):writer.writerow(['计算',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state['quarantine']:writer.writerow(['隔离',rid,row['line'],row.get('id',''),row['code'],json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
