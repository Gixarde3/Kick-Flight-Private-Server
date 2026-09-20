"""Read unencrypted ENet/Photon Protocol18 messages from a tcpdump pcap.

Usage: python scripts/re/read-photon-pcap.py trace.pcap > trace.jsonl
Optional: --rpc-list settings.json (object containing the APK's rpc_list array).
Read-only diagnostic. Unsupported/encrypted/fragmented payloads are reported,
never interpreted as absent game events. Supports Ethernet, Linux SLL/SLL2.
Wire layouts follow Luxon's enet_protocol.cpp and ser_gp_binary_v18.cpp.
"""
import datetime
import json
import struct
import sys
from pathlib import Path


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('truncated payload')
        b = self.data[self.pos:self.pos+n]
        self.pos += n
        return b

    def num(self, fmt):
        return struct.unpack('>' + fmt, self.take(struct.calcsize('>' + fmt)))[0]

    def value(self, code=None):
        code = self.num('B') if code in (None, 0, 42) else code
        if code == 42:
            return None
        if code in (98, 107, 105, 108, 102, 100, 111):
            return self.num({98:'B',107:'h',105:'i',108:'q',102:'f',100:'d',111:'?'}[code])
        if code == 115:
            return self.take(self.num('H')).decode('utf-8', errors='replace')
        if code == 120:
            return {'bytes': self.take(self.num('I')).hex()}
        if code == 99:
            custom = self.num('B')
            return {'custom':custom, 'bytes':self.take(self.num('H')).hex()}
        if code == 104:
            pairs = []
            for _ in range(self.num('H')):
                key = self.value()
                pairs.append([key, self.value()])
            return {'hashtable':pairs}
        if code == 68:
            kt, vt, n = self.num('B'), self.num('B'), self.num('H')
            return {'dictionary':[[self.value(kt), self.value(vt)] for _ in range(n)]}
        if code == 122:
            return [self.value() for _ in range(self.num('H'))]
        if code == 110:
            return [self.num('i') for _ in range(self.num('I'))]
        if code == 97:
            return [self.value(115) for _ in range(self.num('H'))]
        if code == 121:
            n, elem = self.num('H'), self.num('B')
            return [self.value(elem) for _ in range(n)]
        raise ValueError(f'unsupported type {code:#x}')

    def parameters(self):
        pairs = {}
        for _ in range(self.num('H')):
            key = self.num('B')
            pairs[str(key)] = self.value()
        return pairs


class Reader18(Reader):
    def num(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def varuint(self):
        result = 0
        for shift in range(0, 70, 7):
            b = self.num('B')
            result |= (b & 127) << shift
            if b < 128:
                return result
        raise ValueError('invalid varuint')

    def value(self, code=None):
        code = self.num('B') if code is None or code == 0 else code
        if code == 8:
            return None
        if code in (2,3,4,5,6):
            return self.num({2:'?',3:'B',4:'h',5:'f',6:'d'}[code])
        if code == 7:
            return self.take(self.varuint()).decode('utf-8', errors='replace')
        if code in (9,10):
            n = self.varuint()
            return (n >> 1) ^ -(n & 1)
        if 11 <= code <= 18:
            n = self.num('B' if code in (11,12,15,16) else 'H')
            return -n if code % 2 == 0 else n
        if code in (27,28):
            return code == 28
        if 29 <= code <= 34:
            return 0
        if code == 19 or code >= 128:
            custom = self.num('B') if code == 19 else code - 128
            return {'custom':custom, 'bytes':self.take(self.varuint()).hex()}
        if code == 21:
            pairs = []
            for _ in range(self.varuint()):
                key = self.value()
                pairs.append([key,self.value()])
            return {'hashtable':pairs}
        if code == 20:
            kt, vt = self.num('B'), self.num('B')
            return {'dictionary':[[self.value(kt),self.value(vt)] for _ in range(self.varuint())]}
        if code == 23:
            return [self.value() for _ in range(self.varuint())]
        if code == 67:
            return {'bytes':self.take(self.varuint()).hex()}
        if code in (68,69,70,71,73,74,85):
            elem = {68:4,69:5,70:6,71:7,73:9,74:10,85:21}[code]
            return [self.value(elem) for _ in range(self.varuint())]
        raise ValueError(f'unsupported Protocol18 type {code:#x}')

    def parameters(self):
        pairs = {}
        for _ in range(self.num('B')):
            key = self.num('B')
            pairs[str(key)] = self.value()
        return pairs


def photon(payload):
    r = Reader18(payload)
    if r.num('B') != 0xf3:
        raise ValueError('not a Photon message')
    kind = r.num('B')
    if kind & 128:
        raise ValueError('encrypted Photon payload')
    if kind not in (2,3,4,6,7):
        raise ValueError(f'unsupported Photon kind {kind}')
    out = {'kind':kind, 'code':r.num('B')}
    if kind in (3,7):
        out['return_code'] = r.num('h')
        out['debug'] = r.value()
    out['parameters'] = r.parameters()
    if r.pos != len(payload):
        raise ValueError(f'trailing bytes: {len(payload)-r.pos}')
    return out


def read(path):
    fragments = {}
    rpc_names = None
    if '--rpc-list' in sys.argv:
        rpc_names = json.loads(Path(sys.argv[sys.argv.index('--rpc-list')+1]).read_text())['rpc_list']
    with Path(path).open('rb') as f:
        header = f.read(24)
        if header[:4] not in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4'):
            raise ValueError('expected classic microsecond pcap')
        endian = '<' if header[0] == 0xd4 else '>'
        link = struct.unpack(endian+'I', header[20:24])[0]
        offset = {1:14,113:16,276:20}[link]
        while h := f.read(16):
            if len(h) != 16:
                break  # A live tcpdump may still be appending this record.
            sec, usec, size, _ = struct.unpack(endian+'IIII', h)
            packet = f.read(size)
            if len(packet) != size:
                break
            ip = packet[offset:]
            if len(ip)<28 or ip[0]>>4 != 4 or ip[9] != 17:
                continue
            udp = ip[(ip[0]&15)*4:]
            source, destination, length, _ = struct.unpack('>HHHH',udp[:8])
            d = udp[8:length]
            if len(d)<12 or d[2] not in (0,204):
                continue
            pos = 16 if d[2] == 204 else 12
            for _ in range(d[3]):
                if pos+12>len(d):
                    break
                cmd, channel = d[pos], d[pos+1]
                n, sequence = struct.unpack('>II',d[pos+4:pos+12])
                if n<12 or pos+n>len(d):
                    break
                payload = d[pos+12:pos+n]
                pos += n
                if cmd not in (6,7,8,11,13,14,15):
                    continue
                if cmd in (7,11):
                    payload = payload[4:]
                record = {'utc':datetime.datetime.fromtimestamp(sec+usec/1e6,datetime.timezone.utc).isoformat(),
                          'source':source,'destination':destination,'channel':channel,'sequence':sequence,'command':cmd}
                try:
                    if cmd in (8,15):
                        start, count, number, total, off = struct.unpack('>IIIII',payload[:20])
                        chunk = payload[20:]
                        if count > 10000 or total > 16000000 or number >= count or off + len(chunk) > total:
                            raise ValueError('invalid fragment bounds')
                        key = (ip[12:20],source,destination,channel,start,total)
                        parts = fragments.setdefault(key,{})
                        parts[number] = (off,chunk)
                        if len(parts) != count:
                            record['fragment_pending'] = {'start':start,'number':number,'count':count}
                            print(json.dumps(record))
                            continue
                        ordered = sorted(parts.values())
                        cursor = 0
                        for offset_, chunk_ in ordered:
                            if offset_ != cursor:
                                raise ValueError('fragment coverage gap or overlap')
                            cursor += len(chunk_)
                        if cursor != total:
                            raise ValueError('fragment coverage incomplete')
                        payload = b''.join(chunk_ for _,chunk_ in ordered)
                        del fragments[key]
                        record['reassembled_fragments'] = count
                    record['message'] = photon(payload)
                    m = record['message']
                    params = m['parameters']
                    if rpc_names and (params.get('244') == 200 or m['kind'] == 4 and m['code'] == 200):
                        table = params.get('245')
                        if isinstance(table,dict) and 'hashtable' in table:
                            rpc = {k:v for k,v in table['hashtable'] if isinstance(k,(int,str))}
                            index = rpc.get(5)
                            record['rpc_name'] = rpc_names[index] if isinstance(index,int) and 0 <= index < len(rpc_names) else rpc.get(3,'unknown')
                except (ValueError,struct.error,IndexError) as exc:
                    record['decode_error'] = str(exc)
                    record['raw'] = payload.hex()
                print(json.dumps(record,ensure_ascii=False))


if __name__ == '__main__':
    read(sys.argv[1])
