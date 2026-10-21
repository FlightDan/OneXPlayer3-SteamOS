from pathlib import Path
import json, subprocess, sys, tempfile
source=Path(sys.argv[1]).read_text()
with tempfile.TemporaryDirectory() as td:
    d=Path(td); config=d/"output.json"; helper=d/"fallback.py"
    helper.write_text(source.replace("/home/deck/.config/kwinoutputconfig.json",str(config)))
    def run(): return subprocess.run([sys.executable,"-I",str(helper)],capture_output=True).returncode
    assert run()==0 and not config.exists()
    original=[{"name":"outputs","data":[{"connectorName":"eDP-1","highDynamicRange":True,"wideColorGamut":True,"brightness":0.2,"scale":1.7},{"connectorName":"DP-1","highDynamicRange":True,"wideColorGamut":True}]}]
    config.write_text(json.dumps(original));config.chmod(0o640)
    assert run()==0
    got=json.loads(config.read_text());assert got[0]["data"][0]["highDynamicRange"] is False and got[0]["data"][0]["wideColorGamut"] is False
    assert got[0]["data"][0]["brightness"]==0.2 and got[0]["data"][0]["scale"]==1.7 and got[0]["data"][1]==original[0]["data"][1]
    assert config.stat().st_mode&0o777==0o640
    before=config.read_bytes();assert run()==0 and config.read_bytes()==before
    config.write_text("invalid JSON");assert run()!=0 and config.read_text()=="invalid JSON"
    config.unlink();target=d/"target.json";target.write_text(json.dumps(original));config.symlink_to(target)
    assert run()!=0 and json.loads(target.read_text())==original
print("PASS: absent config, internal-only SDR recovery, idempotence, invalid JSON refusal, symlink refusal; brightness/scale/external output and permissions preserved")
