"""Create a portable summary only after the complete owned-VM suite passes."""
from pathlib import Path
import datetime
import json
import re

root=Path(__file__).resolve().parents[1]
lab=root/'work/refind-acceptance-20261014'
records=json.loads((lab/'acceptance.json').read_text(encoding='utf-8-sig'))
expected=['lifecycle','manual-steamos-boot','windows-probe','windows-efi-probe-boot','uninstall','restored-steamos-boot']
assert [r['name'] for r in records]==expected and all(r['passed'] for r in records)
logs={r['name']:Path(r['record']).read_text(encoding='utf-8-sig') for r in records}
lifecycle=json.loads(re.search(r'OXP_REFIND_RESULT=(\{[^\n]+\})',logs['lifecycle'])[1])
assert lifecycle['passed'] and lifecycle['count']==31
boots={}
for name in ('manual-steamos-boot','windows-efi-probe-boot','restored-steamos-boot'):
    folder=Path(re.search(r'(?:REFIND_BOOT|INTEGRATION_BOOT)=([^\r\n]+)',logs[name])[1])
    proof=json.loads((folder/'result.json').read_text())
    assert proof['passed'] and not proof['cancelled'] and not proof['timedOut']
    assert folder.stat().st_mtime >= Path(records[0]['record']).stat().st_mtime
    boots[name]={k:proof[k] for k in ('passed','refindManual','windowsProbe','scope')}
    boots[name]['local_record']=str(folder.relative_to(root)/'result.json')
ui={}
for name,file in [('options','logs/options-checks.json'),('touch_layout','logs/touch-ui-20261014-002715/checks.json'),('wizard','logs/wizard-ui-20261014-002720/checks.json')]:
    proof=json.loads((root/file).read_text(encoding='utf-8-sig')); assert proof['passed']
    ui[name]=dict(passed=True,events=len(proof['events']),local_record=file)
summary=dict(recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),passed=True,
    stages=[dict(name=r['name'],passed=r['passed']) for r in records],lifecycle=lifecycle,boots=boots,ui=ui,
    theme=dict(name='Graphite Quiet',review='ship for reviewed 1280x800 visual scope',screenshots=['refind-dark-menu.png','refind-dark-windows.png','refind-dark-tools.png']),
    limitations=['Windows EFI destination probe is not a real Windows OS boot','Physical installation, handheld touch, display rotation and Secure Boot chain are untested','Injected process interruption is not physical power loss','SteamOS boot proof reaches serial login, not Steam frontend'])
(root/'docs/refind-acceptance.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(dict(passed=True,lifecycle_checks=lifecycle['count'],boots=len(boots),ui=ui),ensure_ascii=False))
