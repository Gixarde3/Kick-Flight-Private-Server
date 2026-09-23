#!/usr/bin/env python3
"""List the fields of il2cpp classes straight out of global-metadata.dat.

Why this exists: the served master JSON keys are the client's own field names (Unity's JsonUtility
maps a field name to the key verbatim), so "what does a TutorialKickerAiMasterData row look like" is a
question only this table can answer. The identifier string table is not enough - type names, field
names and method names all live in it and adjacent entries belong to unrelated classes.

    python scripts/re/meta_fields.py KickerAiMasterData TutorialKickerAiMasterData
    python scripts/re/meta_fields.py --search KickerAiMasterData
    python scripts/re/meta_fields.py --dump-fields TutorialKickerAiMasterData

Metadata layout found in KickFlight 2.11.0 (il2cpp metadata version 24):

    int32 sanity (0xFAB11BAF), int32 version, then 33 (offset, byte-size) pairs. Every pair is an
    offset and a size IN BYTES, so a table's entry count is size / entry-stride - never the size
    itself (treating typeDefinitionsSize as a count is what used to make this script read garbage).
    The three pairs used here:

        pair  2 (header int32  6/7)   stringOffset / stringSize
        pair 11 (header int32 24/25)  fieldsOffset / fieldsSize
        pair 19 (header int32 40/41)  typeDefinitionsOffset / typeDefinitionsSize

    as found in this APK: string @ 0x8dda0 (1819996 B), fields @ 0x951cd8 (782676 B = 65223 * 12),
    typeDefinitions @ 0xae3668 (1597700 B = 15977 * 100).

Il2CppFieldDefinition is 12 bytes: nameIndex int32, typeIndex int32, token uint32. Entry count is
fieldsSize / 12 = 65223.

Il2CppTypeDefinition is 100 bytes here (not the 92 of the plain v24 struct), and neither the stride nor
the slot offsets are assumed: they are discovered and then printed, so a human can sanity-check them.
The stride is the value in 88..128 for which the int32 at each record's start lands on a true string
start (a `strtab.find(KickerAiMasterData)` style search is not enough - that matches inside
`CustomBattleKickerAiMasterData`). fieldStart/fieldCount are then brute-forced over the record slots by
requiring that the field run of every record that has fields is a run of real field names AND that
consecutive records' runs are contiguous, ending exactly at 65223. Slots found that way:

    +0   nameIndex        int32, into the string table
    +4   namespaceIndex   int32, into the string table (empty for the global namespace)
    +8   byvalTypeIndex   int32, into the il2cpp *type table* (NOT into the type definitions)
    +20  parentIndex      int32, ALSO a type-table index
    +32  flags            uint32
    +44  fieldStart       int32, index into the fields table, -1 when the type declares no field
    +80  fieldCount       uint16 (the following uint16 in that slot is event_count)
    +96  token            uint32

Base classes are free money once you know that: parentIndex points into the type table, which lives in
the binary's Il2CppMetadataRegistration and not in global-metadata.dat, so the raw index means nothing
on its own - but byvalTypeIndex holds a distinct type-table entry for every type definition, so
parentIndex resolves to the definition whose byvalTypeIndex equals it (92% of the parents here: the
rest are entries nothing claims as its byval one, generic instances and duplicates). That is how `id`
shows up for KickerAiMasterData: it is declared by its base Colorful.MasterData, not by
KickerAiMasterData. A parent that cannot be mapped back is reported as unresolved instead of being
silently dropped.
"""
import argparse
import re
import struct
import sys
import zipfile
from pathlib import Path

MAGIC = 0xFAB11BAF
DEFAULT_APK = Path(__file__).resolve().parents[2] / ".local" / "KickFlight-2.11.0-photon-nas.apk"
METADATA_ENTRY = "assets/bin/Data/Managed/Metadata/global-metadata.dat"

# (offset, byte-size) pairs of Il2CppGlobalMetadataHeader, counted as int32 indices / 2.
STRING_PAIR = 2
FIELDS_PAIR = 11
TYPE_DEFINITIONS_PAIR = 19

# Il2CppFieldDefinition: nameIndex int32, typeIndex int32, token uint32. Validated by the field names
# themselves, so a sibling version that pads the record shows up as a lower hit ratio.
FIELD_STRIDES = (12, 8, 16, 20)
FIELD_NAME_OFFSET = 0
FIELD_STRIDE_MIN_RATIO = 0.9

# Il2CppTypeDefinition: searched, never assumed.
TYPE_STRIDE_RANGE = range(88, 129)
TYPE_STRIDE_MIN_RATIO = 0.75
NAME_INDEX_OFFSET = 0
NAMESPACE_INDEX_OFFSET = 4
BYVAL_TYPE_OFFSET = 8
PARENT_OFFSET = 20
TOKEN_OFFSET = 96
PARENT_INVALID = -1
# A sanity bound on a slot read as a count, not a real limit: the biggest type in this metadata
# (PlayerAnimatorParameter) declares 548 fields, so a cap like 512 silently breaks the validation.
MAX_FIELD_COUNT = 8192

PRINTABLE = re.compile(r"^[\x21-\x7e]{1,200}$")


def read_metadata(source: Path) -> bytes:
    """Accepts the metadata file itself or any APK that carries it."""
    if source.suffix == ".apk" or zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as apk:
            return apk.read(METADATA_ENTRY)
    return source.read_bytes()


class TypeDefinition:
    __slots__ = ("index", "name", "namespace", "byval_type", "parent_type", "field_start", "field_count")

    def __init__(self, index, name, namespace, byval_type, parent_type, field_start, field_count):
        self.index = index
        self.name = name
        self.namespace = namespace
        self.byval_type = byval_type
        self.parent_type = parent_type
        self.field_start = field_start
        self.field_count = field_count

    @property
    def full_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name


class Metadata:
    def __init__(self, data: bytes):
        self.data = data
        sanity, self.version = struct.unpack_from("<Ii", data, 0)
        if sanity != MAGIC:
            raise SystemExit(f"not il2cpp metadata: sanity {sanity:#x}")

        self.string_offset, self.string_size = self._pair(STRING_PAIR)
        self.fields_offset, self.fields_size = self._pair(FIELDS_PAIR)
        self.type_definitions_offset, self.type_definitions_size = self._pair(TYPE_DEFINITIONS_PAIR)

        self.field_stride, self.field_count, self.field_stride_ratio = self._discover_field_stride()
        self.type_stride, self.type_count, self.type_stride_ratio = self._discover_type_stride()
        found = self._discover_field_slots()
        (self.field_start_offset, self.field_count_offset, self.field_count_kind,
         self.field_slot_alternatives) = found

        self._records = None
        self._byval_index = None

    # ---- raw reads -------------------------------------------------------------------------------
    def _pair(self, index: int):
        return struct.unpack_from("<2i", self.data, 8 + index * 8)

    def _i32(self, offset: int) -> int:
        return struct.unpack_from("<i", self.data, offset)[0]

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def string(self, index: int) -> str:
        start = self.string_offset + index
        end = self.data.index(b"\0", start)
        return self.data[start:end].decode("utf-8", "replace")

    def is_string_start(self, index: int) -> bool:
        """True when index is the first byte of a string and not the middle of a longer one.

        This is the check that stops `KickerAiMasterData` from matching inside
        `CustomBattleKickerAiMasterData` (that occurrence is not preceded by a NUL).
        """
        if not 0 <= index < self.string_size:
            return False
        if index == 0:
            return self.data[self.string_offset] != 0
        return self.data[self.string_offset + index - 1] == 0 and self.data[self.string_offset + index] != 0

    def is_name(self, index: int) -> bool:
        """A string start whose text looks like an identifier (compiler names like `<>c__DisplayClass` too)."""
        return self.is_string_start(index) and bool(PRINTABLE.match(self.string(index)))

    # ---- layout discovery ------------------------------------------------------------------------
    def _discover_field_stride(self):
        best = None
        for stride in FIELD_STRIDES:
            count = self.fields_size // stride
            if count < 2:
                continue
            good = sum(1 for f in range(count)
                       if self.is_name(self._i32(self.fields_offset + f * stride + FIELD_NAME_OFFSET)))
            ratio = good / count
            if best is None or ratio > best[2]:
                best = (stride, count, ratio)
        if best is None or best[2] < FIELD_STRIDE_MIN_RATIO:
            raise SystemExit(f"cannot find the fields table: offset {self.fields_offset:#x} "
                             f"size {self.fields_size} holds no run of field names")
        return best

    def _discover_type_stride(self):
        best = None
        for stride in TYPE_STRIDE_RANGE:
            count = self.type_definitions_size // stride
            if count < 2:
                continue
            sample = range(0, count, 7)
            good = sum(1 for i in sample
                       if self.is_name(self._i32(self.type_definitions_offset + i * stride + NAME_INDEX_OFFSET)))
            ratio = good / len(sample)
            if best is None or ratio > best[2]:
                best = (stride, count, ratio)
        if best is None or best[2] < TYPE_STRIDE_MIN_RATIO:
            raise SystemExit(f"cannot find the type definitions table: offset {self.type_definitions_offset:#x} "
                             f"size {self.type_definitions_size} holds no run of type names")
        # Re-check the winner over every record before trusting it.
        stride, count, _ = best
        good = sum(1 for i in range(count)
                   if self.is_name(self._i32(self.type_definitions_offset + i * stride + NAME_INDEX_OFFSET)))
        return stride, count, good / count

    def _field_name_index(self, field: int) -> int:
        return self._i32(self.fields_offset + field * self.field_stride + FIELD_NAME_OFFSET)

    def _record_i32(self, i: int, offset: int) -> int:
        return self._i32(self.type_definitions_offset + i * self.type_stride + offset)

    def _record_count(self, i: int, offset: int, kind: str) -> int:
        absolute = self.type_definitions_offset + i * self.type_stride + offset
        return self._i32(absolute) if kind == "i32" else self._u16(absolute)

    def _discover_field_slots(self):
        """Brute-force fieldStart (int32) and fieldCount (uint16/int32) over the record slots.

        A pair is accepted when every record that has fields resolves to a run of real field names,
        consecutive runs are contiguous and the last run ends exactly at the last field entry. That is
        what rejects the slots that merely hold the same kind of number (propertyStart walks the very
        same way, eventStart does not, and both fail the ends-exactly-at-65223 test).
        """
        screens = []
        sample = range(0, self.type_count, 29)
        for fs_off in range(0, self.type_stride - 3, 4):
            good = bad = 0
            for i in sample:
                fs = self._record_i32(i, fs_off)
                if fs < 0:
                    continue
                if fs + 3 >= self.field_count:
                    bad += 1
                    continue
                if all(self.is_name(self._field_name_index(fs + k)) for k in range(4)):
                    good += 1
                else:
                    bad += 1
            if good and bad <= good * 0.05:
                screens.append(fs_off)

        winners = []
        for fs_off in screens:
            starts = [self._record_i32(i, fs_off) for i in range(self.type_count)]
            for kind, step in (("u16", 2), ("i32", 4)):
                for fc_off in range(0, self.type_stride - (1 if kind == "u16" else 3), step):
                    expected = None
                    ok = True
                    for i in range(self.type_count):
                        fc = self._record_count(i, fc_off, kind)
                        if fc == 0 or fc > MAX_FIELD_COUNT:
                            continue
                        fs = starts[i]
                        if fs < 0 or fs + fc > self.field_count or (expected is not None and fs != expected):
                            ok = False
                            break
                        if not all(self.is_name(self._field_name_index(fs + k)) for k in range(fc)):
                            ok = False
                            break
                        expected = fs + fc
                    if ok and expected == self.field_count:
                        winners.append((fs_off, fc_off, kind))

        if not winners:
            raise SystemExit("cannot find fieldStart/fieldCount in the type definition records")
        winners.sort(key=lambda w: (w[0], w[2], w[1]))
        fs_off, fc_off, kind = winners[0]
        return fs_off, fc_off, kind, winners[1:]

    # ---- records ---------------------------------------------------------------------------------
    def records(self):
        if self._records is None:
            out = []
            for i in range(self.type_count):
                base = self.type_definitions_offset + i * self.type_stride
                name_index = struct.unpack_from("<i", self.data, base + NAME_INDEX_OFFSET)[0]
                namespace_index = struct.unpack_from("<i", self.data, base + NAMESPACE_INDEX_OFFSET)[0]
                out.append(TypeDefinition(
                    index=i,
                    name=self.string(name_index) if self.is_string_start(name_index) else "",
                    namespace=self.string(namespace_index) if self.is_string_start(namespace_index) else "",
                    byval_type=self._i32(base + BYVAL_TYPE_OFFSET),
                    parent_type=self._i32(base + PARENT_OFFSET),
                    field_start=self._record_i32(i, self.field_start_offset),
                    field_count=self._record_count(i, self.field_count_offset, self.field_count_kind),
                ))
            self._records = out
        return self._records

    def byval_index(self):
        """type-table entry -> type definition, i.e. how parentIndex is turned into a class."""
        if self._byval_index is None:
            index = {}
            for record in self.records():
                index.setdefault(record.byval_type, record.index)
            self._byval_index = index
        return self._byval_index

    def fields_of(self, record: TypeDefinition):
        if record.field_count <= 0 or record.field_start < 0:
            return []
        return [self.string(self._field_name_index(record.field_start + k)) for k in range(record.field_count)]

    def base_chain(self, record: TypeDefinition):
        """(bases, unresolved) with bases ordered base-most first, plus the first parent that is not a definition."""
        chain = []
        unresolved = None
        seen = {record.index}
        current = record
        while True:
            parent_type = current.parent_type
            if parent_type == PARENT_INVALID:
                break
            index = self.byval_index().get(parent_type)
            if index is None:
                unresolved = parent_type
                break
            if index in seen:
                break
            seen.add(index)
            current = self.records()[index]
            chain.append(current)
        chain.reverse()
        return chain, unresolved

    def layout_note(self) -> str:
        resolved = 0
        total = 0
        for record in self.records():
            if record.parent_type == PARENT_INVALID:
                continue
            total += 1
            resolved += record.parent_type in self.byval_index()
        return (
            f"# layout: typeDefinition stride {self.type_stride} (validated {self.type_stride_ratio:.0%} of "
            f"{self.type_count} names), nameIndex +{NAME_INDEX_OFFSET}, byvalTypeIndex +{BYVAL_TYPE_OFFSET}, "
            f"parentIndex +{PARENT_OFFSET} ({resolved}/{total} resolve to a definition), "
            f"fieldStart +{self.field_start_offset} i32, fieldCount +{self.field_count_offset} {self.field_count_kind}\n"
            f"#         fields stride {self.field_stride} @ {self.fields_offset:#x} ({self.field_count} entries, "
            f"{self.field_stride_ratio:.0%} named), strings @ {self.string_offset:#x} ({self.string_size} B)"
        )


def print_class(metadata: Metadata, record: TypeDefinition, show_inherited: bool) -> None:
    declared = metadata.fields_of(record)
    bases, unresolved = metadata.base_chain(record) if show_inherited else ([], None)
    rows = []
    for base in bases:
        rows += [(name, base.full_name) for name in metadata.fields_of(base)]
    rows += [(name, None) for name in declared]

    parts = [f"{len(declared)} declared"]
    if show_inherited:
        parts.append(f"{len(rows) - len(declared)} inherited")
    head = f"\n{record.full_name}  ({', '.join(parts)} = {len(rows)} fields)" if rows else \
           f"\n{record.full_name}  (0 fields)"
    print(head)
    width = max((len(name) for name, _ in rows), default=0)
    for name, owner in rows:
        print(f"    {name.ljust(width)}  # {owner}" if owner else f"    {name}")
    if unresolved is not None:
        print(f"    # base is type-table entry {unresolved}, which no type definition claims as its byval "
              f"entry (generic instance or duplicate entry); fields of that base are not listed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("classes", nargs="*", help="type names, e.g. TutorialKickerAiMasterData")
    parser.add_argument("--search", help="print every type whose name contains this substring")
    parser.add_argument("--dump-fields", action="append", default=[], metavar="TYPE",
                        help="same as passing the type name positionally (repeatable)")
    parser.add_argument("--namespace", help="only classes whose namespace contains this")
    parser.add_argument("--no-inherited", action="store_true",
                        help="list only the fields the class itself declares")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    args = parser.parse_args()

    metadata = Metadata(read_metadata(args.apk))
    print(f"# {args.apk.name}: metadata version {metadata.version}, {metadata.type_count} type definitions")
    print(metadata.layout_note())
    for extra in metadata.field_slot_alternatives:
        print(f"# note: fieldStart/fieldCount candidate also valid at +{extra[0]}/+{extra[1]} ({extra[2]})")

    wanted = list(args.classes) + list(args.dump_fields)
    if args.search:
        needle = args.search
        for record in metadata.records():
            if needle in record.name and (not args.namespace or args.namespace in record.namespace):
                print(record.full_name)
        if not wanted:
            return 0

    found = set()
    for record in metadata.records():
        if record.name in wanted and (not args.namespace or args.namespace in record.namespace):
            found.add(record.name)
            print_class(metadata, record, not args.no_inherited)
    missing = [name for name in wanted if name not in found]
    if missing:
        print(f"no such type: {', '.join(missing)}; try --search", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
