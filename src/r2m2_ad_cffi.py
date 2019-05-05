# Copyright (C) 2019 Guillaume Valadon <guillaume@valadon.net>

"""
r2m2 plugin that uses miasm as a radare2 disassembly and assembly backend
"""


import os
import sys

from miasm.analysis.machine import Machine
from miasm.core.locationdb import LocationDB
from miasm.expression.expression import ExprInt, ExprLoc

from miasm_embedded_r2m2_ad import ffi


def set_rbuf(rbuf, str_data):
    """Copy a string to a RStrBuf"""

    if len(str_data) < 32:
        rbuf.buf = str_data
    else:
        rbuf.buf = "/!\ buffer too long /!\\"


MIASM_MACHINE = None


def miasm_machine():
    """Retrieve a miasm machine using the R2M2_ARCH environment variable."""

    r2m2_arch = os.getenv("R2M2_ARCH")
    available_archs = Machine.available_machine()

    if not r2m2_arch or r2m2_arch not in available_archs:
        message = "Please specify a valid miasm arch in the R2M2_ARCH "
        message += "environment variable !\nThe following are available: "
        message += ", ".join(available_archs)
        print >> sys.stderr, message + "\n"

        return None

    else:
        global MIASM_MACHINE
        if MIASM_MACHINE is None:
            MIASM_MACHINE = Machine(r2m2_arch)
        return MIASM_MACHINE


@ffi.def_extern()
def miasm_dis(r2_op, r2_address, r2_buffer, r2_length):
    """Disassemble an instruction using miasm."""

    # Cast radare2 variables
    rasmop = ffi.cast("RAsmOp_r2m2*", r2_op)
    opcode = ffi.cast("char*", r2_buffer)

    # Prepare the opcode
    opcode = ffi.unpack(opcode, r2_length)

    # Get the miasm machine
    machine = miasm_machine()
    if machine is None:
        return

    # Disassemble the opcode
    loc_db = LocationDB()
    try:
        mode = machine.dis_engine().attrib
        instr = machine.mn().dis(opcode, mode)
        instr.offset = r2_address
        if instr.dstflow():
            # Remember ExprInt arguments sizes
            args_size = list()
            for i in range(len(instr.args)):
                if isinstance(instr.args[i], ExprInt):
                    args_size.append(instr.args[i].size)
                else:
                    args_size.append(None)

            # Adjust arguments values using the instruction offset
            instr.dstflow2label(loc_db)

            # Convert ExprLoc to ExprInt
            for i in range(len(instr.args)):
                if args_size[i] is None:
                    continue
                if isinstance(instr.args[i], ExprLoc):
                    addr = loc_db.get_location_offset(instr.args[i].loc_key)
                    instr.args[i] = ExprInt(addr, args_size[i])

        dis_str = str(instr)
        dis_len = instr.l
    except Exception:
        dis_str = "/!\ Can't disassemble using miasm /!\\"
        dis_len = 2  # GV: seems fischy !

    # Remaining bytes
    buf_hex = opcode[0:dis_len].encode("hex")

    # Check buffer sizes
    if len(dis_str)-1 > 256:
        dis_str = "/!\ Disassembled instruction is too long /!\\"
    if len(buf_hex)-1 > 256:
        buf_hex = buf_hex[:255]

    # Fill the RAsmOp structure
    rasmop.size = dis_len
    set_rbuf(rasmop.buf_asm, dis_str)


@ffi.def_extern()
def miasm_asm(r2_op, r2_address, r2_buffer):
    """Assemble an instruction using miasm."""

    # Cast radare2 variables
    rasmop = ffi.cast("RAsmOp_r2m2*", r2_op)
    mn_str = ffi.string(r2_buffer)

    # miasm only parses upper case mnemonics
    mn_str = mn_str.upper()
    mn_str = mn_str.replace("X", "x")  # hexadecimal

    # Get the miasm machine
    machine = miasm_machine()
    if machine is None:
        return

    # Get the miasm mnemonic object
    mn = machine.mn()

    # Assemble and return all possible candidates
    loc_db = LocationDB()
    mode = machine.dis_engine().attrib
    instr = mn.fromstring(mn_str, loc_db, mode)
    instr.mode = mode
    instr.offset = r2_address
    if instr.offset and instr.dstflow():
        # Adjust arguments values using the instruction offset
        instr.fixDstOffset()
    asm_instr = [i for i in mn.asm(instr)][0]

    # Check buffer sizes
    if len(asm_instr)-1 > 256:
        print >> sys.stderr, "/!\ Assembled instruction is too long /!\\"
        return

    # Fill the RAsmOp structure
    rasmop.size = len(asm_instr)
    set_rbuf(rasmop.buf, asm_instr)
    rasmop.buf.len = len(asm_instr)
