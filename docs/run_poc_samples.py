import sys
import io

sys.path.insert(0, '.')
sys.path.insert(0, 'engine')
sys.path.insert(0, 'scripts')
from engine.replay_engine import ReplayEngine

# 重定向 stdout 到文件
log_file = open('d:/stock/Analysis/docs/replay_poc_v2_full.log', 'w', encoding='utf-8')

class TeeOutput:
    def __init__(self, *files):
        self.files = files
    def write(self, text):
        for f in self.files:
            f.write(text)
    def flush(self):
        for f in self.files:
            try:
                f.flush()
            except:
                pass

sys.stdout = TeeOutput(sys.stdout, log_file)

print('=' * 70)
print('Phase 3 POC v2 - 4 样本完整报告')
print('=' * 70)

e = ReplayEngine(verbose=False)
samples = [
    ('603773.SH', '沃格光电', '20260522', '20260612', 9.12, 'WIN'),
    ('603039.SH', '泛微网络', '20260608', None, None, '活跃持仓'),
    ('002602.SZ', '世纪华通', '20260605', '20260615', -2.93, 'LOSS'),
    ('002407.SZ', '多氟多', '20260612', '20260615', -3.05, 'LOSS'),
]
for tc, name, entry, exit_d, pnl, scenario in samples:
    print()
    print('=' * 70)
    print('[Sample] {} ({}) - {}'.format(name, tc, scenario))
    print('=' * 70)
    r = e.replay_position(tc, entry, exit_d)
    if pnl is not None:
        r.set_actual_pnl(pnl)
    print(r.summary())

print()
print('=' * 70)
print('性能统计')
print('=' * 70)
print('  Preload count: {}'.format(e.stats['preload_count']))
print('  Cache hits:    {}'.format(e.stats['cache_hits']))
print('  Signal count:  {}'.format(e.stats['signal_count']))

log_file.close()
print('Saved to d:/stock/Analysis/docs/replay_poc_v2_full.log')