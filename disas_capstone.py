#!/usr/bin/env python3

from capstone import *
from sys import argv

CODE = bytes.fromhex(argv[1])
mode = CS_MODE_64 if len(argv) < 3 or argv[2] != "32" else CS_MODE_32
print(f"Disassembling {len(CODE)} bytes of code in {'64-bit' if mode == CS_MODE_64 else '32-bit'} mode...\n")

md = Cs(CS_ARCH_X86, mode)
real_insns = []
for i in md.disasm(CODE, 0x1000):
    # if i.mnemonic in ("xor", "cmp", "movsxd", "jz", "jnz", "ret"):
    real_insns.append(f"{i.mnemonic} {i.op_str}")
print("\n".join(real_insns))
