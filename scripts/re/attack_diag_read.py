"""Read the basic-attack DIAG probes (scripts/re/attack_diag_caves.py) from a logcat dump and print a timeline.

    adb logcat -d -v time -s KFDIAG > log.txt && python scripts/re/attack_diag_read.py log.txt
    python scripts/re/attack_diag_read.py            # runs `adb logcat -d -s KFDIAG` itself

Each line: time, event. Repeated identical events are collapsed into "xN".
"""
import subprocess
import sys

NAMES = {
    8210: "COMBO RESET: IsReset (target null)",
    8211: "COMBO RESET: IsUpdateAction false",
    8220: "SS ready + SS targeting -> attacks suspended",
    8230: "IsUpdateAction FALSE",
    8300: "range: OUT",
    8301: "range: in",
    8310: "IsAttack TRUE -> attack",
}
REASONS = {8710: "sync", 8720: "enableAttack", 8730: "transitionMotion", 8740: "stateNormal",
           8750: "land", 8760: "crouch", 8770: "ssTargeting"}
STATES = ["Normal", "Avoid", "TurnAround", "BarrelRoll", "BackStep", "KickTurn", "BlowOff", "PullIn", "KnockBack",
          "Dead", "Revival", "Skill", "Deposit", "SpecialSkill", "FlagStand", "Entrained"]
COMBO = {8100: "ATTACK combo", 8400: "PlayAttackIn", 8500: "PlayMoveAttackIn", 8600: "PlayGroundMoveAttackIn"}
ANGLE = {8320: "idle yaw", 8321: "idle pitch", 8322: "move yaw", 8323: "move pitch"}


def main():
    if len(sys.argv) > 1:
        text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    else:
        text = subprocess.run(["adb", "logcat", "-d", "-v", "time", "-s", "KFDIAG"], capture_output=True, text=True).stdout
    vals = []
    for line in text.splitlines():
        if "v=" not in line:
            continue
        parts = line.split()
        try:
            vals.append((parts[1], int(parts[-1][2:])))
        except (IndexError, ValueError):
            pass
    events = []
    i = 0
    while i < len(vals):
        t, v = vals[i]
        if v in NAMES:
            events.append((t, NAMES[v]))
        elif 8800 <= v < 8804:
            events.append((t, f"collision destroyed: {['None', 'HIT', 'LifeTime (miss)', 'ForceRemove'][v - 8800]}"))
        elif 8810 <= v < 8820:
            events.append((t, f"  hits={v - 8810}"))
        elif 8789 <= v < 8800:
            n = v - 8790
            events.append((t, f"  state={STATES[n] if 0 <= n < len(STATES) else n}"))
        elif v - v % 10 in REASONS and v % 10 in (0, 1):
            events.append((t, f"  {REASONS[v - v % 10]}={'yes' if v % 10 else 'NO'}"))
        elif 8100 <= v < 8103 or 8400 <= v < 8403 or 8500 <= v < 8503 or 8600 <= v < 8603:
            base = v - v % 100
            events.append((t, f"{COMBO[base]} #{v - base + 1}"))
        elif v in ANGLE and i + 2 < len(vals):
            events.append((t, f"{ANGLE[v]} |d|={vals[i + 1][1]} limit={vals[i + 2][1]}"))
            i += 2
        i += 1
    out = []
    for t, e in events:
        if out and out[-1][1] == e:
            out[-1][2] += 1
        else:
            out.append([t, e, 1])
    for t, e, n in out:
        print(f"{t}  {e}" + (f"  x{n}" if n > 1 else ""))


if __name__ == "__main__":
    main()
