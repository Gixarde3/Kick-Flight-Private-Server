
import subprocess

out = subprocess.check_output(['adb', '-s', 'emulator-5554', 'shell', 'cat /data/tombstones/tombstone_46'], text=True)
lines = out.splitlines()

for i, l in enumerate(lines):
    if 'memory near sp' in l.lower() or 'memory near x29' in l.lower() or 'memory near lr' in l.lower():
        print(f'=== {l} ===')
        for j in range(i, min(i+20, len(lines))):
            print(lines[j])
