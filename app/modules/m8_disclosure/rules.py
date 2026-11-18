# 披露裁决（统计披露控制）
# 页面、归档与导出共用本文件的同一判断，禁止在别处另写一套保护逻辑。
#
# 两条敏感规则（可叠加，任一命中即不得按原区间披露）：
#   SMALL_SAMPLE 小样本：区间下界仍低于最小样本门槛，单商户客流可被定位。
#   INFERABLE    可反推：区间过窄（含精确值 EXACT），或由相邻区域差额/补集
#                 反推出的其余联合人数区间过窄或落入小样本。
# 处置：
#   可通过扩大区间（按保护带宽取整，公开区间仍保留上下界）消除的，状态 widened；
#   下界类风险（自身或补集反推落入小样本）无法靠扩区间抬升，扩大后仍不安全的，
#   暂缓披露 withheld，不输出任何可用边界。

SMALL_SAMPLE_THRESHOLD = 10      # 下界低于 10 人视为小样本
MIN_INTERVAL_WIDTH = 10          # 公开区间最小宽度（宽度 0 即精确反推）
WIDEN_BANDS = (10, 20, 50, 100)  # 扩区间带宽，由小到大逐级尝试

STATUS_PUBLIC = 'public'
STATUS_WIDENED = 'widened'
STATUS_WITHHELD = 'withheld'
STATUS_LABEL = {STATUS_PUBLIC: '公开', STATUS_WIDENED: '扩区间', STATUS_WITHHELD: '暂缓'}


def _dedupe(seq):
    seen, out = set(), []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _widen(lower, upper, band):
    """按带宽把区间向外扩大：下界向下取整到带宽倍数（不低于 0），
    上界一律取到下一个带宽倍数，确保即使原值压在带宽边界上也确实变宽。"""
    new_lower = max(0, (lower // band) * band)
    new_upper = (upper // band + 1) * band
    return new_lower, new_upper


def _complement_bounds(lower, upper, zone_max):
    """相邻区域差额/补集反推：已知本联合区间 [L,U] 与其中某单区域观测 z，
    其余区域联合人数被夹在 [max(0,L-z), max(0,U-z)]。取最大单区域使反推区间最窄。"""
    return max(0, lower - zone_max), max(0, upper - zone_max)


def _flags(lower, upper, zone_max, zone_count):
    flags = []
    if lower < SMALL_SAMPLE_THRESHOLD:
        flags.append('SMALL_SAMPLE')
    if upper - lower < MIN_INTERVAL_WIDTH:
        flags.append('INFERABLE')  # 自身区间过窄（含宽度 0 的精确反推）
    # 补集/差额反推只在两个及以上区域时成立；单区域没有“其余商户”，补集为 0 不构成泄露。
    if zone_count >= 2:
        comp_lower, comp_upper = _complement_bounds(lower, upper, zone_max)
        if (comp_upper - comp_lower) < MIN_INTERVAL_WIDTH or comp_lower < SMALL_SAMPLE_THRESHOLD:
            flags.append('INFERABLE')  # 相邻区域差额可反推其余联合人数
    return _dedupe(flags)


def adjudicate_entry(lower, upper, zone_max, zone_count=1):
    """对单个联合人数区间给出唯一保护判断。

    返回 dict：status、reasons、band；公开/扩区间时给 public_lower/public_upper，
    暂缓时不返回任何可用边界（键缺省），避免下游误披露。
    """
    reasons = _flags(lower, upper, zone_max, zone_count)
    if not reasons:
        return {'status': STATUS_PUBLIC, 'reasons': [], 'band': 0,
                'public_lower': lower, 'public_upper': upper}
    if zone_count >= 2:
        comp_lower, _ = _complement_bounds(lower, upper, zone_max)
    else:
        comp_lower = SMALL_SAMPLE_THRESHOLD  # 单区域无补集风险
    # 下界类风险（自身小样本，或差额反推出小补集）：扩区间只会平移或下压下界，
    # 无法抬升，直接暂缓。
    if lower < SMALL_SAMPLE_THRESHOLD or comp_lower < SMALL_SAMPLE_THRESHOLD:
        return {'status': STATUS_WITHHELD, 'reasons': reasons, 'band': 0}
    for band in WIDEN_BANDS:
        new_lower, new_upper = _widen(lower, upper, band)
        if not _flags(new_lower, new_upper, zone_max, zone_count):
            return {'status': STATUS_WIDENED, 'reasons': reasons, 'band': band,
                    'public_lower': new_lower, 'public_upper': new_upper}
    return {'status': STATUS_WITHHELD, 'reasons': reasons, 'band': 0}


def adjudicate(state):
    """对 M5 计算结果逐时段裁决，写入 state['disclosure'] 并返回 state。

    纯函数：同一输入（含补录后重新计算的结果）必然得到同一裁决；补录使组合不再
    敏感时，重跑后对应条目自动回到 public/widened，无需人工清理历史状态。
    """
    models = {m['bucket']: m['model'] for m in state.get('models', [])}
    entries = []
    for calc in state.get('calculations', []):
        model = models.get(calc['id'], {'zones': {}})
        zones = model.get('zones', {})
        zone_max = max(zones.values(), default=0)
        verdict = adjudicate_entry(calc['lower'], calc['upper'], zone_max, len(zones))
        entries.append({
            'id': calc['id'], 'line': calc['line'],
            'lower': calc['lower'], 'upper': calc['upper'],
            'zone_max': zone_max, **verdict,
        })
    summary = {STATUS_PUBLIC: 0, STATUS_WIDENED: 0, STATUS_WITHHELD: 0}
    for entry in entries:
        summary[entry['status']] += 1
    state['disclosure'] = {
        'thresholds': {'small_sample': SMALL_SAMPLE_THRESHOLD,
                       'min_width': MIN_INTERVAL_WIDTH,
                       'widen_bands': list(WIDEN_BANDS)},
        'entries': entries,
        'summary': summary,
        'publishable': summary[STATUS_WITHHELD] == 0,
    }
    return state
