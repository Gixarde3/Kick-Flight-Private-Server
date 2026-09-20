"""Read a known player's transform prefix from decoded Photon event201.

Requires explicit view IDs; custom66 buffers from other observables must not be
assumed to be transforms. Layout verified against PhotonSerializedValueSet
ReadMask (0x18DE700), ValueMask.GetNext2 (0x18DE918), ReadFloat (0x18DEF70),
and PhotonTransformViewSynchronizeValues.OnPhotonSerializeView (0x18E0F78).
Only the position prefix is decoded; later rotation/state fields stay opaque.
"""

import argparse
import json
import math
import struct
from pathlib import Path


def position_prefix(hex_data):
    data = bytes.fromhex(hex_data)
    if len(data) < 4:
        raise ValueError('short serialized buffer')
    mask_offset = struct.unpack_from('<H', data)[0]
    if not 2 <= mask_offset < len(data):
        raise ValueError('mask offset outside buffer')
    mask_length = data[mask_offset]
    mask = data[mask_offset + 1:mask_offset + 1 + mask_length]
    if len(mask) != mask_length or not mask:
        raise ValueError('short/empty mask')
    if not mask[0] & 1:
        return {'syncEnabled': False}
    cursor = 2
    position = []
    for component in range(3):
        bit = 1 + component * 2
        value_type = (int.from_bytes(mask, 'little') >> bit) & 3
        if value_type == 3:
            if cursor + 4 > mask_offset:
                raise ValueError('position float overlaps mask')
            value = struct.unpack_from('<f', data, cursor)[0]
            cursor += 4
        else:
            value = (0.0, 1.0, 3.4028234663852886e38)[value_type]
        if not math.isfinite(value):
            raise ValueError('nonfinite position')
        position.append(value)
    return {'syncEnabled': True, 'position': position,
            'remainingDataBytes': mask_offset - cursor}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jsonl', type=Path)
    parser.add_argument('--views', type=int, nargs='+', required=True)
    args = parser.parse_args()
    for line in args.jsonl.open(encoding='utf-8'):
        row = json.loads(line)
        message = row.get('message', {})
        if message.get('kind') != 4 or message.get('code') != 201:
            continue
        values = message.get('parameters', {}).get('245')
        if not isinstance(values, list):
            continue
        for observable in values[2:]:
            if not isinstance(observable, list) or len(observable) < 4:
                continue
            view = observable[0]
            if view not in args.views:
                continue
            buffer = observable[3]
            if not isinstance(buffer, dict) or buffer.get('custom') != 66:
                continue
            output = {key: row.get(key) for key in ('utc', 'source', 'destination')}
            output['viewId'] = view
            try:
                output.update(position_prefix(buffer['bytes']))
            except (ValueError, KeyError, struct.error) as error:
                output['error'] = str(error)
            print(json.dumps(output))


if __name__ == '__main__':
    main()
