from pathlib import Path
p=Path('/home/deck/oxp3-research/kde-gamma22-build-v1/source/valve/kwin-6.7.3/src/workspace.cpp')
s=p.read_text()
if '#include "utils/envvar.h"' not in s:
 s='#include "utils/envvar.h"\n'+s
anchor='''    support.append(QStringLiteral("KWin version: "));'''
assert s.count(anchor)==1
s=s.replace(anchor,'''    support.append(environmentVariableBoolValue("KWIN_OXP3_GAMMA22_HDR").value_or(false)
        ? QStringLiteral("OXP3 Gamma22 HDR mapping: enabled (1100/472)\\n")
        : QStringLiteral("OXP3 Gamma22 HDR mapping: disabled\\n"));
'''.replace('\\n','\n')+anchor)
p.write_text(s)
print('Private candidate runtime marker added; normal KWin cannot enable the new control.')
