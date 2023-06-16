#!/usr/bin/env python3

"A powerful & Pythonic command-line parsing library.  Give your program Appeal!"
__version__ = "0.6"


# please leave this copyright notice in binary distributions.
license = """
appeal/__init__.py
part of the Appeal software package
Copyright 2021-2023 by Larry Hastings
All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

want_prints = 1
want_prints = 0


from abc import abstractmethod, ABCMeta
import base64
import big.all as big
from big.itertools import PushbackIterator
import builtins
import collections
import enum
import functools
import inspect
import itertools
import math
import os.path
from os.path import basename
import pprint
import shlex
import string
import sys
import textwrap
import time
import types

try:
    from typing import Annotated
    AnnotatedType = type(Annotated[int, str])
    del Annotated
    def dereference_annotated(annotation):
        if isinstance(annotation, AnnotatedType):
            return annotation.__metadata__[-1]
        return annotation
except ImportError:
    def dereference_annotated(annotation):
        return annotation

from . import argument_grouping
from . import text

reversed_dict_values = argument_grouping.reversed_dict_values


POSITIONAL_ONLY = inspect.Parameter.POSITIONAL_ONLY
POSITIONAL_OR_KEYWORD = inspect.Parameter.POSITIONAL_OR_KEYWORD
VAR_POSITIONAL = inspect.Parameter.VAR_POSITIONAL
KEYWORD_ONLY = inspect.Parameter.KEYWORD_ONLY
VAR_KEYWORD = inspect.Parameter.VAR_KEYWORD
empty = inspect.Parameter.empty

try:
    # new in 3.7
    from time import monotonic_ns as event_clock
except ImportError:
    from time import perf_counter

    def event_clock():
        return int(perf_counter() * 1000000000.0)

# new in 3.8
shlex_join = getattr(shlex, 'join', None)
if not shlex_join:
    # note: this doesn't have to be bullet-proof,
    # we only use it for debug print statements.
    def shlex_join(split_command):
        quoted = []
        for s in split_command:
            fields = s.split()
            if len(fields) > 1:
                s = repr(s)
            quoted.append(s)
        return " ".join(quoted)


def update_wrapper(wrapped, wrapper):
    """
    update_wrapper() adds a '__wrapped__'
    attribute.  inspect.signature() then
    follows that attribute, which means it
    returns the wrong (original) signature
    for partial objects if we call
    update_wrapper on them.

    I don't need the __wrapped__ attribute for
    anything, so for now I just remove them.

    I filed an issue to ask about this:
        https://bugs.python.org/issue46761
    """
    functools.update_wrapper(wrapped, wrapper)
    if hasattr(wrapped, '__wrapped__'):
        delattr(wrapped, '__wrapped__')
    return wrapped



class DictGetattrProxy:
    def __init__(self, d, repr_string):
        self.__d__ = d
        self.__repr_string__ = repr_string

    def __repr__(self):
        return self.__repr_string__

    def __getattr__(self, attr):
        return self.__d__.get(attr)


def parameter_name_to_short_option(s):
    assert s and isinstance(s, str)
    return f"-{s[0]}"

def parameter_name_to_long_option(s):
    assert s and isinstance(s, str)
    return f"--{s.lower().replace('_', '-')}"

##
## Options are stored internally in a "normalized" format.
##
##     * For long options, it's the full string (e.g. "--verbose").
##     * For short options, it's just the single character (e.g. "v").
##
## Why bother?  Normalizing them like this makes it lots easier
## to process short options that are glued together (e.g. "-avc").
##
def normalize_option(option):
    assert option and isinstance(option, str)
    assert len(option) != 1
    assert len(option) != 3
    assert option.startswith("-")
    if len(option) == 2:
        return option[1]
    assert option.startswith("--")
    return option

def denormalize_option(option):
    assert option and isinstance(option, str)
    if len(option) == 1:
        return "-" + option
    return option



class AppealBaseException(Exception):
    pass

class AppealConfigurationError(AppealBaseException):
    """
    Raised when the Appeal API is used improperly.
    """
    pass

class AppealUsageError(AppealBaseException):
    """
    Raised when Appeal processes an invalid command-line.
    """
    pass

class AppealCommandError(AppealBaseException):
    """
    Raised when an Appeal command function returns a
    result indicating an error.
    """
    pass

class Preparer:
    pass

#
# used to ensure that the user doesn't use an uncalled
# converter creator
#
# e.g.
#
#    @app.command()
#    def my_command(a:appeal.split):
#        ...
#
# is wrong, the user must call appeal.split:
#
#    @app.command()
#    def my_command(a:appeal.split()):
#        ...
#
# this just adds a field we can check for, and if we find
# it we throw a helpful exception so the user can fix it.
def must_be_instance(callable):
    callable.__appeal_must_be_instance__ = True
    return callable


def is_legal_annotation(annotation):
    if getattr(annotation, "__appeal_must_be_instance__", False):
        result = not isinstance(annotation, types.FunctionType)
        return result
    return True


def _partial_rebind(partial, placeholder, instance, method):
    stack = []
    rebind = False

    if not isinstance(partial, functools.partial):
        raise ValueError("partial is not a functools.partial object")
    while isinstance(partial, functools.partial):
        stack.append(partial)
        func = partial = partial.func
    counter = 0
    while stack:
        counter += 1
        # print(f"*** {counter} stack={stack}\n*** partial={partial}")
        partial = stack.pop()
        if (   (len(partial.args) == 1)
            and (partial.args[0] == placeholder)
            and (not len(partial.keywords))):
                # if we try to use getattr, but it fails,
                # fail over to a functools partial
                use_getattr = method and (not counter)
                if use_getattr:
                    # print(f"*** using getattr method")
                    func2 = getattr(instance, func.__name__, None)
                    use_getattr = func2 is not None
                if not use_getattr:
                    # print(f"*** using new partial method")
                    func2 = functools.partial(func, instance)
                    update_wrapper(func2, func)
                    func = func2
                # print(f"*** func is now {func}")
                partial = func
                continue
        # print(f"*** partial.func={partial.func} != func={func} == rebind={rebind}")
        if partial.func != func:
            partial = functools.partial(func, *partial.args, **partial.keywords)
            update_wrapper(partial, func)

        func = partial
    # print(f"*** returning {partial!r}\n")
    return partial


def partial_rebind_method(partial, placeholder, instance):
    """
    Binds an unbound method curried with a placeholder
    object to an instance and returns the bound method.

    All these statements must be true:
        * "partial" must be a functools.partial() object
          with exactly one curried positional argument
          and zero curried keyword arguments.
        * The one curried positional argument must be
          equal to "placeholder".

    If any of those statements are false, raises ValueError.

    If all those statements are true, this function:
        * extracts the callable from the partial,
        * uses getattr(instance, callable.__name__) to
          bind callable to the instance.
    """
    return _partial_rebind(partial, placeholder, instance, True)

def partial_rebind_positional(partial, placeholder, instance):
    """
    Replaces the first positional argument of a
    functools.partial object with a different argument.

    All these statements must be true:
        * "partial" must be a functools.partial() object
          with exactly one curried positional argument
          and zero curried keyword arguments.
        * The one curried positional argument must be
          equal to "placeholder".

    If any of those statements are false, raises ValueError.

    If all those statements are true, this function:
        * extracts the callable from the partial,
        * uses getattr(instance, callable.__name__) to
          bind callable to instance.
    """
    return _partial_rebind(partial, placeholder, instance, False)


##
## charm
##
## Charm is a simple "bytecode" language.
## Appeal uses Charm to represent mapping
## an Appeal "command" function to the command-line.
##
## See appeal/notes/charm.txt for lots more information.
## Unfortunately that document is out of date.
##

## goal with bytecode design:
##   * no "if" statements inside implementation of any bytecode
##     (sadly, there's one, due to "option" on create_converter)
##
## the interpreter has registers:
##    program
##        the program currently being run.
##    ip
##        the instruction pointer.  an integer, indexes into "program".
##    converters
##        a dict mapping converter "keys" to converters.
##        a converter "key" is any hashable; conceptually a
##        converter key represents a specific instance of a
##        converter being used in the annotation tree.
##        (if you have two parameters annotated with int_float,
##        these two instances get different converter keys.)
##    converter
##        a reference to a converter (or None).
##        the current converter context.
##        conceptually an indirect register like SP or a segment register,
##          you index through it to reference things.
##          specifically:
##              args
##                positional arguments, accessed with an index (-1 permitted).
##              kwargs
##                keyword-only arguments, accessed by name.
##          you can directly store str arguments in these attributes.
##          or, create converters and store (and possibly later retrieve)
##          converter objects in these attributes.
##    o
##        a reference to a converter, a string, or None.
##        a general-purpose register.
##        contains the result of create_converter, pop_converter,
##         consume_argument, and load_converter.
##    total
##        argument counter object (or None).
##        argument counts for this entire command function (so far).
##    group
##        argument counter object (or None).
##        local argument counts just for this argument group.
##
## the interpreter has a stack.  it's used to push/pop all registers
## except ip (which is pushed/popped separately).


## argument counter objects have these fields:
##    count = how many arguments we've consumed
##    minimum = the minimum "arguments" needed
##    maximum = the maximum "arguments" permissible
##    optional = flag, is this an optional group?
##    laden = flag, has anything

def serial_number_generator(*, prefix='', width=0, tuple=False):
    """
    Flexible serial number generator.
    """

    i = 1
    # yield prefix + base64.b32hexencode(i.to_bytes(5, 'big')).decode('ascii').lower().lstrip('0').rjust(3, '0')

    if tuple:
        # if prefix isn't a conventional iterable
        if not isinstance(prefix, (builtins.tuple, list)):
            while True:
                # yield 2-tuple
                yield (prefix, i)
                i += 1
        # yield n-tuple starting with prefix and appending i
        prefix = list(prefix)
        prefix.append(0)
        while True:
            prefix[-1] = i
            yield tuple(prefix)
            i += 1

    if width:
        while True:
            yield f"{prefix}{i:0{width}}"
            i += 1

    while True:
        yield f"{prefix}{i}"
        i += 1

class ArgumentGroup:
    next_serial_number = serial_number_generator(prefix="ag-").__next__

    def __init__(self, minimum=0, maximum=0, *, id=None, optional=True):
        self.minimum = minimum
        self.maximum = maximum
        self.optional = optional
        if id is None:
            id = ArgumentGroup.next_serial_number()
        self.id = id
        self.count = 0
        # a flag you should set when you trigger
        # an option in this group
        self.laden = False

    def satisfied(self):
        if self.optional and (not (self.laden or self.count)):
            return True
        return self.minimum <= self.count <= self.maximum

    def __repr__(self):
        return f"<ArgumentGroup {self.id} optional={self.optional} laden={self.laden} minimum {self.minimum} <= count {self.count} <= maximum {self.maximum} == {bool(self)}>"

    def copy(self):
        o = ArgumentGroup(self.minimum, self.maximum, optional=self.optional, id=self.id)
        o.count = self.count
        o.laden = self.laden
        return o

    def summary(self):
        satisfied = "yes" if self.satisfied() else "no "
        optional = "yes" if self.optional else "no "
        laden = "yes" if self.laden else "no "
        return f"['{self.id}' satisfied {satisfied} | optional {optional} | laden {laden} | min {self.minimum} <= cur {self.count} <= max {self.maximum}]"


class CharmProgram:

    next_id = serial_number_generator(prefix="program-").__next__

    def __init__(self, name=None, minimum=0, maximum=0, *, option=None):
        self.name = name
        self.option = option

        self.id = CharmProgram.next_id()

        self.opcodes = []

        # maps option to its parent option (if any)
        # used for usage
        self.options = {}

        self.total = ArgumentGroup(minimum, maximum, optional=False)

    def __repr__(self):
        s = f" {self.name!r}" if self.name else ""
        return f"<CharmProgram {self.id:02}{s}>"

    def __len__(self):
        return len(self.opcodes)

    def __iter__(self):
        return iter(self.opcodes)

    def __getitem__(self, index):
        return self.opcodes[index]



"""
# cpp

# This is a preprocessor block.
# This Python code prints out the opcode enum.

def print_enum(names, i=0):
    for name in names.split():
        print(f"    {name.strip()} = {i}")
        i += 1

print('class opcode(enum.Enum):')

print_enum('''
    invalid
    jump
    branch_on_o
    call
    create_converter
    load_converter
    load_o
    append_to_args
    add_to_kwargs
    map_option
    consume_argument
    flush_multioption
    set_group
    end

''')

print('''
    # these are removed by the peephole optimizer.
    # the interpreter never sees them.
    # (well... unless you leave in comments during debugging.)
''')

print_enum('''
    no_op
    comment
    label
    jump_to_label
    branch_on_o_to_label
''', i=200)

print()

"""

# Don't modify this stuff directly!
# Everything from here to the
#         # cpp
# line below is generated.
#
# Modify the code in the quotes above and run
#         % python3 cpp.py __init__.py
# to regenerate.

class opcode(enum.Enum):
    invalid = 0
    jump = 1
    branch_on_o = 2
    call = 3
    create_converter = 4
    load_converter = 5
    load_o = 6
    append_to_args = 7
    add_to_kwargs = 8
    map_option = 9
    consume_argument = 10
    flush_multioption = 11
    set_group = 12
    end = 13

    # these are removed by the peephole optimizer.
    # the interpreter never sees them.
    # (well... unless you leave in comments during debugging.)

    no_op = 100
    comment = 101
    label = 102
    jump_to_label = 103
    branch_on_o_to_label = 104

# cpp


class CharmInstruction:
    __slots__ = ['op']

    def copy(self):
        kwargs = {attr: getattr(self, attr) for attr in dir(self) if not (attr.startswith("_") or (attr in ("copy", "op"))) }
        return self.__class__(**kwargs)



class CharmInstructionComment(CharmInstruction):
    __slots__ = ['comment']

    def __init__(self, comment):
        self.op = opcode.comment
        self.comment = comment

    def __repr__(self):
        return f"<comment {self.comment!r}>"


class CharmInstructionNoOp(CharmInstruction): # CharmInstructionNoArgBase

    def __init__(self):
        self.op = opcode.no_op

    def __repr__(self):
        return f"<no-op>"


class CharmInstructionJump(CharmInstruction): # CharmInstructionAddressBase
    """
    jump <address>

    Sets the 'ip' register to <address>.
    <address> is an integer.
    """

    __slots__ = ['address']

    def __init__(self, address):
        self.op = opcode.jump
        self.address = address

    def __repr__(self):
        return f"<jump address={self.address}>"


class CharmInstructionBranchOnO(CharmInstruction): # CharmInstructionAddressBase
    """
    branch_on_o <address>

    If the 'o' register is a true value,
    sets the 'ip' register to <address>.
    <address> is an integer.
    """

    __slots__ = ['address']

    def __init__(self, address):
        self.op = opcode.branch_on_o
        self.address = address

    def __repr__(self):
        return f"<branch_on_o address={self.address}>"


label_id_counter = 0

class CharmInstructionLabel(CharmInstruction):
    """
    label <name>

    Sets a destination in the program that can be
    jumped to by the jump_to_label instruction.

    <name> may be nearly any Python value; the value
    must support basic mathematical properties:
    reflexive, symmetric, transitive, substitution, etc.

    label and *_to_label are both pseudo-instructions.
    They're removed by a pass in the peephole optimizer.
    """
    __slots__ = ['id', 'label']

    def __init__(self, label):
        global label_id_counter
        self.op = opcode.label
        label_id_counter += 1
        self.id = label_id_counter
        self.label = label

    def __repr__(self):
        opcode = str(self.op).rpartition('.')[2]
        label = f" label={self.label!r}" if self.label else ""
        return f"<{opcode} id={self.id}{label}>"

    def __hash__(self):
        return id(CharmInstructionLabel) ^ self.id

class CharmInstructionJumpToLabel(CharmInstruction): # CharmInstructionLabelBase
    """
    jump_to_label <label>

    Sets the 'ip' register to point to the instruction
    after the instance of the <label> instruction in the
    current program.

    label and *_to_label are both pseudo-instructions.
    They're removed by a pass in the peephole optimizer.
    """

    __slots__ = ['label']

    def __init__(self, label):
        self.op = opcode.jump_to_label
        self.label = label

    def __repr__(self):
        label = f" label={self.label!r}" if self.label else ""
        return f"<jump-to-label {label}>"


class CharmInstructionBranchOnOToLabel(CharmInstruction):
    """
    branch_on_o_to_label <label>

    If the 'o' register is a true value,
    sets the 'ip' register to point to the instruction
    after the instance of the <label> instruction in the
    current program.

    label and *_to_label are both pseudo-instructions.
    They're removed by a pass in the peephole optimizer.
    """

    __slots__ = ['label']

    def __init__(self, label):
        self.op = opcode.branch_on_o_to_label
        self.label = label

    def __repr__(self):
        label = f" label={self.label!r}" if self.label else ""
        return f"<branch-on-o-to-label {label}>"


class CharmInstructionCreateConverter(CharmInstruction):
    """
    create_converter <parameter> <key>

    Creates a Converter object using <parameter>,
    an inspect.Parameter object.

    Stores the resulting converter object
    in 'converters[key]' and in the 'o' register.
    """
    __slots__ = ['parameter', 'key', 'is_command']

    def __init__(self, parameter, key, is_command):
        self.op = opcode.create_converter
        self.parameter = parameter
        self.key = key
        self.is_command = is_command

    def __repr__(self):
        return f"<create_converter parameter={parameter!r} key={self.key} is_command={self.is_command}>"

class CharmInstructionLoadConverter(CharmInstruction): # CharmInstructionKeyBase
    """
    load_converter <key>

    Loads a Converter object from 'converters[key]' and
    stores a reference in the 'converter' register.
    """

    __slots__ = ['key']

    def __init__(self, key):
        self.op = opcode.load_converter
        self.key = key

    def __repr__(self):
        return f"<load_converter key={self.key}>"


class CharmInstructionLoadO(CharmInstruction): # CharmInstructionKeyBase
    """
    load_o <key>

    Loads a Converter object from 'converters[key]' and
    stores a reference in the 'o' register.
    """
    __slots__ = ['key']

    def __init__(self, key):
        self.op = opcode.load_o
        self.key = key

    def __repr__(self):
        return f"<load_converter key={self.key}>"

class CharmInstructionAppendToArgs(CharmInstruction):
    """
    append_to_args <parameter> <usage>

    Takes a reference to the value in the 'o' register
    and appends it to 'converter.args'.

    <callable> is a callable object.
    <parameter> and <usage> are strings identifying
    the name of the parameter.  These are all used in
    generating usage information and documentation.
    """

    __slots__ = ['callable', 'parameter', 'discretionary', 'usage', 'usage_callable', 'usage_parameter']

    def __init__(self, callable, parameter, discretionary, usage, usage_callable, usage_parameter):
        self.op = opcode.append_to_args
        self.callable = callable
        self.parameter = parameter
        self.discretionary = discretionary
        self.usage = usage
        self.usage_callable = usage_callable
        self.usage_parameter = usage_parameter

    def __repr__(self):
        return f"<append_to_args callable={self.callable} parameter={self.parameter} discretionary={self.discretionary} usage={self.usage} usage_callable={self.usage_callable} usage_parameter={self.usage_parameter}>"

class CharmInstructionAddToKwargs(CharmInstruction):
    """
    add_to_kwargs <name>

    Takes a reference to the object currently in
    the 'o' register and stores it in 'converter.kwargs[<name>]'.
    (Here 'converter' is the 'converter' register.)

    <name> is a string.
    """

    __slots__ = ['name']

    def __init__(self, name):
        self.op = opcode.add_to_kwargs
        self.name = name

    def __repr__(self):
        return f"<add_to_kwargs name={self.name}>"

# class CharmInstructionPushContext(CharmInstruction): # CharmInstructionNoArgBase
#     """
#     push_context

#     Pushes the current 'converter', 'group', 'o', 'option',
#     and 'total' registers on the stack.
#     """
#     def __init__(self):
#         self.op = opcode.push_context

#     def __repr__(self):
#         return f"<push_context>"

# class CharmInstructionPopContext(CharmInstruction): # CharmInstructionNoArgBase
#     """
#     pop_context

#     Pops the top value from the stack, restoring
#     the previous values of the 'converter', 'group',
#     'o', 'option', and 'total' registers.
#     """
#     def __init__(self):
#         self.op = opcode.pop_context

#     def __repr__(self):
#         return f"<pop_context>"

class CharmInstructionMapOption(CharmInstruction):
    """
    map_option <option> <program> <callable> <parameter> <key> <group>

    Maps the option <option> to the program <program>.

    <program> is self-contained; if the option is invoked
    on the command-line, you may simply 'push' the new
    program on your current CharmInterpreter.

    <callable>, <parameter>, and <key> are used in
    generating usage information.  <key> is the
    converter key for the converter, <parameter>
    is the parameter accepted by that converter
    which this option fills, and <callable> is the
    function that accepts <parameter>.  (The value
    returned by this program becomes the argument for
    <parameter> when calling <callable>.)

    <group> is the id of the ArgumentGroup this is mapped in.
    """
    __slots__ = ['option', 'program', 'callable', 'parameter', 'key', 'group']

    def __init__(self, option, program, callable, parameter, key, group):
        self.op = opcode.map_option
        self.option = option
        self.program = program
        self.callable = callable
        self.parameter = parameter
        self.key = key
        self.group = group

    def __repr__(self):
        return f"<map_option option={self.option!r} program={self.program} key={self.key} parameter={self.parameter} key={self.key} group={self.group}>"

class CharmInstructionConsumeArgument(CharmInstruction):
    """
    consume_argument <is_oparg> <required>

    Consumes an argument from the command-line,
    and stores it in the 'o' register.

    <is_oparg> is a boolean flag:
        * If <is_oparg> is True, you're consuming an oparg.
          You should consume the next command-line argument
          no matter what it is--even if it starts with a
          dash, which would normally indicate a command-line
          option.
        * If <is_oparg> is False, you're consuming a top-level
          command-line positional argument.  You should process
          command-line arguments normally, including
          processing options.  Continue processing until
          you find a command-line argument that isn't
          an option, nor is consumed by any options that
          you might have encountered while processing,
          and then consume that argument to satisfy this
          instruction.

    <required> is also a boolean flag:
        * If <required> is True, this argument is required.
          If there's no string to fill it from the
          command-line, you should raise a usage exception.
        * If <required> is False, this argument isn't required.
          If there's no string to fill it from the
          command-line, that's fine, you should consider
          processing a success and exit.
    """
    __slots__ = ['required', 'is_oparg']

    def __init__(self, required, is_oparg):
        self.op = opcode.consume_argument
        self.required = required
        self.is_oparg = is_oparg

    def __repr__(self):
        return f"<consume_argument required={self.required} is_oparg={self.is_oparg}>"

class CharmInstructionFlushMultioption(CharmInstruction): # CharmInstructionNoArgBase
    """
    flush_multioption

    Calls the flush() method on the object stored in
    the 'o' register.
    """

    def __init__(self):
        self.op = opcode.flush_multioption

    def __repr__(self):
        return f"<flush_multioption>"


class CharmInstructionSetGroup(CharmInstruction):
    """
    set_group <id> <minimum> <maximum> <optional> <repeating>

    Indicates that the program has entered a new argument
    group, and specifies the minimum and maximum arguments
    accepted by that group.  These numbers are stored as
    an ArgumentCount object in the 'group' register.
    """

    __slots__ = ['group', 'id', 'optional', 'repeating']

    def __init__(self, id, minimum, maximum, optional, repeating):
        self.op = opcode.set_group
        self.group = ArgumentGroup(minimum, maximum, optional=optional, id=id)
        self.id = id
        self.optional = optional
        self.repeating = repeating

    def __repr__(self):
        return f"<set_group id={self.id} group={self.group.summary()} optional={self.optional} repeating={self.repeating}>"

class CharmInstructionEnd(CharmInstruction):
    """
    end

    Marks the end of a program.  A no-op, exists only
    to provide some context when reading the trace from
    a running interpreter.
    """

    __slots__ = ['id', 'name']

    def __init__(self, id, name):
        self.op = opcode.end
        self.id = id
        self.name = name

    def __repr__(self):
        return f"<end id={self.id} name={self.name!r}>"


class CharmAssembler:
    """
    Compiles CharmInstruction objects into a list.
    Has a function call for every instruction; calling
    the function appends one of those instructions.

    You can also append a CharmAssembler.  That
    indeed appends the assembler at that point in
    the stream of instructions, and any instructions
    you append to *that* assembler will appear at
    that spot in the final instruction stream.
    """
    def __init__(self, id=None):
        self.id = id

        self.clear()

    def __repr__(self):
        return f"<CharmAssembler '{self.id}'>"

    def _append_instruction(self, o):
        self.opcodes.append(o)
        return o

    def append(self, o):
        if isinstance(o, CharmAssembler):
            if not self.opcodes:
                assert self.contents[-1] == self.opcodes
                self.contents.pop()
            else:
                self.opcodes = []
            self.contents.append(o)
            self.contents.append(self.opcodes)
            return o
        if isinstance(o, CharmInstruction):
            self.opcodes.append(o)
            return o
        raise TypeError('o must be CharmAssembler or CharmInstruction')

    def clear(self):
        self.opcodes = []
        self.contents = [self.opcodes]

    def __len__(self):
        return sum(len(o) for o in self.contents)

    def __bool__(self):
        for o in self.contents:
            if o:
                return True
        return False

    def __getitem__(self, index):
        if not isinstance(index, int):
            raise TypeError(f"CharmAssembler indices must be integers, not {type(index).__name__}")

        for l in self:
            length = len(l)
            if index >= length:
                index -= length
                continue
            return l[index]

        raise IndexError(f"CharmAssembler index out of range")

    def __iter__(self):
        for o in self.contents:
            assert isinstance(o, (list, CharmAssembler))
            if isinstance(o, list):
                if o:
                    yield o
                continue

            yield from o

    def no_op(self):
        op = CharmInstructionNoOp()
        return self._append_instruction(op)

    def comment(self, comment):
        op = CharmInstructionComment(comment)
        return self._append_instruction(op)

    def label(self, name):
        op = CharmInstructionLabel(name)
        return self._append_instruction(op)

    def jump_to_label(self, label):
        op = CharmInstructionJumpToLabel(label)
        return self._append_instruction(op)

    def call(self, program):
        op = CharmInstructionCall(program)
        return self._append_instruction(op)

    def create_converter(self, parameter, key, is_command):
        op = CharmInstructionCreateConverter(
            parameter=parameter,
            key=key,
            is_command=is_command,
            )
        return self._append_instruction(op)

    def load_converter(self, key):
        op = CharmInstructionLoadConverter(
            key=key,
            )
        return self._append_instruction(op)

    def load_o(self, key):
        op = CharmInstructionLoadO(
            key=key,
            )
        return self._append_instruction(op)

    def append_to_args(self, callable, parameter, discretionary, usage, usage_callable, usage_parameter):
        op = CharmInstructionAppendToArgs(
            callable = callable,
            parameter = parameter,
            discretionary = discretionary,
            usage = usage,
            usage_callable = usage_callable,
            usage_parameter = usage_parameter,
            )
        return self._append_instruction(op)

    def add_to_kwargs(self, name):
        op = CharmInstructionAddToKwargs(
            name=name,
            )
        return self._append_instruction(op)

    def map_option(self, option, program, callable, parameter, key, group):
        op = CharmInstructionMapOption(
            option = option,
            program = program,
            callable = callable,
            parameter = parameter,
            key = key,
            group = group,
            )
        return self._append_instruction(op)

    def consume_argument(self, required=False, is_oparg=False):
        op = CharmInstructionConsumeArgument(
            required=required,
            is_oparg=is_oparg,
            )
        return self._append_instruction(op)

    def flush_multioption(self):
        op = CharmInstructionFlushMultioption()
        return self._append_instruction(op)

    def branch_on_o_to_label(self, label):
        op = CharmInstructionBranchOnOToLabel(label=label)
        return self._append_instruction(op)

    def set_group(self, id=None, minimum=0, maximum=0, optional=True, repeating=False):
        op = CharmInstructionSetGroup(id=id, minimum=minimum, maximum=maximum, optional=optional, repeating=repeating)
        return self._append_instruction(op)

    def end(self, id, name):
        op = CharmInstructionEnd(id=id, name=name)
        return self._append_instruction(op)




class CharmCompiler:
    def __init__(self, appeal, *, name=None, converter_key_prefix=None, argument_group_prefix=None, option=None, indent=''):
        self.appeal = appeal
        self.name = name
        self.indent = indent

        if want_prints:
            print(f"[cc]")
            print(f"[cc] {indent}Initializing compiler")
            print(f"[cc]")

        self.program = CharmProgram(name, option=option)

        self.next_converter_key = serial_number_generator(prefix=converter_key_prefix or 'c-').__next__
        self.command_converter_key = None

        self.root = appeal.root

        # The compiler is effectively two passes.
        #
        # First, we iterate over the annotation tree generating instructions.
        # These go into discrete "assemblers" which are carefully ordered in
        # the self.assemblers list.
        #
        # Second, we iterate over self.assemblers and knit togetherthe
        # instructions from every assembler into one big program.
        self.root_a = CharmAssembler("root")

        self.initial_a = a = CharmAssembler("initial")
        self.root_a.append(a)

        self.final_a = CharmAssembler("final")

        self.option_depth = 0

        # options defined in the current argument group
        self.ag_a = self.ag_initialize_a = None
        self.ag_options_a = self.ag_duplicate_options_a = None
        self.ag_options = set()
        self.ag_duplicate_options = set()
        self.next_argument_group_id = serial_number_generator(prefix=f"{name} ag-").__next__

        self.new_argument_group(optional=False, indent=indent)

        self.name_to_callable = {}

    def clean_up_argument_group(self, indent=''):
        if self.ag_a:
            if self.ag_options:
                if want_prints:
                    print(f"[cc]")
                    print(f"[cc] {indent}flushing previous argument group's options.")
                    print(f"[cc]")
                self.ag_initialize_a.append(self.ag_options_a)
                self.ag_options.clear()

            uninteresting_opcodes = set((opcode.comment, opcode.label))
            # if we didn't put anything in one of our assemblers,
            # clear it so we don't have the needless comment lying around
            def maybe_clear_a(a):
                # if length is 0, we don't need to bother clearing, it's already empty
                # if length > 1, it has stuff in it
                if a is None:
                    return
                if len(a) == 1:
                    if a[0].op in uninteresting_opcodes:
                        a.clear()

            maybe_clear_a(self.ag_initialize_a)
            maybe_clear_a(self.ag_options_a)
            # is this redundant? maybe.
            # but ag_duplicate_options_a is in body_a,
            # so we should clear ag_duplicate_options_a
            # before we try to clear body_a.
            maybe_clear_a(self.ag_duplicate_options_a)
            maybe_clear_a(self.body_a)

    def new_argument_group(self, *, optional, indent=''):
        #
        # Every argument group adds at least three assemblers:
        #
        #   * ag_initialize_a, the assembler for initialization code for
        #     this argument group.  starts with a set_group instruction,
        #     then has all the create_converter instructions.
        #   * ag_options_a, the assembler for map_option instructions
        #     for options that *haven't* been mapped before in this
        #     argument group.
        #   * ag_duplicate_options_a, the assembler for map_option
        #     instructions for options that *have* been mapped before
        #     in this argument group.  Initially this is None, and
        #     then we create a fresh one after emitting every
        #     consume_argument opcode.
        #
        # What's this about duplicate options?  It's Appeal trying
        # to be a nice guy, to bend over backwards and allow crazy
        # command-lines.
        #
        # Normally an option is mapped purely based on its membership
        # in an optional group.  Consider this command:
        #
        #     def three_strs(d, e, f, *, o=False): ...
        #
        #     @app.command()
        #     def base(a, b, c, three_strs: d_e_f=None, *, v=False): ...
        #
        # Its usage would look like this:
        #
        #     base [-v] a b c [ [-o] d e f ]
        #
        # -v is mapped the whole time, but -o is only mapped after
        # you have three parameters.
        #
        # Now what if you change it to be like this?
        #
        #     def three_strs(d, e, f, *, o=False): ...
        #
        #     @app.command()
        #     def base(a, b, c, d_e_f:three_strs=None, g_h_i:three_strs=None, *, v=False): ...
        #
        # Since the two mappings of -o are in different groups, it's okay.
        # Usage looks like this:
        #
        #     base [-v] a b c [ [-o] d e f [ [-o] d e f ] ]
        #
        # Still not ambiguous.  But what if you do *this*?
        #
        #     def three_strs(d, e, f, *, o=False): ...
        #
        #     @app.command()
        #     def base(a, b, c, d_e_f:three_strs, g_h_i:three_strs, *, v=False): ...
        #
        # Now everybody's in one big argument group.  And that means
        # we map -o twice in the same group.
        #
        # Appeal permits this because it isn't actually ambiguous.
        # It permits you to map the same option twice in one argument
        # group *provided that* it can intelligently map the duplicate
        # option after a consume_argument opcode--between positional
        # parameters.  So usage looks like this:
        #
        #     base [-v] a b c [-o] d e f [-o] d e f
        #
        # It looks a little strange, but hey man, you're the one who
        # asked Appeal to turn that into a command-line.  It's doing
        # its best.

        self.clean_up_argument_group(indent=indent)

        self.group_id = group_id = self.next_argument_group_id()

        if want_prints:
            print(f"[cc] {indent}new argument group '{group_id}'")
            indent += "  "

        self.ag_a = ag_a = CharmAssembler(group_id)
        self.root_a.append(ag_a)

        # "converters" represent functions we're going to fill with arguments and call.
        # The top-level command is a converter, all the functions we call to convert
        # arguments are converters.
        self.ag_initialize_a = a = CharmAssembler(f"'{group_id}' initialize")
        a.comment(f"{self.program.name} argument group '{group_id}' initialization")
        ag_a.append(a)

        self.ag_options_a = a = CharmAssembler(f"'{group_id}' options")
        a.comment(f"{self.program.name} argument group '{group_id}' options")

        self.body_a = a = CharmAssembler(f"'{group_id}' body")
        a.comment(f"{self.program.name} argument group '{group_id}' body")
        ag_a.append(a)

        # initially in an argument group we don't allow duplicate options.
        # you can only have duplicates after the first consume_argument
        # opcode in an argument group.
        self.ag_duplicate_options_a = None
        self.ag_duplicate_options.clear()

        self.group = self.ag_initialize_a.set_group(id=group_id, optional=optional)
        return self.group

    def reset_duplicate_options_a(self):
        if self.ag_duplicate_options:
            self.ag_duplicate_options.clear()
        elif self.ag_duplicate_options_a:
            self.ag_duplicate_options_a.clear()

        group_id = self.group_id
        self.ag_duplicate_options_a = a = CharmAssembler(f"{group_id} duplicate options")
        a.comment(f"{self.program.name} argument group {group_id} duplicate options")
        self.body_a.append(a)

    def is_converter_discretionary(self, parameter, converter_class):
        optional = (
            # *args and **kwargs are not required
            (parameter.kind in (VAR_POSITIONAL, VAR_KEYWORD))
            or
            # parameters of other types with a default are not required
            (parameter.default is not empty)
            )

        # only actual Converter objects can be discretionary
        is_converter = issubclass(converter_class, Converter)

        return is_converter and optional

    def compile_options(self, parent_callable, key, parameter, options, depth, indent, group_id):
        if want_prints:
            print(f"[cc] {indent}compile_options options={options}")
            indent += "  "
            print(f"[cc] {indent}key={key}")
            print(f"[cc] {indent}parameter={parameter}")
            print(f"[cc] {indent}parameter.kind={parameter.kind}")
            print(f"[cc]")

        cls = self.appeal.root.map_to_converter(parameter)

        assert options

        self.program.options.update({o: self.program.option for o in options})
        name = parent_callable.__name__
        option_names = [denormalize_option(o) for o in options]
        assert option_names
        option_names = " | ".join(option_names)
        program_name = f"{name} {option_names}"
        if cls is SimpleTypeConverterStr:
            # hand-coded program to handle this option that takes
            # a single required str argument.
            if want_prints:
                print(f"[cc] {indent}hand-coded program for simple str")
            program = CharmProgram(name=program_name, minimum=1, maximum=1, option=option_names)
            a = CharmAssembler(self)
            a.set_group(self.next_argument_group_id(), 1, 1, optional=False)
            a.load_converter(key)
            a.consume_argument(required=True, is_oparg=True)
            a.add_to_kwargs(parameter.name)
            a.end(name=program_name, id=program.id)
            program.opcodes = a.opcodes
        else:
            annotation = dereference_annotated(parameter.annotation)
            if not is_legal_annotation(annotation):
                raise AppealConfigurationError(f"{parent_callable.__name__}: parameter {parameter.name!r} annotation is {parameter.annotation}, which you can't use directly, you must call it")

            multioption = issubclass(cls, MultiOption)

            if want_prints:
                print(f"[cc] {indent}<< recurse on option >>")

            cc = CharmCompiler(self.appeal, name=program_name, converter_key_prefix=key + f".{parameter.name}-", argument_group_prefix=group_id + "-", option=option_names, indent=indent)

            add_to_kwargs = key, parameter.name
            program = cc(annotation, parameter.default, is_option=True, multioption=multioption, add_to_kwargs=add_to_kwargs)
            program.option = option_names
            self.program.options.update(program.options)

        for option in options:
            # option doesn't have to be unique in this argument group,
            # but it must be unique per consumed argument.
            # (you can't define the same option twice without at least one consume_argument between.)

            if option not in self.ag_options:
                self.ag_options.add(option)
                destination = self.ag_options_a
            elif self.ag_duplicate_options_a:
                if option in self.ag_duplicate_options:
                    raise AppealConfigurationError(f"multiple definitions of option {denormalize_option(option)} are ambiguous (no arguments consumed in between definitions)")
                destination = self.ag_duplicate_options_a
                self.ag_duplicate_options.add(option)
            else:
                raise AppealConfigurationError(f"argument group initialized with multiple definitions of option {denormalize_option(option)}, ambiguous")

            if want_prints:
                print(f"[cc] {indent}option={option}")
                print(f"[cc] {indent}    program={program}")
                print(f"[cc] {indent}    destination={destination}")
            destination.map_option(option, program, parent_callable, parameter, key, group_id)

    def map_options(self, callable, parameter, signature, key, depth, indent, group_id):
        if want_prints:
            print(f"[cc] {indent}map_options parameter={parameter}")
            indent += "  "
            print(f"[cc] {indent}key={key}")
            if not signature.parameters:
                print(f"[cc] {indent}signature=()")
            else:
                print(f"[cc] {indent}signature=(")
                for _k, _v in signature.parameters.items():
                    print(f"[cc] {indent}    {_v},")
                print(f"[cc] {indent}    )")
            print(f"[cc]")
        _, kw_parameters, _ = self.appeal.fn_database_lookup(callable)
        mappings = kw_parameters.get(parameter.name, ())

        if not mappings:
            p = signature.parameters.get(parameter.name)
            assert p
            annotation = dereference_annotated(p.annotation)
            default = p.default
            default_options = self.appeal.root.default_options
            assert builtins.callable(default_options)
            default_options(self.appeal, callable, parameter.name, annotation, default)

        parameter_index_to_options = collections.defaultdict(list)
        parameters = []
        mapped_options = []
        for option_entry in kw_parameters[parameter.name]:
            option, callable2, parameter = option_entry
            mapped_options.append(option)
            # assert callable is not empty
            assert callable == callable2

            # not all parameters are hashable.  (default might be a list, etc.)
            try:
                parameter_index = parameters.index(parameter)
            except ValueError:
                parameter_index = len(parameters)
                parameters.append(parameter)

            parameter_index_to_options[parameter_index].append(option)

        for parameter_index, options in parameter_index_to_options.items():
            parameter = parameters[parameter_index]
            self.compile_options(callable, key, parameter, options, depth, indent, group_id)

        return mapped_options


    def compile_parameter(self, depth, indent, parameter, pgi, usage_callable, usage_parameter, multioption=False, append=None, add_to_kwargs=None, is_command=False):
        """
        returns is_degenerate, a boolean, True if this entire subtree is "degenerate".
        """

        if want_prints:
            print(f"[cc] {indent}compile_parameter {parameter}")
            indent += "    "
            required = "yes" if parameter.default is empty else "no"
            print(f"[cc] {indent}required? {required}")
            print(f"[cc] {indent}depth={depth}")
            print(f"[cc] {indent}multioption={multioption}")
            print(f"[cc] {indent}append={append}")
            print(f"[cc]")

        maps_to_positional = set((POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD, VAR_POSITIONAL))
        tracked_by_argument_grouping = set((POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD, VAR_POSITIONAL))

        # hard-coded, at least for now
        annotation = dereference_annotated(parameter.annotation)
        if annotation is not empty:
            cls = annotation
        elif parameter.default is not empty:
            cls = type(parameter.default)

        callable = annotation
        cls = self.root.map_to_converter(parameter)
        signature = cls.get_signature(parameter)
        parameters = signature.parameters
        if want_prints:
            print(f"[cc] {indent}cls={cls}")
            if not parameters:
                print(f"[cc] {indent}signature=()")
            else:
                print(f"[cc] {indent}signature=(")
                for _k, _v in parameters.items():
                    print(f"[cc] {indent}    {_v},")
                print(f"[cc] {indent}    )")
            print(f"[cc]")

        # is_degenerate only applies to depth > 1.
        is_degenerate = (not depth) and (len(parameters) < 2)

        if want_prints:
            print(f"[cc] {indent}is_degenerate={is_degenerate}")
            print(f"[cc] {indent}len(parameters)={len(parameters)}")
            print(f"[cc]")

        # fix chicken-and-egg problem:
        # create converter key here, so we can use it in multioption block
        converter_key = self.next_converter_key()
        if not self.command_converter_key:
            # guarantee that the root converter has a special key
            self.command_converter_key = converter_key

        if multioption:
            assert not append
            label_flush_multioption = CharmInstructionLabel("flush_multioption")
            label_after_multioption = CharmInstructionLabel("after_multioption")

            assert self.command_converter_key
            load_o_op = self.ag_initialize_a.load_o(key=self.command_converter_key)
            self.ag_initialize_a.branch_on_o_to_label(label_flush_multioption)

        # leaves the converter in the "o" register
        op = self.ag_initialize_a.create_converter(parameter=parameter, key=converter_key, is_command=is_command)

        append_op = None
        if append:
            self.body_a.load_o(key=converter_key)
            append_op = self.body_a.append_to_args(**append)
        elif add_to_kwargs:
            parent_key, parameter_name = add_to_kwargs
            self.body_a.load_converter(key=parent_key)
            self.body_a.load_o(key=converter_key)
            self.body_a.add_to_kwargs(name=parameter_name)

        if multioption:
            load_o_op.key = converter_key
            self.ag_initialize_a.jump_to_label(label_after_multioption)
            self.ag_initialize_a.append(label_flush_multioption)
            op = self.ag_initialize_a.flush_multioption()
            self.ag_initialize_a.append(label_after_multioption)

        var_keyword = None
        kw_parameters_seen = set()
        _, kw_parameters, positionals = self.appeal.fn_database_lookup(callable)

        # we need to delay mapping options sometimes.
        #
        # if depth=0, we're in the command function (or the root option function).
        # all options go into the first argument group.
        #
        # if depth>0, we're in a child annotation function. all options go into
        # the same group as the first argument (if any)
        mapped_options = False
        def map_options():
            nonlocal mapped_options
            if mapped_options:
                return
            mapped_options = True
            if want_prints:
                print(f"[cc] {indent}automatically map keyword-only parameters to options")

            for i, (parameter_name, p) in enumerate(parameters.items()):
                if p.kind == KEYWORD_ONLY:
                    if p.default == empty:
                        raise AppealConfigurationError(f"{usage_callable}: keyword-only argument {parameter_name} doesn't have a default value")
                    kw_parameters_seen.add(parameter_name)
                    self.map_options(callable, p, signature, converter_key, depth, indent, self.group.id)
                    continue
                if p.kind == VAR_KEYWORD:
                    var_keyword = parameter_name
                    continue

            # step 2: populate **kwargs-only options
            # (options created with appeal.option(), where the parameter_name doesn't
            #  appear in the function, so the output goes into **kwargs)
            if want_prints:
                print(f"[cc] {indent}map user-defined options")

            kw_parameters_unseen = set(kw_parameters) - kw_parameters_seen
            if kw_parameters_unseen:
                if not var_keyword:
                    raise AppealConfigurationError(f"{usage_callable}: there are options that must go into **kwargs, but this callable doesn't accept **kwargs.  options={kw_parameters_unseen}")
                for parameter_name in kw_parameters_unseen:
                    parameter = inspect.Parameter(parameter_name, KEYWORD_ONLY)
                    self.map_options(callable, parameter, signature, converter_key, depth, indent, self.group.id)

        if not depth:
            map_options()

        group = None

        # Consider this:
        #
        #  def my_int(s): return int(s)
        #  @app.command()
        #  def foo(abc:my_int): ...
        #
        # In usage we'd rather see "abc" than "s".  So this is special-cased.
        # Appeal calls this a "degenerate converter tree"; it's a tree of converter
        # functions that only have one positional parameter each.  Appeal will by
        # default use the usage information from the parameter from the root parameter
        # of that degenerate converter tree--in this case, the parameter "abc" from
        # the function "foo".

        if want_prints:
            print(f"[cc] {indent}compile positional parameters")
            print(f"[cc]")
            indent += "    "

        for i, (parameter_name, p) in enumerate(parameters.items()):
            if not p.kind in maps_to_positional:
                continue

            annotation = dereference_annotated(p.annotation)
            if not is_legal_annotation(annotation):
                raise AppealConfigurationError(f"{callable.__name__}: parameter {p.name!r} annotation is {p.annotation}, which you can't use directly, you must call it")

            # FIXME it's lame to do this here,
            # you need to rewrite compile_parameter so it
            # always recurses for positional parameters
            cls = self.root.map_to_converter(p)

            if p.kind == VAR_POSITIONAL:
                label = self.body_a.label("var_positional")
                index = -1
            else:
                index = i

            if is_degenerate:
                usage_parameter = usage = None
            else:
                usage_callable = callable
                usage = usage_parameter = parameter_name

            usage = positionals.get(parameter_name, usage)

            # only create new groups here if it's an optional group
            # (we pre-create the initial, required group)
            pgi_parameter = next(pgi)

            if want_prints:
                printable_default = "(empty)" if p.default is empty else repr(p.default)

                print(f"[cc] {indent}positional parameter {i}: p={p}")
                print(f"[cc] {indent}    p.kind={p.kind!s}")
                print(f"[cc] {indent}    annotation={annotation.__name__}")
                print(f"[cc] {indent}    default={printable_default} cls={cls}")
                print(f"[cc] {indent}    cls={cls}")
                print(f"[cc] {indent}    pgi_parameter={pgi_parameter}")

            if pgi_parameter.first_in_group and (not pgi_parameter.in_required_group):
                group = self.group = self.new_argument_group(optional=True, indent=indent + "    ")

            map_options()

            self.body_a.load_converter(key=converter_key)
            if cls is SimpleTypeConverterStr:
                if want_prints:
                    print(f"[cc] {indent}    simple str converter, consume_argument and append.")
                self.body_a.consume_argument(required=pgi_parameter.required, is_oparg=bool(self.option_depth))
                op = self.body_a.append_to_args(callable=callable, parameter=parameter_name, discretionary=False, usage=usage, usage_callable=usage_callable, usage_parameter=usage_parameter)
                self.reset_duplicate_options_a()
            else:
                if want_prints:
                    print(f"[cc] {indent}    << recurse on parameter >>")
                discretionary = self.is_converter_discretionary(p, cls)
                append = {'callable': callable, 'parameter': parameter_name, "discretionary": discretionary, "usage": usage, 'usage_callable': usage_callable, 'usage_parameter': usage_parameter }
                is_degenerate_subtree = self.compile_parameter(depth + 1, indent + "    ", p, pgi, usage_callable, usage_parameter, None, append=append, is_command=False)
                is_degenerate = is_degenerate and is_degenerate_subtree

            if p.kind == VAR_POSITIONAL:
                group.repeating = True
                self.body_a.jump_to_label(label)

            if want_prints:
                print(f"[cc]")

        map_options()

        if append_op and not is_degenerate:
            if want_prints:
                print(f"[cc] {indent}suppress usage for non-leaf parameter {append_op.usage}")
            append_op.usage = None

        return is_degenerate


    def __call__(self, callable, default, is_option=False, multioption=None, add_to_kwargs=None):
        indent = self.indent

        if self.name is None:
            self.name = callable.__name__
            self.program.name = self.name

        parameter_name = callable.__name__
        while True:
            if parameter_name.startswith('<'):
                parameter_name = parameter_name[1:-1]
                continue
            if parameter_name.endswith("()"):
                parameter_name = parameter_name[:-2]
                continue
            break

        if want_prints:
            print(f"[cc]")
            print(f"[cc] {indent}Compiling '{self.name}'")
            print(f"[cc]")

        # in Python 3.11, inspect.Parameter won't allow you to use
        # 'lambda' (or '<lambda>') as a parameter name.  And we aren't
        # doing that... not *really*.  It's not a *real* Parameter,
        # we just use one of those because of the way _compile recurses.
        # But if we're compiling a lambda function, we create a
        # Parameter out of the function's name, which is '<lambda>',
        # and, well... we gotta use *something*.  (hope this works!)
        fix_lambda = parameter_name == 'lambda'
        if fix_lambda:
            parameter_name = '_____lambda______'

        def signature(p):
            cls = self.appeal.map_to_converter(p)
            signature = cls.get_signature(p)
            return signature
        pg = argument_grouping.ParameterGrouper(callable, default, signature=signature)
        pgi = pg.iter_all()

        kind = KEYWORD_ONLY if is_option else POSITIONAL_ONLY
        if is_option:
            self.option_depth += 1
        parameter = inspect.Parameter(parameter_name, kind, annotation=callable, default=default)
        if fix_lambda and (getattr(parameter, '_name', '') == parameter_name):
            parameter._name = 'lambda'
        self.compile_parameter(0, indent, parameter, pgi, usage_callable=None, usage_parameter=None, multioption=multioption, add_to_kwargs=add_to_kwargs, is_command=True)

        self.finalize()

        if is_option:
            self.option_depth -= 1

        if want_prints:
            print(f"[cc] {indent}compilation of {parameter_name} complete.")
            print(f"[cc]")
            if not self.option_depth:
                print()


        return self.program


    def finalize(self):
        """
        Performs a finalization pass on program:

        * Computes total and group min/max values.
        * Convert label/jump_to_label pseudo-ops into
          absolute jump ops.
        * Simple peephole optimizations to remove redundant
          load_* ops and jump-to-jumps.
        """

        self.clean_up_argument_group()

        self.final_a.end(self.program.id, self.name)
        self.root_a.append(self.final_a)

        p = self.program.opcodes
        for opcodes in self.root_a:
            p.extend(opcodes)

        labels = {}
        jump_fixups = []
        total = self.program.total
        group = None
        converter = None
        o = None
        option = None
        stack = []
        groups = []

        optional = False

        i = 0

        while i < len(p):
            op = p[i]

            # remove labels
            if op.op == opcode.label:
                if op in labels:
                    raise AppealConfigurationError(f"label used twice: {op}")
                labels[op] = i
                del p[i]
                # forget current registers,
                # who knows what state the interpreter
                # will be in when we jump here.
                converter = o = None
                continue
            if op.op in (opcode.jump_to_label, opcode.branch_on_o_to_label):
                jump_fixups.append(i)

            # remove no_ops
            if op.op == opcode.no_op:
                del p[i]
                continue
            if op.op == opcode.comment:
                # if 1:
                if not want_prints:
                    del p[i]
                    continue

            # compute total and group values
            if op.op == opcode.set_group:
                group = op.group
                optional = op.optional
                if op.repeating:
                    if total:
                        total.maximum = math.inf
            if op.op == opcode.consume_argument:
                if total:
                    if not optional:
                        total.minimum += 1
                    total.maximum += 1
                if group:
                    group.minimum += 1
                    group.maximum += 1

            # discard redundant load_converter and load_o ops
            if op.op == opcode.load_converter:
                if converter == op.key:
                    del p[i]
                    continue
                converter = op.key
            if op.op == opcode.load_o:
                if o == op.key:
                    del p[i]
                    continue
                o = op.key
            if op.op == opcode.create_converter:
                o = op.key
            if op.op == opcode.consume_argument:
                o = '(string value)'
            # if op.op == opcode.push_context:
            #     # stack.append(CharmContextStackEntry(converter, group, o, total))
            #     stack.append(CharmContextStackEntry(converter, o, group, groups))
            # if op.op == opcode.pop_context:
            #     context = stack.pop()
            #     converter = context.converter
            #     group = context.group
            #     o = context.o
            #     # total = context.total

            i += 1

        # now process jump fixups:
        # replace *_to_label ops with absolute jump ops
        opcode_map = {
            opcode.jump_to_label: CharmInstructionJump,
            opcode.branch_on_o_to_label: CharmInstructionBranchOnO,
        }
        for i in jump_fixups:
            op = p[i]
            new_instruction_cls = opcode_map[op.op]
            address = labels.get(op.label)
            if address is None:
                raise AppealConfigurationError(f"unknown label {op.label}")
            p[i] = new_instruction_cls(address)

        # and *now* do a jump-to-jump peephole optimization
        # (I don't know if Appeal can actually generate jump-to-jumps)
        for i in jump_fixups:
            op = p[i]
            while True:
                op2 = p[op.address]
                if op2.op != opcode.jump:
                    break
                op.address = op2.address

        return p


def charm_compile(appeal, callable, default=empty, name=None, *, is_option=False):
    if name is None:
        name = callable.__name__
    cc = CharmCompiler(appeal, name=name)
    program = cc(callable, default, is_option=is_option)
    return program


def charm_print(program, indent=''):
    programs = collections.deque((program,))
    print_divider = False
    seen = set((program.id,))
    specially_formatted_opcodes = set((opcode.comment, opcode.label))
    while programs:
        if print_divider:
            print("________________")
            print()
        else:
            print_divider = True
        program = programs.popleft()
        width = math.floor(math.log10(len(program))) + 1
        padding = " " * width
        indent2 = indent + f"{padding}|   "
        empty_line = indent2.rstrip()
        print(program)
        print_leading_blank_line = False
        for i, op in enumerate(program):
            prefix = f"{indent}{i:0{width}}| "

            # specialized opcode printers
            if op.op in specially_formatted_opcodes:
                if print_leading_blank_line:
                    print(empty_line)
                    print_leading_blank_line = False
                if op.op == opcode.comment:
                    print(f"{prefix}# {op.comment}")
                else:
                    print(f"{prefix}{op.label}:")
                print(empty_line)
                continue

            # generic opcode printer
            print_leading_blank_line = True
            suffix = ""
            printable_op = str(op.op).rpartition(".")[2]
            print(f"{prefix}{printable_op}{suffix}")
            for slot in op.__class__.__slots__:
            # for slot in dir(op):
                if slot.startswith("_") or slot in ("copy", "op"):
                    continue
                value = getattr(op, slot, None)
                if slot == "program":
                    print(f"{indent2}program={value}")
                    value_id = value.id
                    if value_id not in seen:
                        programs.append(value)
                        seen.add(value_id)
                    continue
                if slot == "callable":
                    value = value.__name__ if value is not None else value
                elif value == empty:
                    value = "(empty)"
                elif isinstance(value, ArgumentGroup):
                    value = value.summary()
                else:
                    value = repr(value)
                print(f"{indent2}{slot}={value}")
    print()



class CharmProgramIterator:
    __slots__ = ['program', 'opcodes', 'length', 'ip']

    def __init__(self, program):
        self.program = program
        self.opcodes = program.opcodes
        self.length = len(program)
        self.ip = 0

    def __repr__(self):
        return f"<{self.__class__.__name__} program={self.program} ip={self.ip}>"

    def __repr__(self):
        return f"[{self.program}:{self.ip}]"

    def __next__(self):
        if not bool(self):
            raise StopIteration
        op = self.opcodes[self.ip]
        self.ip += 1
        if 0:
            print(f">> {hex(id(self))} ip -> ", op)
        return op

    def __bool__(self):
        return 0 <= self.ip < self.length

    def jump(self, address):
        self.ip = address

    def jump_relative(self, delta):
        self.ip += delta
        if not self:
            raise RuntimeError(f"Jumped outside current program, ip={self.ip}, len(program)={self.length}")


class CharmBaseInterpreter:
    """
    A bare-bones interpreter for Charm programs.
    Doesn't actually interpret anything;
    it just provides the registers and the iterator
    and some utility functions like jump, push, and pop.
    Actually interpreting the instructions is up to
    the user.
    """
    def __init__(self, program, *, name=''):
        self.name = name
        self.call_stack = []

        assert program

        # registers

        self.program = program
        # shh, don't tell anybody,
        # the ip register technically lives *inside* the iterator.
        self.ip = CharmProgramIterator(program)

        self.converter = None
        self.o = None
        self.group = None

        self.converters = {}
        self.groups = []


    def repr_ip(self, ip=None):
        s = "--"

        if self.ip is not None:
            if ip is None:
                ip = self.ip.ip
            length = len(self.ip.program)
            if 0 <= ip < length:
                width = math.floor(math.log10(length) + 1)
                s = f"{ip:0{width}}"
        return s

    def __repr__(self):
        ip = self.repr_ip()
        group = self.group and self.group.summary()
        converter = self.repr_converter(self.converter)
        o = self.repr_converter(self.o)
        return f"<{self.__class__.__name__} [{ip}] converter={converter!s} o={o!s} group={group!s}>"

    def repr_converter(self, converter):
        if self.converters:
            width = math.floor(math.log10(len(self.converters)) + 1)
            for key, value in self.converters.items():
                if converter == value:
                    return repr([key]) + "=" + repr(converter)
        return repr(converter)

    @big.BoundInnerClass
    class CharmProgramStackEntry:
        __slots__ = ['interpreter', 'ip', 'program', 'converter', 'o', 'group', 'groups']

        def __init__(self, interpreter):
            self.interpreter = interpreter
            self.ip = interpreter.ip
            self.program = interpreter.program
            self.converter = interpreter.converter
            self.o = interpreter.o
            self.group = interpreter.group
            self.groups = interpreter.groups

        def restore(self):
            interpreter = self.interpreter
            interpreter.ip = self.ip
            interpreter.program = self.program
            interpreter.converter = self.converter
            interpreter.o = self.o
            interpreter.group = self.group
            interpreter.groups = self.groups

        def __repr__(self):
            return f"<CharmProgramStackEntry ip={self.ip} program={self.program.name!r} converter={self.converter} o={self.o} group={self.group.summary() if self.group else 'None'} groups=[{len(self.groups)}]>"


    def __iter__(self):
        return self

    def __next__(self):
        while True:
            if not (self.ip or self.call_stack):
                raise StopIteration
            try:
                ip = self.ip.ip
                op = self.ip.__next__()
                return ip, op
            except StopIteration as e:
                self.finish()
                continue

    # def __bool__(self):
    #     return bool(self.ip) or any(bool(cse.ip) for cse in self.call_stack)
    def running(self):
        return bool(self.ip) or any(bool(cse.ip) for cse in self.call_stack)

    def rewind_one_instruction(self):
        if self.ip is None:
            raise StopIteration
        self.ip.jump_relative(-1)

    def call(self, program):
        cpse = self.CharmProgramStackEntry()
        self.call_stack.append(cpse)

        self.program = program
        self.ip = CharmProgramIterator(program)
        self.groups = []
        self.converter = self.o = self.group = None

    def finish(self):
        if self.call_stack:
            cpse = self.call_stack.pop()
            cpse.restore()
        else:
            self.ip = None

    def abort(self):
        self.ip = None
        self.call_stack.clear()

    def unwind(self):
        while self.call_stack:
            self.finish()
        self.abort()




def _charm_usage(program, usage, closing_brackets, formatter, arguments_values, option_values):
    ci = CharmBaseInterpreter(program)
    program_id_to_option = collections.defaultdict(list)

    def add_option(op):
        program_id_to_option[op.program.id].append(op)

    def flush_options():
        for program_id, op_list in program_id_to_option.items():
            options = []
            for op in op_list:
                options.append(denormalize_option(op.option))
            full_name = f"{op.callable.__name__}.{op.parameter.name}"
            option_value = "|".join(options)
            option_values[full_name] = option_value

            usage.append(" [")
            usage.append(option_value)

            usage.append(" ")
            old_len_usage = len(usage)
            _charm_usage(op.program, usage, closing_brackets, formatter, arguments_values, option_values)
            if len(usage) == old_len_usage:
                # this option had no arguments, we don't want the space
                usage.pop()

            usage.append("]")

    last_op = None
    first_argument_in_group = True
    for ip, op in ci:
        # print(f"op={op}")
        if ((last_op == opcode.map_option)
            and (op.op != last_op)):
            flush_options()

        if op.op == opcode.map_option:
            add_option(op)
        elif op.op == opcode.set_group:
            if op.optional:
                usage.append(" [")
                closing_brackets.append("]")
                if op.repeating:
                    closing_brackets.append("... ")
            first_argument_in_group = True
        elif op.op == opcode.append_to_args:
            # append_to_args can only be after one of those two opcodes!
            # if last_op.op in (opcode.consume_argument, opcode.load_o):
                if op.usage:
                    if first_argument_in_group:
                        first_argument_in_group = False
                    else:
                        usage.append(" ")
                    full_name = f"{op.usage_callable.__name__}.{op.usage_parameter}"
                    arguments_values[full_name] = op.usage
                    usage.append(formatter(op.usage))
        last_op = op

    flush_options()


def charm_usage(program, *, formatter=str):
    usage = []
    closing_brackets = []
    arguments_values = {}
    option_values = {}
    _charm_usage(program, usage, closing_brackets, formatter, arguments_values, option_values)
    usage.extend(closing_brackets)
    # print(f"arguments_values={arguments_values}")
    # print(f"option_values={option_values}")
    return "".join(usage).strip(), arguments_values, option_values




class CharmInterpreter(CharmBaseInterpreter):
    def __init__(self, processor, program, *, name=''):
        super().__init__(program, name=name)
        self.processor = processor
        self.program = program

        self.appeal = processor.appeal
        self.argi = processor.argi

        self.command_converter_key = None

        # The first part of the __call__ loop consumes *opcodes.*
        self.opcodes_prefix = "#---"
        # The second part of the __call__ loop consumes *cmdline arguments.*
        self.cmdline_prefix = "####"

        self.options = self.Options()



    # overloaded from CharmBasicInterpreter.
    # it's called automatically when we exit a program.
    def finish(self):
        program = self.program
        super().finish()
        if want_prints:
            if program != self.program:
                print(f"{self.opcodes_prefix}")
                print(f"{self.opcodes_prefix} finished {program}")


    ##
    ## "options"
    ##
    ## Options in Appeal can be hierarchical.
    ## One option can map in child options.
    ## These child options have a limited lifespan.
    ##
    ## Example:
    ##
    ##     def color_option(color, *, brightness=0, hue=0): ...
    ##     def position_option(x, y, z, *, polar=False): ...
    ##
    ##     @app.command()
    ##     def frobnicate(a, b, c, *, color:color_option=Color('BLUE'), position:position_option=Position(0, 0, 0)): ...
    ##
    ## If you then run this command-line:
    ##
    ##     % python3 myscript frobnicate A --color red ...
    ##                                                 ^
    ##                                                 |
    ##      +------------------------------------------+
    ##      |
    ## At THIS point. we've run the Charm program associated
    ## with "--color".  It's mapped in two new options,
    ## "--brightness" (and probably "-b") and "--hue" (and maybe "-h").
    ## These are "child options"; they're children of "--color".
    ##
    ## If the next thing on the command-line is "--brightness"
    ## or "--hue", we handle that option.  But if the next thing
    ## is a positional argument to frobnicate (which will be
    ## the argument supplied to parameter "b"), or the option
    ## "--position", those two child options are *unmapped*.
    ##
    ## We manage these options lifetimes with a *stack* of options dicts.
    ##
    ##  self.options is the options dict at the top of the stack.
    ##  self.stack is a stack of the remaining options dicts,
    ##     with the bottom of the stack at self.options_stack[0].
    ##
    ## An "options token" represents a particular options dict in
    ## the stack.  Each entry in the stack gets a token.  We then
    ## store the toke on the option.  This is how we unmap the
    ## children of a sibling's option; when the user executes an
    ## option on the command-line, we pop the options stack until
    ## the options dict mapped to that token is at the top of the
    ## stack.
    ##

    @big.BoundInnerClass
    class Options:

        def __init__(self, interpreter):
            self.interpreter = interpreter
            self.stack = []
            self.token_to_dict = {}
            self.dict_id_to_token = {}

            # We want to sort options tokens.
            # But serial_number_generator(tuple=True) is ugly and verbose.
            # This seems nicer.

            class OptionsToken:
                def __init__(self, i):
                    self.i = i
                    self.repr = f"<options-{self.i}>"
                def __repr__(self):
                    return self.repr
                def __lt__(self, other):
                    return self.i < other.i
                def __eq__(self, other):
                    return self.i == other.i
                def __hash__(self):
                    return self.i

            def token_generator():
                i = 1
                while True:
                    yield OptionsToken(i)
                    i += 1

            self.next_token = token_generator().__next__
            self.reset()

        def reset(self):
            options = {}
            token = self.next_token()
            self.options = self.token_to_dict[token] = options
            self.token = self.dict_id_to_token[id(options)] = token
            return token

        def push(self):
            self.stack.append((self.options, self.token))
            token = self.reset()

            if want_prints:
                print(f"{self.interpreter.cmdline_prefix} {self.interpreter.ip_spacer} Options.push token={token}")

        def pop(self):
            options_id = id(self.options)
            token = self.dict_id_to_token[options_id]
            del self.dict_id_to_token[options_id]
            del self.token_to_dict[token]

            options, token = self.stack.pop()
            self.options = options
            self.token = token

            if want_prints:
                options = [denormalize_option(option) for option in options]
                options.sort(key=lambda s: s.lstrip('-'))
                options = "{" + " ".join(options) + "}"
                print(f"{self.interpreter.cmdline_prefix} {self.interpreter.ip_spacer} Options.pop: popped to token {token}, options={options}")

        def pop_until_token(self, token):
            if self.token == token:
                if want_prints:
                    print(f"{self.interpreter.cmdline_prefix} {self.interpreter.ip_spacer} Options.pop_until_token: token={token} is current token.  popped 0 times.")
                return
            options_to_stop_at = self.token_to_dict.get(token)
            if not options_to_stop_at:
                raise ValueError(f"Options.pop_until_token: specified non-existent options token={token}")

            count = 0
            while self.stack and (self.options != options_to_stop_at):
                count += 1
                self.pop()

            if self.options != options_to_stop_at:
                raise ValueError(f"Options.pop_until_token: couldn't find options with token={token}")

            if want_prints:
                print(f"{self.interpreter.cmdline_prefix} {self.interpreter.ip_spacer} Options.pop_until_token: token={token}, popped {count} times.")

        def unmap_all_child_options(self):
            """
            This unmaps all the *child* options.

            Note that we're only emptying the stack.
            self.options is the top of the stack, and we aren't
            blowing that away.  So when we empty self.stack,
            there's still one options dict left, which was at the
            bottom of the stack; this is the bottom options dict,
            where all the permanently-mapped options live.
            """
            count = len(self.stack)
            for _ in range(count):
                self.pop()

            if want_prints:
                print(f"{self.interpreter.cmdline_prefix} Options.unmap_all_child_options: popped {count} times.")

        def __getitem__(self, option):
            depth = 0
            options = self.options
            token = self.token
            i = reversed(self.stack)
            while True:
                t = options.get(option, None)
                if t is not None:
                    break
                try:
                    options, token = next(i)
                except StopIteration:
                    parent_options = self.interpreter.program.options.get(option)
                    if parent_options:
                        parent_options = parent_options.replace("|", "or")
                        message = f"{denormalize_option(option)} can't be used here, it must be used immediately after {parent_options}"
                    else:
                        message = f"unknown option {denormalize_option(option)}"
                    raise AppealUsageError(message) from None

            program, group_id = t
            total = program.total
            return program, group_id, total.minimum, total.maximum, token

        def __setitem__(self, option, value):
            self.options[option] = value

    def __call__(self):
        (
        option_space_oparg,

        short_option_equals_oparg,
        short_option_concatenated_oparg,
        ) = self.appeal.root.option_parsing_semantics

        argi = self.argi

        id_to_group = {}

        command_converter = None

        force_positional = self.appeal.root.force_positional

        if want_prints:
            self.ip_spacer = '    '

        if want_prints:
            charm_separator_line = f"{self.opcodes_prefix}{'-' * 58}"
            print(charm_separator_line)
            print(f"{self.opcodes_prefix}")
            print(f'{self.opcodes_prefix} CharmInterpreter start')
            print(f"{self.opcodes_prefix}")
            all_options = list(denormalize_option(o) for o in self.program.options)
            all_options.sort(key=lambda s: s.lstrip('-'))
            all_options = " ".join(all_options)
            print(f"{self.opcodes_prefix} all options supported: {all_options}")

        waiting_op = None
        prev_op = None

        ip_zero = f"[{self.repr_ip(0)}]"
        self.ip_spacer = " " * len(ip_zero)
        self.register_spacer = " " * len(ip_zero)

        sentinel = object()

        def print_changed_registers(**kwargs):
            """
            Call this *after* changing registers.
            Pass in the *old value* of every registers
            you changed, as a keyword argument named
            for the register.

            If you don't change any registers,
            you should still call this, for
            visual consistency.

            (Why *changed* instead of *changing*?
            That made it easier to copy with the
            two-phase loop and printing consume_argument.)
            """
            for r in ('converter', 'o', 'group', 'groups'):
                fields = [r.rjust(9), "|   "] # len(coverter) == 9

                value = getattr(self, r)
                old = kwargs.get(r, sentinel)
                changed = (old != sentinel) and (value != old)
                if changed:
                    if r == 'groups':
                        s = repr([group.id for group in old ])
                    elif r == 'group':
                        s = old.summary() if old else repr(old)
                    else:
                        s = self.repr_converter(old)
                    fields.append(s)
                    fields.append("->")

                if r == 'groups':
                    s = repr([group.id for group in value ])
                elif r == 'group':
                    s = value.summary() if value else repr(value)
                else:
                    s = self.repr_converter(value)
                fields.append(s)

                result = " ".join(fields)
                if len(result) < 50:
                    print(f"{self.opcodes_prefix} {self.register_spacer} {result}")
                else:
                    # split it across two lines
                    print(f"{self.opcodes_prefix} {self.register_spacer} {r:>9} |    {fields[2]}")
                    if changed:
                        print(f"{self.opcodes_prefix} {self.register_spacer}           | -> {fields[-1]}")


        while self.running() or argi:
            if want_prints:
                print(f'{self.opcodes_prefix}')
                print(charm_separator_line)
                print(f"{self.opcodes_prefix} command-line: {shlex_join(list(reversed(argi.stack)))}")

            # The main interpreter loop.
            #
            # This loop has two "parts".
            #
            # In the first part, we iterate over bytecodes until either
            #    * we finish the program, or
            #    * we must consume a command-line argument
            #      (we encounter a "consume_argument" bytecode).
            # If we finish the program, obviously, we're done.
            # If we must consume a command-line argument, we proceed
            # to the second "part".
            #
            # In the second part, we consume a command-line argument.
            # If it's an option, we process the option, and loop.
            # If it's not an option, we consume it as normal and continue.

            # First "part" of the loop: iterate over bytecodes.
            if want_prints:
                print(f"{self.opcodes_prefix}")
                print(f"{self.opcodes_prefix} loop part one: execute program {self.program}")
                program_printed = self.program


            for ip, op in self:
                prev_op = waiting_op
                waiting_op = op

                if want_prints:
                    print(f"{self.opcodes_prefix} ")
                    if program_printed != self.program:
                        print(f"{self.opcodes_prefix} now running program {self.program}")
                        program_printed = self.program
                        print(f"{self.opcodes_prefix} ")

                    prefix = f"[{self.repr_ip(ip)}]"

                if op.op == opcode.create_converter:
                    # r = None if op.parameter.kind == KEYWORD_ONLY else command_converter
                    cls = self.appeal.map_to_converter(op.parameter)
                    converter = cls(op.parameter, self.appeal, is_command=op.is_command)
                    old_o = self.o
                    self.converters[op.key] = self.o = converter
                    if op.is_command and (not command_converter):
                        command_converter = converter
                        self.command_converter_key = op.key

                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} create_converter | cls {cls.__name__} | parameter {op.parameter.name} | key {op.key}")
                        print_changed_registers(o=old_o)
                        print(f"{self.opcodes_prefix} ")
                        print(f"{self.opcodes_prefix} {self.register_spacer} converters[{op.key}] = {converter}")
                    continue

                if op.op == opcode.load_converter:
                    converter = self.converters.get(op.key, None)
                    old_converter = self.converter
                    self.converter = converter
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} load_converter | key {op.key}")
                        print_changed_registers(converter=old_converter)
                    continue

                if op.op == opcode.load_o:
                    o = self.converters.get(op.key, None)
                    old_o = self.o
                    self.o = o
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} load_o | key {op.key}")
                        print_changed_registers(o=old_o)
                    continue

                if op.op == opcode.map_option:
                    self.options[op.option] = (op.program, op.group)
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} map_option | '{denormalize_option(op.option)}' -> {op.program} | token {self.options.token}")
                        print_changed_registers()
                    continue

                if op.op == opcode.append_to_args:
                    o = self.o
                    converter = self.converter
                    # either queue or append o as indicated
                    (converter.queue_converter if op.discretionary else converter.append_converter)(o)

                    if want_prints:
                        discretionary = "yes" if op.discretionary else "no"
                        print(f"{self.opcodes_prefix} {prefix} append_to_args | parameter {op.parameter} | discretionary? {discretionary}")
                        print_changed_registers()
                    continue

                if op.op == opcode.add_to_kwargs:
                    name = op.name
                    converter = self.converter
                    o = self.o

                    existing = converter.kwargs_converters.get(name)
                    if existing:
                        if not ((existing == o) and isinstance(existing, MultiOption)):
                            raise AppealUsageError(f"{program.name} specified more than once.")
                        # we're setting the kwarg to the value it's already set to,
                        # and it's a multioption.  it's fine, we just ignore it.
                        continue

                    converter.unqueue()
                    converter.kwargs_converters[name] = o
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} add_to_kwargs | name {op.name}")
                        print_changed_registers()
                    continue

                if op.op == opcode.consume_argument:
                    if not argi:
                        if want_prints:
                            print(f"{self.opcodes_prefix} {prefix} consume_argument | no more arguments, aborting program.")
                        self.abort()
                    # proceed to second part of interpreter loop
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} consume_argument | switching from loop part 1 to loop part 2")
                    break

                if op.op == opcode.set_group:
                    if want_prints:
                        old_group = self.group
                        old_groups = self.groups.copy()
                    self.group = group = op.group.copy()
                    self.groups.append(group)
                    id_to_group[group.id] = group
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} set_group")
                        print_changed_registers(group=old_group, groups=old_groups)
                    continue

                if op.op == opcode.flush_multioption:
                    assert isinstance(self.o, MultiOption), f"expected o to contain instance of MultiOption but o={self.o}"
                    self.o.flush()
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} flush_multioption")
                        print_changed_registers()
                    continue

                if op.op == opcode.jump:
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} jump | op.address {op.address}")
                        print_changed_registers()
                    self.ip.jump(op.address)
                    continue

                if op.op == opcode.branch_on_o:
                    if want_prints:
                        branch = "yes" if self.o else "no"
                        print(f"{self.opcodes_prefix} {prefix} branch_on_o | o? {branch} | address {op.address}")
                        print_changed_registers()
                    if self.o:
                        self.ip.jump(op.address)
                    continue

                if op.op == opcode.comment:
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} # {op.comment!r}")
                    continue

                if op.op == opcode.end:
                    if want_prints:
                        print(f"{self.opcodes_prefix} {prefix} end | id {op.id} | name {op.name!r}")
                        print_changed_registers()
                    continue

                raise AppealConfigurationError(f"unhandled opcode | op {op}")

            else:
                # we finished the program
                if want_prints:
                    print(f"{self.opcodes_prefix} ")
                    print(f"{self.opcodes_prefix} finished.")
                    print(f"{self.opcodes_prefix} ")
                op = None


            # Second "part" of the loop: consume a command-line argument.
            #
            # We've either paused or finished the program.
            #   If we've paused, it's because the program wants us
            #     to consume an argument.  In that case op
            #     will be a 'consume_argument' op.
            #   If we've finished the program, op will be None.
            assert (op == None) or (op.op == opcode.consume_argument), f"op={op}, expected either None or consume_argument"

            # Technically we loop over argi, but in practice
            # we usually only consume one argument at a time.
            #
            # for a in argi:
            #    * if a is an option (or options),
            #      push that program (programs) and resume
            #      the charm interpreter.
            #    * if a is the special value '--', remember
            #      that all subsequent command-line arguments
            #      can no longer be options, and continue to
            #      the next a in argi.  (this is the only case
            #      in which we'll consume more than one argument
            #      in this loop.)
            #    * else a is a positional argument.
            #      * if op is consume_argument, consume it and
            #        resume the charm interpreter.
            #      * else, hmm, we have a positional argument
            #        we don't know what to do with.  the program
            #        is done, and we don't have a consume_argument
            #        to give it to.  so push it back onto argi
            #        and exit.  (hopefully the argument is the
            #        name of a command/subcomand.)

            print_loop_start = True

            for a in argi:
                if want_prints:
                    if print_loop_start:
                        print(f"{self.cmdline_prefix} ")
                        print(f"{self.cmdline_prefix} loop part 2: consume argument(s): op={op} cmdline: {shlex_join(list(reversed(argi.stack)))}")
                        print(f"{self.cmdline_prefix} ")
                        print_loop_start = False
                    print(f"{self.cmdline_prefix} argument: {a!r}  remaining: {shlex_join(list(reversed(argi.stack)))}")
                    print(f"{self.cmdline_prefix}")

                # Is this command-line argument a "positional argument", or an "option"?
                # In this context, a "positional argument" can be either a conventional
                # positional argument on the command-line, or an "oparg".

                # If force_positional is true, we encountered "--" on the command-line.
                # This forces Appeal to ignore dashes and process all subsequent
                # arguments as positional arguments.

                # If the argument doesn't start with a dash,
                # it can't be an option, therefore it must be a positional argument.
                doesnt_start_with_a_dash = not a.startswith("-")

                # If the argument is a single dash, it isn't an option,
                # it's a positional argument.  This is an old UNIX idiom;
                # if you were expecting a filename and you got "-", you should
                # use the appropriate stdio file (stdin/stdout) there.
                is_a_single_dash = a == "-"

                # If we're consuming opargs, we ignore leading dashes,
                # and all arguments are forced to be opargs
                # until we've consume all the opargs we need.
                is_oparg = op and (op.op == opcode.consume_argument) and op.is_oparg

                is_positional_argument = (
                    force_positional
                    or doesnt_start_with_a_dash
                    or is_a_single_dash
                    or is_oparg
                    )

                if is_positional_argument:
                    if not op:
                        if want_prints:
                            print(f"{self.cmdline_prefix}  positional argument we don't want.")
                            print(f"{self.cmdline_prefix}  maybe somebody else will consume it.")
                            print(f"{self.cmdline_prefix}  exit.")
                        argi.push(a)
                        return self.converters[self.command_converter_key]

                    # set register "o" to our string and return to running bytecodes.
                    if want_prints:
                        old_o = self.o
                        old_group = self.group.copy()
                    self.o = a
                    if self.group:
                        self.group.count += 1
                        self.group.laden = True

                    if not is_oparg:
                        self.options.unmap_all_child_options()

                    if want_prints:
                        print(f"{self.cmdline_prefix}")
                        print(f"{self.opcodes_prefix} {prefix} consume_argument")
                        print_changed_registers(o=old_o, group=old_group)

                    break

                if not option_space_oparg:
                    raise AppealConfigurationError("oops, currently the only supported value of option_space_oparg is True")

                if a == "--":
                    # we shouldn't be able to reach this twice.
                    # if the user specifies -- twice on the command-line,
                    # the first time turns of option processing, which means
                    # it should be impossible to get here.
                    assert not force_positional
                    force_positional = self.appeal.root.force_positional = True
                    if want_prints:
                        print(f"{self.cmdline_prefix}  '--', force_positional=True")
                    continue

                # it's an option!
                double_dash = a.startswith("--")
                pushed_remainder = False

                # split_value is the value we "split" from the option string.
                # In these example, split_value is 'X':
                #     --option=X
                #     -o=X
                # and, if o takes exactly one optional argument,
                # and short_option_concatenated_oparg is true:
                #     -oX
                # If none of these syntaxes (syntices?) is used,
                # split_value is None.
                #
                # Literally we handle it by splitting it off,
                # then pushing it *back* onto argi, so the option
                # program can consume it.  Thus we actually transform
                # all the above examples into
                #     -o X
                #
                # Note: split_value can be an empty string!
                #     -f=
                # So, simply checking truthiness is insufficient.
                # You *must* check "if split_value is None".
                split_value = None

                try_to_split_value = double_dash or short_option_equals_oparg
                if try_to_split_value:
                    a, equals, _split_value = a.partition("=")
                    if equals:
                        split_value = _split_value
                else:
                    split_value = None

                if double_dash:
                    option = a
                    program, group_id, minimum_arguments, maximum_arguments, token = self.options[option]
                else:
                    ## In Appeal,
                    ##      % python3 myscript foo -abcde
                    ## must be EXACTLY EQUIVALENT TO
                    ##      % python3 myscript foo -a -b -c -d -e
                    ##
                    ## The best way to handle this is to transform the former
                    ## into the latter.  Every time we encounter a single-dash
                    ## option, consume just the first letter, and if the rest
                    ## is more options, reconstruct the remaining short options
                    ## and push it onto the argi pushback iterator.  For example,
                    ## if -a is an option that accepts no opargs, we transform
                    ##      % python3 myscript foo -abcde
                    ## into
                    ##      % python3 myscript foo -a -bcde
                    ## and then handle "-a".
                    ##
                    ## What about options that take opargs?  Except for
                    ## the special case of short_option_concatenated_oparg,
                    ## options that take opargs have to be the last short option.

                    # strip off this short option by itself:
                    option = a[1]
                    program, group_id, minimum_arguments, maximum_arguments, token = self.options[option]

                    # handle the remainder.
                    remainder = a[2:]
                    if remainder:
                        if maximum_arguments == 0:
                            # more short options.  push them back onto argi.
                            pushed_remainder = True
                            remainder = "-" + remainder
                            argi.push(remainder)
                            if want_prints:
                                print(f"{self.cmdline_prefix} isolating '-{option}', pushing remainder '{remainder}' back onto argi")
                        elif maximum_arguments >= 2:
                            if minimum_arguments == maximum_arguments:
                                number_of_arguments = maximum_arguments
                            else:
                                number_of_arguments = f"{minimum_arguments} to {maximum_arguments}"
                            raise AppealUsageError(f"-{option}{remainder} isn't allowed, -{option} takes {number_of_arguments} arguments, it must be last")
                        # in the remaining cases, we know maximum_arguments is 1
                        elif short_option_concatenated_oparg and (minimum_arguments == 0):
                            # Support short_option_concatenated_oparg.
                            #
                            # If a short option takes *exactly* one *optional*
                            # oparg, you can smash the option and the oparg together.
                            # For example, if short option "-f" takes exactly one
                            # optional oparg, and you want to supplythe oparg "guava",
                            # you can do
                            #    -f=guava
                            #    -f guava
                            # and in ONLY THIS CASE
                            #    -fguava
                            #
                            # Technically POSIX doesn't allow us to support this:
                            #    -f guava
                            #
                            # On the other hand, there's a *long list* of things
                            # POSIX doesn't allow us to support:
                            #
                            #    * short options with '=' (split_value, e.g. '-f=guava')
                            #    * long options
                            #    * subcommands
                            #    * options that take multiple opargs
                            #
                            # So, clearly, exact POSIX compliance is not of
                            # paramount importance to Appeal.
                            #
                            # Get with the times, you musty old fogeys!

                            if split_value is not None:
                                raise AppealUsageError(f"-{option}{remainder}={split_value} isn't allowed, -{option} must be last because it takes an argument")
                            split_value = remainder
                        else:
                            assert minimum_arguments == maximum_arguments == 1
                            raise AppealUsageError(f"-{option}{remainder} isn't allowed, -{option} must be last because it takes an argument")

                laden_group = id_to_group[group_id]

                denormalized_option = denormalize_option(option)
                if want_prints:
                    print(f"{self.cmdline_prefix} option {denormalized_option}")
                    print(f"{self.cmdline_prefix} {self.ip_spacer} program={program}")
                    print(f"{self.cmdline_prefix} {self.ip_spacer} group={laden_group.summary()}")
                    print(f"{self.cmdline_prefix}")

                # mark argument group as having had stuff done in it.
                laden_group.laden = True

                # we have an option to run.
                # the existing consume_argument op will have to wait.
                if op:
                    assert op.op == opcode.consume_argument
                    self.rewind_one_instruction()
                    op = None

                # throw away child options mapped below our option's sibling.
                self.options.pop_until_token(token)

                # and push a fresh options dict.
                self.options.push()

                if split_value is not None:
                    if maximum_arguments != 1:
                        if maximum_arguments == 0:
                            raise AppealUsageError(f"{denormalized_option}={split_value} isn't allowed, because {denormalize_option} doesn't take an argument")
                        if maximum_arguments >= 2:
                            raise AppealUsageError(f"{denormalized_option}={split_value} isn't allowed, because {denormalize_option} takes multiple arguments")
                    argi.push(split_value)
                    if want_prints:
                        print(f"{self.cmdline_prefix} {self.ip_spacer} pushing split value {split_value!r} back onto argi")

                if want_prints:
                    print(f"{self.cmdline_prefix}")
                    print(f"{self.cmdline_prefix} call program={program}")

                # self.push_context()
                self.call(program)
                break

        self.unwind()

        satisfied = True
        ag = self.group
        assert ag

        if not ag.satisfied():
            if ag.minimum == ag.maximum:
                plural = "" if ag.minimum == 1 else "s"
                middle = f"{ag.minimum} argument{plural}"
            else:
                middle = f"at least {ag.minimum} arguments but no more than {ag.maximum} arguments"
            program = self.program
            message = f"{program.name} requires {middle} in this argument group."
            raise AppealUsageError(message)

        if want_prints:
            print(f"{self.opcodes_prefix}")
            print(f"{self.opcodes_prefix} ending parse.")
            finished_state = "did not finish" if self else "finished"
            print(f"{self.opcodes_prefix}      program {finished_state}.")
            if argi:
                print(f"{self.opcodes_prefix}      remaining cmdline: {list(reversed(argi.stack))}")
            else:
                print(f"{self.opcodes_prefix}      cmdline was completely consumed.")

        if want_prints:
            print(charm_separator_line)
            print()

        return self.converters[self.command_converter_key]



class Converter:
    """
    A Converter object calls a Python function, filling
    in its parameters using command-line arguments.
    It introspects the function passed in, creating
    a tree of sub-Converter objects underneath it.

    A Converter
    """
    def __init__(self, parameter, appeal, *, is_command=False):
        self.parameter = parameter
        self.appeal = appeal
        self.is_command = is_command

        callable = dereference_annotated(parameter.annotation)
        default = parameter.default

        # self.fn = callable
        self.callable = callable

        if not hasattr(self, '__signature__'):
            self.__signature__ = self.get_signature(parameter)

        # self.root = root or self
        self.default = default
        self.name = parameter.name

        # output of analyze().  input of parse() and usage().
        # self.program = None

        self.docstring = self.callable.__doc__

        self.usage_str = None
        self.summary_str = None
        self.doc_str = None

        self.reset()

    def __repr__(self):
        return f"<{self.__class__.__name__} callable={self.callable.__name__}>"

    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        return inspect.signature(dereference_annotated(parameter.annotation), follow_wrapped=False)

    def reset(self):
        """
        Called to reset the mutable state of a converter.

        Note that MultiOption is a subclass of Converter,
        and calls reset() each time it's invoked.
        """

        # names of parameters that we filled with strings
        # from the command-line.  if this converter throws
        # a ValueError or TypeError when executed, and it's
        # an interior node in the annotations tree, we'll know
        # exactly which command-line argument failed to convert
        # and can display more pertinent usage information.
        self.string_parameters = []

        # queued and args_queue are used to manage converters
        # that might not actually be needed.  some converters
        # are created proactively but are never actually used.
        # Appeal used to queue them, then remove them; queueing
        # them and not flushing them is easier.
        #
        # queued is a flag.  if queued is not None, it points to our
        #     parent converter, and it represents a request to notify
        #     the parent when you get a cmdline argument added to
        #     you--either positional or keyword-only.
        # args_queue is a list of child converters that are waiting to be
        #     flushed into our args_converters.
        #
        # Note that self.queued may be set to our parent even when we
        # *aren't* in our parent's args_queue.  Our converter might be
        # a required argument to our parent, but our parent is optional and
        # has been queued.  (Or our parent's parent, etc.  It's a tree.)
        self.queued = None
        self.args_queue = collections.deque()

        # collections of converters we'll use to compute *args and **kwargs.
        # contains either raw strings or Converter objects which we'll call.
        #
        # these are the output of parse(), specifically the CharmInterpreter,
        # and the input of convert().
        self.args_converters = []
        self.kwargs_converters = {}

        # these are the output of convert(), and the input for execute().
        self.args = []
        self.kwargs = {}


    ## "discretionary" converters, and queueing and unqueueing
    ##
    ## If a group is "optional", that means there's at least
    ## one parameter with a default value.  If that parameter
    ## has a converter, we don't know in advance whether or not
    ## we're actually gonna call it.  We'll only call it if we
    ## fill one of its parameters with a positional argument,
    ## and we can't really predict in advance whether or not
    ## that's gonna happen.
    ##
    ## For example:
    ##   * the first actual positional argument is optional
    ##   * it's nested three levels deep in the annotation tree
    ##   * we have command-line arguments waiting in argi but
    ##     the next argument is an option, and we don't know
    ##     how many opargs it wants to consume until we run it
    ##
    ## Or:
    ##   * all the parameters to the converter are optional
    ##   * the converter maps an option
    ##   * sometime in the deep future the user invokes
    ##     that option on the command-line
    ##
    ## So... when should we create the converter?  The best
    ## possible time would be "just-in-time", at the moment
    ## we know we need it and no sooner.  But, the way Appeal
    ## works internally, it makes things a lot smoother to
    ## just pre-allocate a converter, then eventually throw it
    ## away if we don't need it.
    ##
    ## Observe that:
    ##   * First, we're only talking about optional groups.
    ##     So this only applies to converters that get appended
    ##     to args.
    ##       * Converters that handle options get set in kwargs,
    ##         so there's no mystery about whether or not they're
    ##         getting used.  Appeal already creates *those*
    ##         only on demand.
    ##   * Second, optional groups only become required once we
    ##     consume an argument in that group, or invoke one of
    ##     the options mapped in that group.
    ##
    ## Here's what Appeal does.  In a nutshell, converters mapped
    ## in optional groups get created early, but they don't get
    ## appended to their parent's args_converters right away.
    ## These converters that we might not need are called
    ## "discretionary" converters.  Converters that aren't
    ## discretionary are "mandatory" converters.  A "discretionary"
    ## converter becomes mandatory at the moment it (or a
    ## converter below it in the annotations tree) gets a string
    ## argument from the command-line appended to it, or the user
    ## invokes an option that maps to one of its (or one of
    ## its children's) options.
    ##
    ## When the CharmInterpreter creates a mandatory converter
    ## for a positional argument, that converter is immediately
    ## queued in its parent converter's args_converters list.
    ## But discretionary converters get "queued", which means
    ## it goes to a different place: the parent converter's other
    ## list, args_queue.
    ##
    ## At the moment that a discretionary converter becomes
    ## mandatory--a string from the command-line gets appended
    ## to that converter, or one of the options it maps gets
    ## invoked--we "unqueue" that queued converter, moving it
    ## from its parent's args_queue list to its parent's
    ## args_converters list.
    ##
    ## Two complexities arise from this:
    ##     * If there's a converter B queued in front of
    ##       converter A in same parent, and B becomes mandatory,
    ##       A becomes mandatory too.  And you need to flush
    ##       it first, so that the parent gets its positional
    ##       arguments in the right order.  So, when we want to
    ##       flush a particular converter, we flush all the entries
    ##       in the queue before it too.
    ##     * An optional argument group can have an entire tree
    ##       of converters underneath it, themselves variously
    ##       optional or required.  So, when a converter has been
    ##       queued, and it gets a child converter appended to it
    ##       (or queued to it) it also tells its children "Tell me
    ##       when I need to unqueue".  If one of these children
    ##       gets a positional argument that is a string, or gets
    ##       one of its options invoked, it'll tell its *parent*
    ##       to unqueue.
    ##
    ## Internally, we only use one field in the child converter
    ## for all this: "queued".
    ##     * If "queued" is None, the converter is mandatory,
    ##       and all its parents are mandatory.
    ##     * If "queued" is not None, either the converter
    ##       is optional, or one of its parents is optional,
    ##       and "queued" points to its parent.
    ##
    ## -----
    ##
    ## One final note.  When I was testing this code against the
    ## test suite, I was quite surprised to see the same converter
    ## queued and flushed multiple times.  I investigated, and
    ## found it wasn't actually the *same* converter, but it had
    ## the same name and was going in the same place.  It was a
    ## converter for *args, and the test case looped five times.
    ## So it actually was five identical but different converters,
    ## going so far as to use the same converter key.
    ## (It might be nice to be able to tell them apart in the log.)

    def append_converter(self, o):
        """
        Append o directly to our args_converters list.

        If o is a string, also unqueue ourselves
        (and recursively all our parents too).

        If o is not a string, and we or one of our parents
        is discretionary, ask o to notify us if it gets
        a string positional argument appended to it,
        or if one of its options is invoked.
        """
        # print(f">> {self=} appended to {parent=}\n")
        self.args_converters.append(o)

        if isinstance(o, str):
            self.unqueue()
        else:
            assert not o.queued
            # ask
            if self.queued:
                o.queued = self

    def queue_converter(self, o):
        """
        Append o to our args_queue list.
        o must be a discretionary Converter object.
        """
        # print(f">> {self=} queued for {parent=}\n")
        assert not o.queued
        o.queued = self
        self.args_queue.append(o)

    def unqueue(self, converter=None):
        """
        Unqueue ourselves from our parent.

        Also tells our parent to unqueue itself,
        recursively back up to the root of this
        discretionary converter subtree.

        Also, if converter is not None,
        and converter is in our args_queue,
        converter is a discretionary converter
        in our args_queue, and we flush the
        args_queue until converter is unqueued
        (aka flushed).  If converter isn't in
        args_queue, args_queue doesn't change.
        """
        if self.queued:
            self.queued.unqueue(self)
            self.queued = None

        if not converter:
            return

        try:
            # if converter isn't in args_queue, this will throw ValueError
            self.args_queue.index(converter)

            while True:
                child = self.args_queue.popleft()
                self.args_converters.append(child)
                child.queued = None
                if child == converter:
                    break
        except ValueError:
            pass

    def convert(self, processor):
        # print(f"self={self} self.args_converters={self.args_converters} self.kwargs_converters={self.kwargs_converters}")
        for iterable in (self.args_converters, self.kwargs_converters.values()):
            for converter in iterable:
                if converter and not isinstance(converter, str):
                    # print(f"self={self}.convert, converter={converter}")
                    converter.convert(processor)

        try:
            for converter in self.args_converters:
                if converter and not isinstance(converter, str):
                    converter = converter.execute(processor)
                self.args.append(converter)
            for name, converter in self.kwargs_converters.items():
                if converter and not isinstance(converter, str):
                    converter = converter.execute(processor)
                self.kwargs[name] = converter
        except ValueError as e:
            # we can examine "converter", the exception must have
            # happened in an execute call.
            raise AppealUsageError(f"invalid value something something {converter=}, {dir(converter)=} {converter.args=}")

    def execute(self, processor):
        executor = processor.execute_preparers(self.callable)
        return executor(*self.args, **self.kwargs)


class InferredConverter(Converter):
    def __init__(self, parameter, appeal, *, is_command=False):
        if not parameter.default:
            raise AppealConfigurationError(f"empty {type(parameter.default)} used as default, so we can't infer types")
        p2 = inspect.Parameter(parameter.name, kind=parameter.kind, annotation=type(parameter.default), default=parameter.default)
        super().__init__(p2, appeal, is_command=is_command)

    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        return inspect.signature(type(parameter.default), follow_wrapped=False)

class InferredSequenceConverter(InferredConverter):
    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        parameters = []
        if not parameter.default:
            width = 0
        else:
            width = math.floor(math.log10(len(parameter.default))) + 1
        separator = "_" if parameter.name[-1].isdigit() else ""
        for i, value in enumerate(parameter.default):
            name = f"{parameter.name}{separator}{i:0{width}}"
            p = inspect.Parameter(name, inspect.Parameter.POSITIONAL_ONLY, annotation=type(value))
            parameters.append(p)
        return inspect.Signature(parameters)

    def execute(self, processor):
        return self.callable(self.args)



class SimpleTypeConverter(Converter):
    def __init__(self, parameter, appeal, *, is_command=False):
        self.appeal = appeal
        self.default = parameter.default
        self.is_command = is_command

        self.name = parameter.name

        self.string_parameters = []

        self.value = None

        self.queued = None
        self.args_queue = collections.deque()
        self.args_converters = []
        # don't set kwargs_converters, let it esplody!

        self.options_values = {}
        self.help_options = {}
        self.help_arguments = {}

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.callable} args_converters={self.args_converters} value={self.value}>"

    def convert(self, processor):
        if not self.args_converters:
            # explicitly allow "make -j"
            if self.default is not empty:
                return self.default
            raise AppealUsageError(f"no argument supplied for {self}, we should have raised an error earlier huh.")
        try:
            self.value = self.callable(self.args_converters[0])
        except ValueError as e:
            raise AppealUsageError(f"invalid value {self.args_converters[0]} for {self.name}, must be {self.callable.__name__}")


    def execute(self, processor):
        return self.value


simple_type_signatures = {}

def parse_bool(bool) -> bool: pass
class SimpleTypeConverterBool(SimpleTypeConverter):
    __signature__ = inspect.signature(parse_bool)
    callable = bool
simple_type_signatures[bool] = SimpleTypeConverterBool

def parse_complex(complex) -> complex: pass
class SimpleTypeConverterComplex(SimpleTypeConverter):
    __signature__ = inspect.signature(parse_complex)
    callable = complex
simple_type_signatures[complex] = SimpleTypeConverterComplex

def parse_float(float) -> float: pass
class SimpleTypeConverterFloat(SimpleTypeConverter):
    __signature__ = inspect.signature(parse_float)
    callable = float
simple_type_signatures[float] = SimpleTypeConverterFloat

def parse_int(int) -> int: pass
class SimpleTypeConverterInt(SimpleTypeConverter):
    __signature__ = inspect.signature(parse_int)
    callable = int
simple_type_signatures[int] = SimpleTypeConverterInt

def parse_str(str) -> str: pass
class SimpleTypeConverterStr(SimpleTypeConverter):
    __signature__ = inspect.signature(parse_str)
    callable = str
simple_type_signatures[str] = SimpleTypeConverterStr


class BaseOption(Converter):
    pass

class InferredOption(BaseOption):
    def __init__(self, parameter, appeal, *, is_command=False):
        if not parameter.default:
            raise AppealConfigurationError(f"empty {type(parameter.default)} used as default, so we can't infer types")
        p2 = inspect.Parameter(parameter.name, kind=parameter.kind, annotation=type(parameter.default), default=parameter.default)
        super().__init__(p2, appeal, is_command=is_command)

    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        return inspect.signature(type(parameter.default), follow_wrapped=False)

class InferredSequenceOption(InferredOption):
    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        parameters = []
        if not parameter.default:
            width = 0
        else:
            width = math.floor(math.log10(len(parameter.default))) + 1
        separator = "_" if parameter.name[-1].isdigit() else ""
        for i, value in enumerate(parameter.default):
            name = f"{parameter.name}{separator}{i:0{width}}"
            p = inspect.Parameter(name, inspect.Parameter.POSITIONAL_ONLY, annotation=type(value))
            parameters.append(p)
        return inspect.Signature(parameters)

    def execute(self, processor):
        return self.callable(self.args)


def strip_first_argument_from_signature(signature):
    # suppresses the first argument from the signature,
    # regardless of its name.
    # (the name "self" is traditional, but it's mostly not enforced
    # by the language.  though I think no-argument super() might depend on it.)
    parameters = collections.OrderedDict(signature.parameters)
    if not parameters:
        raise AppealConfigurationError(f"strip_first_argument_from_signature: was passed zero-argument signature {signature}")
    for name, p in parameters.items():
        break
    del parameters[name]
    if 'return' in parameters:
        return_annotation = parameters['return']
        del parameters['return']
    else:
        return_annotation = empty
    return inspect.Signature(parameters.values(), return_annotation=return_annotation)


def strip_self_from_signature(signature):
    # suppresses self from the signature.
    parameters = collections.OrderedDict(signature.parameters)
    if not parameters:
        return signature
    # the self parameter must be first
    for name, p in parameters.items():
        break
    if name != "self":
        return signature
    del parameters['self']
    if 'return' in parameters:
        return_annotation = parameters['return']
        del parameters['return']
    else:
        return_annotation = empty
    return inspect.Signature(parameters.values(), return_annotation=return_annotation)


class Option(BaseOption):
    def __init__(self, parameter, appeal, *, is_command=False):
        # the callable passed in is ignored
        p2 = inspect.Parameter(parameter.name, kind=parameter.kind, annotation=self.option, default=parameter.default)
        super().__init__(p2, appeal, is_command=is_command)
        self.init(parameter.default)

    def __repr__(self):
        return f"<{self.__class__.__name__}>"

    @classmethod
    def get_signature(cls, parameter):
        if hasattr(cls, "__signature__"):
            return cls.__signature__
        # we need the signature of cls.option
        # but *without self*
        signature = inspect.signature(cls.option, follow_wrapped=False)
        signature = strip_first_argument_from_signature(signature)
        return signature

    def execute(self, processor):
        self.option(*self.args, **self.kwargs)
        return self.render()

    # Your subclass of SingleOption or MultiOption is required
    # to define its own option() and render() methods.
    # init() is optional.

    # init() is called at initialization time.
    # This is a convenience; you can also overload __init__
    # if you like.  But that means staying in sync with
    # the parameters to __init__ and still change sometimes.
    def init(self, default):
        pass

    # option() is called every time your option is specified
    # on the command-line.  For an Option, this will be exactly
    # one time.  For a MultiOption, this will be one or more times.
    # (Appeal will never construct your Option object unless
    # it's going to call your option method at least once.)
    #
    # option() can take parameters, and these are translated
    # to command-line positional parameters or options in the
    # same way converters are.
    #
    # Note:
    #   * If option() takes no parameters, your option will
    #     consume no opargs or options, like a boolean option.
    #     It'll still be called every time, your option is
    #     specified.
    #   * You may (and are encouraged to!) specify annotations for
    #     the parameters to option().
    #   * If your option method only has *optional* parameters,
    #     it's possible Appeal will call it with zero arguments.
    #     (This is how you implement "make -j" for example.)
    @abstractmethod
    def option(self):
        pass

    # render() is called exactly once, after option() has been
    # called for the last time.  it should return the "value"
    # for the option.
    @abstractmethod
    def render(self):
        pass


# the old name, now deprecated
SingleOption = Option


def parse_bool_option() -> bool: pass
class BooleanOptionConverter(Option):
    __signature__ = inspect.signature(parse_bool_option)

    def init(self, default):
        self.value = default

    def option(self):
        self.value = not self.value

    def render(self):
        return self.value

class MultiOption(Option):
    def __init__(self, parameter, appeal, *, is_command=False):
        self.multi_converters = []
        self.multi_args = []
        # the callable passed in is ignored
        p2 = inspect.Parameter(parameter.name, kind=parameter.kind, annotation=self.option, default=parameter.default)
        super().__init__(p2, appeal, is_command=is_command)

    def flush(self):
        self.multi_converters.append((self.args_converters, self.kwargs_converters))
        self.reset()

    def convert(self, processor):
        self.flush()
        for args, kwargs in self.multi_converters:
            self.args = []
            self.kwargs = {}
            self.args_converters = args
            self.kwargs_converters = kwargs
            super().convert(processor)
            self.multi_args.append((self.args, self.kwargs))

    def execute(self, processor):
        for args, kwargs in self.multi_args:
            # print(f"CALLING self.option={self.option} args={args} kwargs={kwargs}")
            self.option(*args, **kwargs)
        return self.render()


@must_be_instance
def counter(*, max=None, step=1):
    class Counter(MultiOption):
        def init(self, default):
            nonlocal max
            self.count = default
            if not step:
                raise AssertInternalError("counter(): step value cannot be 0")
            if max == None:
                max = math.inf if step > 0 else (-math.inf)
            self.max = max
            self.step = step

        def option(self):
            callable = min if self.step > 0 else max
            self.count = callable(self.count + step, self.max)

        def render(self):
            return self.count

    return Counter


class AccumulatorMeta(ABCMeta):
    def __getitem__(cls, t):
        if not isinstance(t, (tuple, list)):
            return cls.__getitem_single__(t)
        return cls.__getitem_iterable__(t)


    def __getitem_single__(cls, t):
        class accumulator(cls):
            __name__ = f'{cls.__name__}[{t.__name__}]'

            def option(self, arg:t):
                self.values.append(arg)
        return accumulator

    def __getitem_iterable__(cls, t):
        iterable_type = type(t)
        t_names = "_".join(ti.__name__ for ti in t)

        class accumulator(cls):
            __name__ = f'{cls.__name__}[{t_names}]'

            def option(self, *args):
                if type(args) != iterable_type:
                    args = iterable_type(args)
                self.values.append(args)

        parameters = []
        padding = math.ceil(math.log10(len(t)))
        for i, value in enumerate(t):
            p = inspect.Parameter(
                name = f'arg{i:0{padding}}',
                default = inspect.Parameter.empty,
                annotation = value,
                kind = inspect.Parameter.POSITIONAL_ONLY,
                )
            parameters.append(p)

        signature = inspect.signature(accumulator.option)
        updated_signature = signature.replace(
            parameters=parameters,
            return_annotation=inspect.Signature.empty,
            )

        accumulator.__signature__ = updated_signature

        return accumulator

    def __repr__(cls):
        return f'<{cls.__name__}>'


class accumulator(MultiOption, metaclass=AccumulatorMeta):
    def init(self, default):
        self.values = []
        if default is not empty:
            self.values.extend(default)

    def option(self, s:str):
        self.values.append(s)

    def render(self):
        return self.values


class MappingMeta(ABCMeta):
    def __getitem__(cls, t):
        if not ((isinstance(t, (tuple, list))) and (len(t) >= 2)):
            raise AppealConfigurationError("MappingMeta[] must have at least two types")
        if len(t) == 2:
            return cls.__getitem_key_single__(t[0], t[1])
        return cls.__getitem_key_iterable__(t[0], t[1:])

    def __getitem_key_single__(cls, k, v):
        class accumulator(cls):
            __name__ = f'{cls.__name__}[{k.__name__}_{v.__name__}]'

            def option(self, key:k, value:v):
                if key in self.dict:
                    raise AppealUsageError("defined {key} more than once")
                self.dict[key] = value
        return accumulator

    def __getitem_key_iterable__(cls, key, values):
        iterable_type = type(values)
        values_names = "_".join(ti.__name__ for ti in values)

        class accumulator(cls):
            __name__ = f'{cls.__name__}[{key.__name__}_{values_names}]'

            def option(self, key, *values):
                if key in self.dict:
                    raise AppealUsageError("defined {key} more than once")
                if type(values) != iterable_type:
                    values = iterable_type(values)
                self.dict[key] = values

        parameters = [
            inspect.Parameter(
                name = 'key',
                default = inspect.Parameter.empty,
                annotation = key,
                kind = inspect.Parameter.POSITIONAL_ONLY,
                )]

        padding = math.ceil(math.log10(len(values)))
        for i, value in enumerate(values):
            p = inspect.Parameter(
                name = f'value{i:0{padding}}',
                default = inspect.Parameter.empty,
                annotation = value,
                kind = inspect.Parameter.POSITIONAL_ONLY,
                )
            parameters.append(p)

        signature = inspect.signature(accumulator.option)
        updated_signature = signature.replace(
            parameters=parameters,
            return_annotation=inspect.Signature.empty,
            )

        accumulator.__signature__ = updated_signature

        return accumulator


class mapping(MultiOption, metaclass=MappingMeta):
    def init(self, default):
        self.dict = {}
        if default is not empty:
            self.dict.update(dict(default))

    def option(self, key:str, value:str):
        if key in self.dict:
            raise AppealUsageError("defined {key} more than once")
        self.dict[key] = value

    def render(self):
        return self.dict


@must_be_instance
def split(*separators, strip=False):
    """
    Creates a converter function that splits a string
    based on one or more separator strings.

    If you don't supply any separators, splits on
    any whitespace.

    If strip is True, also strips the separators
    from the beginning and end of the string.
    """
    if not all((s and isinstance(s, str)) for s in separators):
        raise AppealConfigurationError("split(): every separator must be a non-empty string")

    def split(str):
        return list(big.multisplit(str, separators, strip=strip))
    return split



@must_be_instance
def validate(*values, type=None):
    """
    Creates a converter function that validates a value
    from the command-line.

        values is a list of permissible values.
        type is the type for the value.  If not specified,
          type defaults to builtins.type(values[0]).

    If the value from the command-line is one of the values,
    returns value.  Otherwise reports a usage error.
    """
    if not values:
        raise AppealConfigurationError("validate() called without any values.")
    if type == None:
        type = builtins.type(values[0])
    failed = []
    for value in values:
        if not isinstance(value, type):
            failed.append(value)
    if failed:
        failed = " ".join(repr(x) for x in failed)
        raise AppealConfigurationError("validate() called with these non-homogeneous values {failed}")

    values_set = set(values)
    def validate(value:type):
        if value not in values_set:
            raise AppealUsageError(f"illegal value {value!r}, should be one of {' '.join(repr(v) for v in values)}")
        return value
    return validate

@must_be_instance
def validate_range(start, stop=None, *, type=None, clamp=False):
    """
    Creates a converter function that validates that
    a value from the command-line is within a range.

        start and stop are like the start and stop
            arguments for range().

        type is the type for the value.  If unspecified,
            it defaults to builtins.type(start).

    If the value from the command-line is within the
    range established by start and stop, returns value.

    If value is not inside the range of start and stop,
    and clamp=True, returns either start or stop,
    whichever is nearest.

    If value is not inside the range of start and stop,
    and clamp=False, raise a usage error.
    """
    if type is None:
        type = builtins.type(start)

    if stop is None:
        stop = start
        start = type()
        # ensure start is < stop
        if start > stop:
            start, stop = stop, start
    def validate_range(value:type):
        in_range = start <= value <= stop
        if not in_range:
            if not clamp:
                raise AppealUsageError(f"illegal value {value}, should be {start} <= value < {stop}")
            if value >= stop:
                value = stop
            else:
                value = start
        return value
    return validate_range



def no_arguments_callable(): pass
no_arguments_signature = inspect.signature(no_arguments_callable)





# this function isn't published as one of the _to_converter callables
def simple_type_to_converter(parameter, callable):
    cls = simple_type_signatures.get(callable)
    if not cls:
        return None
    if (callable == bool) and (parameter.kind == KEYWORD_ONLY):
        return BooleanOptionConverter
    return cls

none_and_empty = ((None, empty))
def unannotated_to_converter(parameter):
    if (dereference_annotated(parameter.annotation) in none_and_empty) and (parameter.default in none_and_empty):
        return SimpleTypeConverterStr


def type_to_converter(parameter):
    annotation = dereference_annotated(parameter.annotation)
    if not isinstance(annotation, type):
        return None
    cls = simple_type_to_converter(parameter, annotation)
    if cls:
        return cls
    if issubclass(annotation, SingleOption):
        return annotation
    return None

def callable_to_converter(parameter):
    annotation = dereference_annotated(parameter.annotation)
    if (annotation is empty) or (not builtins.callable(annotation)):
        return None
    if parameter.kind == KEYWORD_ONLY:
        return BaseOption
    return Converter

illegal_inferred_types = {dict, set, tuple, list}

def inferred_type_to_converter(parameter):
    annotation = dereference_annotated(parameter.annotation)
    if (annotation is not empty) or (parameter.default is empty):
        return None
    inferred_type = type(parameter.default)
    # print(f"inferred_type_to_converter(parameter={parameter})")
    cls = simple_type_to_converter(parameter, inferred_type)
    # print(f"  inferred_type={inferred_type} cls={cls}")
    if cls:
        return cls
    if issubclass(inferred_type, SingleOption):
        return inferred_type
    if inferred_type in illegal_inferred_types:
        return None
    if parameter.kind == KEYWORD_ONLY:
        return InferredOption
    return InferredConverter

sequence_types = {tuple, list}
def sequence_to_converter(parameter):
    annotation = dereference_annotated(parameter.annotation)
    if (annotation is not empty) or (parameter.default is empty):
        return None
    inferred_type = type(parameter.default)
    if inferred_type not in sequence_types:
        return None
    if parameter.kind == KEYWORD_ONLY:
        return InferredSequenceOption
    return InferredSequenceConverter



def _default_option(option, appeal, callable, parameter_name, annotation, default):
    if appeal.option_signature(option):
        return False
    appeal.option(parameter_name, option, annotation=annotation, default=default)(callable)
    return True


def default_short_option(appeal, callable, parameter_name, annotation, default):
    option = parameter_name_to_short_option(parameter_name)
    if not _default_option(option, appeal, callable, parameter_name, annotation, default):
        raise AppealConfigurationError(f"couldn't add default option {option} for {callable} parameter {parameter_name}")


def default_long_option(appeal, callable, parameter_name, annotation, default):
    if len(parameter_name) < 2:
        return
    option = parameter_name_to_long_option(parameter_name)
    if not _default_option(option,
        appeal, callable, parameter_name, annotation, default):
        raise AppealConfigurationError(f"couldn't add default option {option} for {callable} parameter {parameter_name}")

def default_options(appeal, callable, parameter_name, annotation, default):
    # print(f"default_options(appeal={appeal}, callable={callable}, parameter_name={parameter_name}, annotation={annotation}, default={default})")
    added_an_option = False
    options = [parameter_name_to_short_option(parameter_name)]
    if len(parameter_name) > 1:
        options.append(parameter_name_to_long_option(parameter_name))
    for option in options:
        worked = _default_option(option,
            appeal, callable, parameter_name, annotation, default)
        added_an_option = added_an_option or worked
    if not added_an_option:
        raise AppealConfigurationError(f"Couldn't add any default options for {callable} parameter {parameter_name}")


def unbound_callable(callable):
    """
    Unbinds a callable.
    If the callable is bound to an object (a "method"),
    returns the unbound callable.  Otherwise returns callable.
    """
    return callable.__func__ if isinstance(callable, types.MethodType) else callable



class SpecialSection:
    def __init__(self, name, topic_names, topic_values, topic_definitions, topics_desired):
        self.name = name

        # {"short_name": "fn_name.parameter_name" }
        self.topic_names = topic_names
        # {"fn_name.parameter_name": "usage_name"}
        self.topic_values = topic_values
        # {"fn_name.parameter_name": docs... }
        self.topic_definitions = topic_definitions

        # Appeal's "composable documentation" feature means that it merges
        # up the docs for arguments and options from child converters.
        # But what about opargs?  Those are "arguments" from the child
        # converter tree, but you probably don't want them merged.
        #
        # So topics_desired lets you specify which topics Appeal should
        # merge.
        self.topics_desired = topics_desired

        self.topics = {}
        self.topics_seen = set()



unspecified = object()

class Appeal:
    """
    An Appeal object can only process a single command-line.
    Once you have called main() or process() on an Appeal object,
    you can't call either of those methods again.
    """

    def __init__(self,
        name=None,
        *,
        default_options=default_options,
        repeat=False,
        parent=None,

        option_space_oparg = True,              # '--long OPARG' and '-s OPARG'

        short_option_equals_oparg = True,       # -s=OPARG
        short_option_concatenated_oparg = True, # -sOPARG, only supported if -s takes *exactly* one *optional* oparg

        positional_argument_usage_format = "{name}",

        # if true:
        #   * adds a "help" command (if your program supports commands)
        #   * supports lone "-h" and "--help" options which behave like the "help" command without arguments
        help=True,

        # if set to a non-empty string,
        #   * adds a "version" command (if your program has commands)
        #   * supports lone "-v" and "--version" options which behave like the "version" command without arguments
        version=None,

        # when printing docstrings: should Appeal add in missing arguments?
        usage_append_missing_options = True,
        usage_append_missing_arguments = True,

        usage_indent_definitions = 4,

        # when printing docstrings, how should we sort the options and arguments?
        #
        # valid options:
        #    None:     don't change order
        #    "sorted": sort lexigraphically.  note that options sort by the first long option.
        #    "usage":  reorder into the order they appear in usage.
        #
        # note that when sorting, options that appear multiple times will only be shown
        # once.  the second and subsequent appearances will be discarded.
        usage_sort_options = None,
        usage_sort_arguments = None,

        usage_max_columns = 80,

        log_events = bool(want_prints),

        ):
        self.parent = parent
        self.repeat = repeat

        self.name = name

        self.commands = {}
        self._global = None
        self._global_program = None
        self._global_command = None
        self._default = None
        self._default_program = None
        self._default_command = None
        self.full_name = ""
        self.depth = -1

        self.processor_preparer = None
        self.appeal_preparer = None

        self.usage_str = self.summary_str = self.doc_str = None

        # in root Appeal instance, self.root == self, self.parent == None
        # in child Appeal instance, self.root != self, self.parent != None (and != self)
        #
        # only accept settings parameters if we're the root Appeal instance
        if parent is None:
            self.root = self

            name = name or os.path.basename(sys.argv[0])
            self.name = self.full_name = name
            self.force_positional = False
            self.parsing_option = 0

            self.default_options = default_options

            self.option_parsing_semantics = (
                option_space_oparg,

                short_option_equals_oparg,
                short_option_concatenated_oparg,
                )

            self.usage_append_missing_options = usage_append_missing_options
            self.usage_append_missing_arguments = usage_append_missing_arguments
            self.usage_sort_options = usage_sort_options
            self.usage_sort_arguments = usage_sort_arguments
            self.usage_max_columns = usage_max_columns
            self.usage_indent_definitions = usage_indent_definitions

            # slightly hacky and limited!  sorry!
            self.positional_argument_usage_format = positional_argument_usage_format.replace("name.upper()", "__NAME__")

            # an "option entry" is:
            #   (option, callable, parameter, annotation, default)
            #
            #    option is the normalized option string
            #    callable is the unbound Python function/method
            #        note that if callable is a bound method object, we store that.
            #        we don't unbind it for this application.
            #    parameter is the string name of the parameter
            #    annotation is the annotation of the parameter (can be "empty")
            #    default is the default value of the parameter  (can be "empty")

            # self.fn_database[callable] = options, parameters, positionals
            # options = { option: option_entry }
            # kw_parameters = {parameter_name: [ option_entry, option_entry2, ...] )
            # positionals = {parameter_name: usage_presentation_name}
            #
            # if option is short option, it's just the single letter (e.g. "-v" -> "v")
            # if option is long option, it's the full string (e.g. "--verbose" -> "--verbose")
            # converter must be either a function or inspect.Parameter.empty
            #
            # You should *set* things in the *local* fn_database.
            # You should *look up* things using fn_database_lookup().
            self.fn_database = collections.defaultdict(lambda: ({}, {}, {}))

            self.support_help = help
            self.support_version = version

            self.program_id = 1

            # How does Appeal turn an inspect.Parameter into a Converter?
            #
            # It used to be simple: Appeal would examine the parameter's
            # callable (annotation), and its default, and use those to
            # produce a "callable" we'll use in a minute:
            #    if there's an annotation, return annotation.
            #    elif there's a default ('default' is neither empty nor None),
            #       return type(default).
            #    else return str.
            # (This function was called analyze_parameter.)
            #
            # Next we analyze the "callable" we just produced:
            #    if callable already a subclass of Converter, instantiate "callable".
            #    if callable is a basic type (str/int/float/complex/bool),
            #       instantiate the appropriate subclass of
            #       SimpleTypeConverter.
            #       (Special case for "bool" when is_option=True.)
            #    else wrap it with Option if it's an option, Converter
            #       if it isn't.
            # (This function was called create_converter.)
            #
            # This worked fine for what Appeal did at the time.  But there
            # was a snazzy new feature I wanted to add:
            #     def foo(a=[1, 2.0])
            # would *infer* that we should consume two command-line arguments,
            # and run int() on the first one and float() on the second.
            # In order to do that, we had a bit of a rewrite.
            #
            # Below we define converter_factories, a first stab at a
            # plugin system.  converter_factories is an iterable of
            # callables; each callable has the signature
            #       foo(callable, default, is_option)
            # The callable should return one of two things: either
            #    * a (proper) subclass of Converter, or
            #    * None.
            #
            # For this to work, we also had to adjust the signature of
            # Converter slightly.
            #
            # First, the constructors had to become consistent.  Every
            # subclass of Converter must strictly define its __init__ thus:
            #    def __init__(self, callable, default, appeal):
            #
            # Second, you now ask the Converter class or instance for the
            # signature.  You can no longer call
            #    inspect.signature(converter_instance.callable)
            #
            # How do you get the signature? two ways.
            #
            # 1) a Converter class must always have a "get_signature" classmethod:
            #       @classmethod
            #       def get_signature(cls, callable, default):
            #    Naturally, that works on classes and instances.
            #       a = ConverterSubclass.get_signature(callable, default)
            # 2) A Converter instance must always have a "__signature__" attribute.
            #       converter = cls(...)
            #       b = converter.__signature__
            #
            # (cls.__signature__ may be predefined on some Converter subclasses!
            #  But you can't rely on that.)

            self.converter_factories = [
                unannotated_to_converter,
                type_to_converter,
                callable_to_converter,
                inferred_type_to_converter,
                sequence_to_converter,
                ]
        else:
            self.root = self.parent.root

        # self.option_signature_database[option] = [signature, option_entry1, ...]
        #
        # stores the signature of the converter function for
        # this option.  stores an option_entry for each
        # place the option is defined on a converter, though
        # this is only used for error reporting, and we probably
        # only need one.
        #
        # note: is per-Appeal object.
        self.option_signature_database = {}

        self._calculate_full_name()

        self.log_events = log_events

    def format_positional_parameter(self, name):
        return self.root.positional_argument_usage_format.format(
            name=name, __NAME__=name.upper())

    def _calculate_full_name(self):
        if not self.name:
            return
        names = []
        appeal = self
        while appeal:
            names.append(appeal.name)
            appeal = appeal.parent
        self.full_name = " ".join([name for name in reversed(names)])
        self.depth = len(names) - 1

    def fn_database_lookup(self, callable):
        callable = unbound_callable(callable)
        # appeal = self
        # while appeal:
        #     if name in appeal.fn_database:
        #         return appeal.fn_database[fn]
        #     appeal = appeal.parent
        # raise KeyError, the lazy way
        x = self.root.fn_database[callable]
        # print(f"fn_database_lookup(callable={callable} -> {x}")
        return x

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.full_name!r} depth={self.depth}>"

    def command(self, name=None):
        a = None
        if name is not None:
            a = self.commands.get(name)
        if not a:
            a = Appeal(name=name, parent=self)
        return a

    def __call__(self, callable):
        assert callable and builtins.callable(callable)
        self._global = callable
        if self.root != self:
            if self.name is None:
                self.name = callable.__name__
                self._calculate_full_name()
            self.parent.commands[self.name] = self
        return callable

    def global_command(self):
        if self.root != self:
            raise AppealConfigurationError("only the root Appeal instance can have a global command")
        return self.__call__

    def default_command(self):
        def closure(callable):
            assert callable and builtins.callable(callable)
            self._default = callable
            return callable
        return closure

    class Rebinder(Preparer):
        def __init__(self, *, bind_method=True):
            self.bind_method = bind_method
            self.placeholder = f"_r_{hex(id(object()))}"

        def wrap(self, fn):
            fn2 = functools.partial(fn, self.placeholder)
            update_wrapper(fn2, fn)
            return fn2

        def __call__(self, fn):
            return self.wrap(fn)

        def bind(self, instance):
            rebinder = partial_rebind_method if self.bind_method else partial_rebind_positional
            def prepare(fn):
                try:
                    # print(f"\nattempting rebind of\n    fn={fn}\n    self.placeholder={self.placeholder}\n    instance={instance}\n    rebinder={rebinder}\n")
                    return rebinder(fn, self.placeholder, instance)
                except ValueError:
                    return fn
            return prepare

    class CommandMethodPreparer(Rebinder):
        def __init__(self, appeal, *, bind_method=True):
            super().__init__(bind_method=bind_method)
            self.appeal = appeal
            self.placeholder = f"_cmp_{hex(id(object()))}"

        def command(self, name=None):
            def command(fn):
                fn2 = self.wrap(fn)
                self.appeal.command(name=name)(fn2)
                return fn
            return command

        def __call__(self, name=None):
            return self.command(name=name)

        def global_command(self):
            def global_command(fn):
                # print(f"global_command wrapped fn={fn} with partial for self.placeholder={self.placeholder}")
                fn2 = self.wrap(fn)
                self.appeal.global_command()(fn2)
                return fn
            return global_command

        def default_command(self):
            def default_command(fn):
                # print(f"default_command wrapped fn={fn} with partial for self.placeholder={self.placeholder}")
                fn2 = self.wrap(fn)
                self.appeal.default_command()(fn2)
                return fn
            return global_command

        def bind(self, instance):
            rebinder = partial_rebind_method if self.bind_method else partial_rebind_positional
            def prepare(fn):
                try:
                    # print(f"\nattempting rebind of\n    fn={fn}\n    self.placeholder={self.placeholder}\n    instance={instance}\n    rebinder={rebinder}\n")
                    return rebinder(fn, self.placeholder, instance)
                except ValueError:
                    return fn
            return prepare

    def command_method(self, bind_method=True):
        return self.CommandMethodPreparer(self, bind_method=bind_method)

    def bind_processor(self):
        if not self.processor_preparer:
            self.processor_preparer = self.Rebinder(bind_method=False)
        return self.processor_preparer

    def bind_appeal(self):
        if not self.appeal_preparer:
            self.appeal_preparer = self.Rebinder(bind_method=False)
        return self.appeal_preparer

    def app_class(self, bind_method=True):
        command_method = self.CommandMethodPreparer(self, bind_method=bind_method)

        def app_class():
            def app_class(cls):
                # print("\n<app_class d> 0 in decorator, called on", cls)
                assert isinstance(cls, type)
                signature = inspect.signature(cls)
                bind_processor = self.bind_processor()
                # print(f"<app_class d> 1 bind_processor={bind_processor}")
                # print(f"<app_class d> 2 bind_processor.placeholder={bind_processor.placeholder}")

                def fn(processor, *args, **kwargs):
                    # print(f"\n[app_class gc] in global command, cls={cls} processor={processor}\n")
                    # print(f"\n[app_class gc] args={args}\n")
                    # print(f"\n[app_class gc] kwargs={kwargs}\n")
                    o = cls(*args, **kwargs)
                    # print(f"\n[app_class gc] binding o={o}\n")
                    processor.preparer(command_method.bind(o))
                    return None
                # print(f"<app_class d> 3 inspect.signature(fn)={inspect.signature(fn)}")
                # print(f"<app_class d> 4 inspect.signature(bind_processor)={inspect.signature(bind_processor)}")
                # print(f"    fn={fn}")
                # print(f"    isinstance(fn, functools.partial)={isinstance(fn, functools.partial)}")
                fn = bind_processor(fn)

                # print(f"<app_class d> 6 inspect.signature(fn)={inspect.signature(fn)}")
                # print(f"    fn={fn}")
                # print(f"    isinstance(fn, functools.partial)={isinstance(fn, functools.partial)}")
                fn.__signature__ = signature
                # print(f"<app_class d> 7 inspect.signature(fn)={inspect.signature(fn)}")

                self.global_command()(fn)
                # print(f"<app_class d> 8 self._global={self._global}")
                return cls
            return app_class

        # print("appeal.app_class returning", app_class, command_method)
        return app_class, command_method


    def argument(self, parameter, *, usage=None):
        def argument(callable):
            _, _, positionals = self.fn_database_lookup(callable)
            positionals[parameter] = usage
            return callable
        return argument

    def option_signature(self, option):
        """
        Returns the option_signature_database entry for that option.
        if defined, the return value is a list:
            [option_signature, option_entry1, ...]

        The option should be "denormalized", as in, it should be
        passed in how it would appear on the command-line.  e.g.
            '-v'
            '--verbose'
        """
        option = normalize_option(option)
        return self.option_signature_database.get(option)


    def option(self, parameter_name, *options, annotation=empty, default=empty):
        """
        Additional decorator for @command functions.  Explicitly adds
        one or more options mapped to a parameter on the @command function,
        specifying an explicit annotation and/or default value.

        Notes:

        * The parameter must be a keyword-only parameter.

        * If the @command function accepts a **kwargs argument,
          @option can be used to create arguments passed in via **kwargs.

        * The parameters to @option *always override*
          the annotation and default of the original parameter.

        * It may seem like there's no point to the "default" parameter;
          keyword-only parameters must have a default already.  So why
          make the user pass in a "default" here?  Two reasons:
            * The "default" is passed in to Option.init() and may be
              useful there.
            * The user may skip the annotation, in which case the
              annotation will likely be inferred from the default
              (e.g. type(default)).
        """

        if not options:
            raise AppealConfigurationError(f"Appeal.option: no options specified")

        normalized_options = []
        for option in options:
            if not (isinstance(option, str)
                and option.startswith("-")
                and (((len(option) == 2) and option[1].isalnum())
                    or ((len(option) >= 4) and option.startswith("--")))):
                raise AppealConfigurationError(f"Appeal.option: {option!r} is not a legal option")
            normalized = normalize_option(option)
            normalized_options.append((normalized, option))

        parameter = inspect.Parameter(parameter_name, KEYWORD_ONLY, annotation=annotation, default=default)

        # print(f"@option annotation={annotation} default={default}")
        cls = self.root.map_to_converter(parameter)
        if cls is None:
            raise AppealConfigurationError(f"Appeal.option: could not determine Converter for annotation={annotation} default={default}")
        annotation_signature = cls.get_signature(parameter)
        # annotation_signature = callable_signature(annotation)

        def option(callable):
            options, kw_parameters, _ = self.fn_database_lookup(callable)
            mappings = kw_parameters.get(parameter_name)
            if mappings is None:
                mappings = kw_parameters[parameter_name] = []

            for option, denormalized_option in normalized_options:
                entry = (option, callable, parameter)
                # option is already normalized, so let's just access the dict directly.
                existing_entry = self.option_signature_database.get(option)
                if existing_entry:
                    existing_signature = existing_entry[0]
                    if annotation_signature != existing_signature:
                        option2, callable2, parameter2, = existing_entry[1]
                        raise AppealConfigurationError(f"{denormalized_option} is already defined on {callable2} parameter {parameter2!r} with a different signature!")
                options[option] = entry
                mappings.append(entry)
                option_signature_entry = [annotation_signature, entry]
                self.option_signature_database[option] = option_signature_entry
            return callable
        return option


    def map_to_converter(self, parameter):
        # print(f"map_to_converter(parameter={parameter})")
        for factory in self.root.converter_factories:
            c = factory(parameter)
            # print(f"  * factory={factory} -> c={c}")
            if c:
                break
        return c

    def compute_usage(self, commands=None, override_doc=None):
        #
        # This function is pretty ugly.  The top half is glue code mating the
        # new Charm model to the bottom half; the bottom half is a pile of legacy
        # code written assuming the old Charm model, which is the tip of the iceberg
        # for a whole pile of complex code computing usage.
        #
        # For now this hack job is easier than rewriting the usage code.
        # (Which TBH I'm not 100% sure is the approach I want anyway).
        #

        if self.usage_str:
            return self.usage_str, self.split_summary, self.doc_sections

        if not self._global_program:
            self.analyze(None)

        callable = self._global
        fn_name = callable.__name__

        formatter = self.root.format_positional_parameter
        usage_str, arguments_values, options_values = charm_usage(self._global_program, formatter=formatter)

        if commands:
            if usage_str and (not usage_str[-1].isspace()):
                usage_str += ' '
            usage_str += formatter("command")

        # {"{command_name}" : "help string"}
        # summary text parsed from docstring on using that command
        commands_definitions = {}

        if commands:
            for name, child in commands.items():
                child.analyze(None)
                child_usage_str, child_split_summary, child_doc_sections = child.compute_usage()
                commands_definitions[name] = child_split_summary

        # it's a little inconvenient to do this with Charm
        # but we'll give it a go.
        #
        # what we want:
        # build a list of all the functions in the annotations
        # tree underneath our main function, sorted deepest
        # first.
        #
        # however! note that a Charm annotation function always
        # has the same subtree underneath it.  so let's not
        # bother re-creating and re-parsing the same function
        # multiple times.
        #
        # this isn't too hard.  the only complication is that
        # we should use the deepest version of each function.
        # (so we do the max(depth) thing.)
        #
        # step 1:
        # produce a list of annotation functions in the tree
        # underneath us, in deepest-to-shallowest order.

        # signature = callable_signature(callable)
        # positional_children = set()
        # option_children = set()

        # info = [self.callable, signature, 0, positional_children, option_children]
        ci = CharmBaseInterpreter(self._global_program, name=fn_name)

        last_op = None
        option_depth = 0
        programs = {}

        two_lists = lambda: ([], [])
        mapped_options = collections.defaultdict(two_lists)

        for ip, op in ci:
            # print(f"## [{ip:>3}] op={op}")
            if op.op == opcode.create_converter:
                c = {'parameter': op.parameter, 'parameters': {}, 'options': collections.defaultdict(list)}
                ci.converters[op.key] = ci.o = c
                continue

            if op.op == opcode.load_converter:
                ci.converter = ci.converters[op.key]
                continue

            if (op.op == opcode.append_to_args) and last_op and (last_op.op == opcode.consume_argument):
                ci.converter['parameters'][op.parameter] = op.usage
                continue

            if op.op == opcode.map_option:
                parameter = c['parameter']
                program = op.program

                # def __init__(self, option, program, callable, parameter, key):
                options, full_names = mapped_options[program.id]
                options.append(denormalize_option(op.option))

                full_name = f"{op.parameter.name}"
                full_names.append(full_name)

                converter = ci.converters[op.key]
                option_depth += 1
                ci.call(op.program)
                continue

            if op.op == opcode.end:
                option_depth -= 1
                continue

        children = {}
        values = []
        values_callable_index = {}

        positional_parameter_kinds = set((POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD, VAR_POSITIONAL))

        for c in reversed_dict_values(ci.converters.values()):
            parameter = c['parameter']
            callable = dereference_annotated(parameter.annotation)

            positional_children = set()
            option_children = set()
            cls = self.root.map_to_converter(parameter)
            signature = cls.get_signature(parameter)
            for p in signature.parameters.values():
                annotation = dereference_annotated(p.annotation)
                cls2 = self.root.map_to_converter(p)
                if not issubclass(cls2, SimpleTypeConverter):
                    if p.kind in positional_parameter_kinds:
                        positional_children.add(annotation)
                    elif p.kind == KEYWORD_ONLY:
                        option_children.add(annotation)
            values_callable_index[callable] = len(values)
            #              callable, signature, depth, positional_children, option_children
            values.append([callable, signature, 0,     positional_children, option_children])
            kids = (positional_children | option_children)
            children[callable] = kids

        # since we iterated over reversed, the last value is c[0]
        # which means callable is already the root of the whole tree
        # do dfs to calculate depths

        def assign_depth(callable, depth):
            value = values[values_callable_index[callable]]
            value[2] = max(value[2], depth)

            for child in children[callable]:
                assign_depth(child, depth + 1)

        assign_depth(callable, 0)

        #
        # Above this line is the glue code mating the new Charm model
        # to the old unmodified code.
        #
        # Below this line is the old unmodified code.
        ################################################################
        #

        values.sort(key=lambda o: o[2], reverse=True)
        if want_prints:
            for current, signature, depth, positional_children, option_children in values:
                if current in simple_type_signatures:
                    continue
                print(f"current={current}\n    depth={depth}\n    positional_children={positional_children}\n    option_children={option_children}\n    signature={signature}\n")

        # step 2:
        # process the docstrings of those annotation functions, deepest to shallowest.
        # when we process a function, also merge up from its children.

        fn_to_docs = {}

        if want_prints:
            print(f"[] arguments_values={arguments_values}")
            print(f"[] options_values={options_values}")

        # again! complicated.
        #
        # the "topic" is the thing in the left column in curly braces:
        #   {foo}
        # this literal string "foo" represents a parameter of some kind.  it gets
        # looked up and substituted a couple different ways.
        #
        # First, the literal string is formatted using the "*_topic_names" dict
        # (e.g. options_topic_names), which maps it to a "full name"
        # ("fn_name.parameter_name") which is the internal canonical name
        # for the parameter.  e.g.:
        #     foo      -> "myfn.foo"
        #     myfn.foo -> "myfn.foo"
        # The "*_topic_names" must contain, in order of highest to lowest
        # priority:
        #    the name of the current function: getattrproxy, mapping parameter name to full name
        #    the name of every child function: getattrproxy, mapping that function's parameter names to full names
        #    the name of the parameters of the current function: full name
        #    every unique parameter_name for any child function: full name for that parameter
        #
        # Second, at rendering time, this full name is looked up in "*_topic_values"
        # (e.g. optioncs_topic_values)  to produce the actual value for the left column.
        # so "*_topic_values" doesn't use proxy objects.  it maps full names to what you
        # want presented in the docs for that parameter.
        #
        # Third, the values from the right column are stored in "*_topic_definitions".
        # That dict maps full names to the text of the definition, which is a list of
        # strings representing individual lines.
        #
        # Fourth, in the right column, anything in curly braces is looked up
        # in "all_definitions".  This must contain, in order of highest to lowest
        # priority:
        #    the name of the current function: getattrproxy, mapping parameter name to definition
        #    the name of every child function: getattrproxy, mapping that function's parameter names to definitions
        #    every parameter_name on the current function: definition for that parameter
        #    every unique parameter_name for any child function: definition for that parameter
        #
        # Finally, "*_desired" (e.g. options_desired) is a set of full names of parameters
        # that we want defined in that special section (e.g. options).  If the user hasn't
        # defined one in the current docstring, but they defined one in a child docstring,
        # we'll merge up the child definition and add it.

        for callable, signature, depth, positional_children, option_children in values:
            if callable in simple_type_signatures:
                continue

            # print("_" * 79)
            # print(f"callable={callable} signature={signature} depth={depth} positional_children={positional_children} positional_children={positional_children}")

            fn_name = callable.__name__
            prefix = f"{fn_name}."

            # if callable == self.callable:
            #     doc = self.docstring or ""
            # else:
            #     doc = callable.__doc__ or ""
            doc = callable.__doc__ or ""
            if not doc and callable == self._global and override_doc:
                doc = override_doc
            doc.expandtabs()
            doc = textwrap.dedent(doc)

            arguments_topic_values = {k: v for k, v in arguments_values.items() if k.startswith(prefix)}
            # arguments_and_opargs_topic_values = {k: v for k, v in arguments_values.items() if k.startswith(prefix)}
            options_topic_values = {k: v for k, v in options_values.items() if k.startswith(prefix)}

            arguments_topic_definitions = {}
            # arguments_and_opargs_topic_definitions = {}
            options_topic_definitions = {}

            # merge up all the info from our children
            for child in tuple(positional_children):
                for container, child_container in zip(
                    (
                        arguments_topic_definitions,
                        arguments_topic_values,
                        # arguments_and_opargs_topic_definitions,
                        # arguments_and_opargs_topic_values,
                        options_topic_definitions,
                        options_topic_values,
                        positional_children,
                        option_children,
                    ),
                    fn_to_docs[child]
                    ):
                    container.update(child_container)

            for child in tuple(option_children):
                for container, child_container in zip(
                    (
                        arguments_topic_definitions,
                        arguments_topic_values,
                        # arguments_and_opargs_topic_definitions,
                        # arguments_and_opargs_topic_values,
                        # arguments_and_opargs_topic_definitions,
                        # arguments_and_opargs_topic_values,
                        options_topic_definitions,
                        options_topic_values,
                        option_children,
                        option_children,
                    ),
                    fn_to_docs[child]
                    ):
                    container.update(child_container)

            all_values= {}
            # all_values.update(arguments_and_opargs_topic_values)
            all_values.update(arguments_topic_values)
            all_values.update(options_topic_values)

            arguments_topic_names = {}
            # arguments_and_opargs_topic_names = {}
            options_topic_names = {}
            all_definitions = {}

            for i, (d, values, desired_field) in enumerate((
                (arguments_topic_names, arguments_topic_values, "name"),
                # (arguments_and_opargs_topic_names, arguments_and_opargs_topic_values, "name"),
                (options_topic_names, options_topic_values, "name"),
                (all_definitions, all_values, "value"),
                ), 1):
                # build up proxy dicts
                proxy_dicts = collections.defaultdict(dict)
                for name, value in values.items():
                    before_dot, dot, after_dot = name.partition(".")
                    assert dot
                    desired = value if desired_field == "value" else name
                    proxy_dicts[before_dot][after_dot] = desired

                # print(f">>> pass {i} underlying proxy_dicts")
                # pprint.pprint(proxy_dicts)
                # print()

                # priority 1: fn_name -> proxy
                d.update( {name: DictGetattrProxy(value, name) for name, value in proxy_dicts.items() } )

                # priority 2: parameters of current function
                if fn_name in proxy_dicts:
                    # remove it from proxy dicts to obviate
                    # processing it a second time in priority 3 below
                    parameters = proxy_dicts.pop(fn_name)
                    for name, value in parameters.items():
                        # print(f"priority 2 name={name} value={value}")
                        if name not in d:
                            if desired == "name":
                                value = f"{fn_name}.{name}"
                            d[name] = value

                # priority 3: parameters of all child functions,
                # as long as they don't collide
                discarded = set()
                child_parameters = {}
                for child_name, parameters in proxy_dicts.items():
                    if (name not in d) and (name not in discarded):
                        if name in child_parameters:
                            discarded.add(name)
                            del child_parameters[name]
                            continue
                        if desired == "name":
                            value = f"{fn_name}.{name}"
                        child_parameters[name] = value
                d.update(child_parameters)

            arguments_desired = set(arguments_topic_values)
            options_desired = set(options_topic_values)

            if want_prints:
                print("_"*79)
                l = locals()

                # arguments_and_opargs_topic_names
                # arguments_and_opargs_topic_values
                # arguments_and_opargs_topic_definitions

                for name in """
                    callable

                    arguments_topic_names
                    arguments_topic_values
                    arguments_topic_definitions
                    arguments_desired

                    options_topic_names
                    options_topic_values
                    options_topic_definitions

                    options_desired

                    commands_definitions

                    all_definitions

                    doc
                    """.strip().split():
                    print(f">>> {name}:")
                    pprint.pprint(l[name])
                    print()

            ##
            ## parse docstring
            ##

            arguments_section = SpecialSection("[[arguments]]", arguments_topic_names, arguments_topic_values, arguments_topic_definitions, arguments_desired)
            options_section = SpecialSection("[[options]]", options_topic_names, options_topic_values, options_topic_definitions, options_desired)
            # commands are kind of a degenerate form, we don't reference anything from the converter tree
            command_identity = {k:k for k in commands_definitions}
            commands_section = SpecialSection("[[commands]]", command_identity, command_identity, commands_definitions, set(command_identity))

            special_sections_available = {section.name: section for section in (arguments_section, options_section, commands_section)}
            special_sections_used = {}


            summary = None
            special_section = None
            section = None

            topic = None
            definition = None

            sections = []

            def discard_trailing_empty_lines(l):
                while l and not l[-1]:
                    l.pop()

            def next(new_state, line=None):
                nonlocal state
                # print(f">>>> next state={state.__name__.rpartition('.')[2]} line={line}")
                state = new_state
                if line is not None:
                    state(line)

            def determine_next_section_type(line):
                nonlocal special_section
                nonlocal section
                if (not line) and section:
                    section.append(line)
                    return
                if line in special_sections_used:
                    raise AssertInternalError(f"{self.callable.__name__}: can't use {line} special section twice")
                # [[special section name]] must be at the dedented left column
                if is_special_section(line):
                    finish_section()
                    next(start_special_section, line)
                else:
                    if special_section:
                        finish_section()
                    next(start_body_section, line)

            initial_state = determine_next_section_type

            def start_body_section(line):
                nonlocal section
                if section is None:
                    section = []
                    sections.append(section)
                next(in_body_section, line)

            def in_body_section(line):
                section.append(line.format_map(all_definitions))
                if not line:
                    next(maybe_after_body_section)

            # if we continue the non-special-section,
            # we'll just fall through and continue appending
            # to the current body section.
            def maybe_after_body_section(line):
                if not line:
                    section.append(line)
                else:
                    next(determine_next_section_type, line)

            def finish_body_section():
                nonlocal section
                if section:
                    # discard_trailing_empty_lines(section)
                    section = None

            def is_special_section(line):
                return special_sections_available.get(line)

            def start_special_section(line):
                nonlocal special_section
                special_section = special_sections_available[line]
                sections.append(special_section)
                next(in_special_section)

            def in_special_section(line):
                nonlocal topic
                nonlocal definition

                # [[end]] or [[arguments]] etc
                # must be at the dedented left column
                if line.startswith("[["):
                    # if it's not [[end]], we'll pass it in below
                    if line == "[[end]]":
                        line = None
                    next(determine_next_section_type, line)
                    return

                # topics must be at the (dedented) left column
                topic_line = line.startswith("{") and (not line.startswith("{{"))
                if not (topic or topic_line):
                    raise AppealConfigurationError(f"{self.callable}: docstring section {special_section.name} didn't start with a topic line (one starting with {{parameter/command}})")

                if not topic_line:
                    # definition line
                    lstripped = line.lstrip()
                    if (len(line) - len(lstripped)) < 4:
                        definition.append(lstripped)
                    else:
                        definition.append(line.format_map(all_definitions))
                    return

                # topic line
                key, curly, trailing = line.partition('}')
                assert curly
                key = key + curly
                if self.name:
                    name = self.name
                elif self._global:
                    name = self._global.__name__
                else:
                    name = "(unknown callable)"

                try:
                    topic = key.format_map(special_section.topic_names)
                except KeyError as e:
                    raise AppealConfigurationError(f"{name}: docstring section {special_section.name} has unknown topic {key!r}")
                if topic in special_section.topics_seen:
                    raise AppealConfigurationError(f"{name}: docstring section {special_section.name} topic {key!r} defined twice")
                special_section.topics_seen.add(topic)
                definition = []
                if trailing:
                    trailing = trailing.lstrip().format_map(all_definitions)
                    if trailing:
                        definition.append(trailing)
                special_section.topics[topic] = definition

            def finish_special_section():
                nonlocal special_section

                topics2 = {}
                for topic, definition in special_section.topic_definitions.items():
                    if topic not in special_section.topics_desired:
                        continue
                    if topic not in special_section.topics_seen:
                        topics2[topic] = definition
                for topic, definition in special_section.topics.items():
                    discard_trailing_empty_lines(definition)
                    if not definition:
                        existing_definition = special_section.topic_definitions.get(topic)
                        if existing_definition:
                            definition = existing_definition
                    topics2[topic] = definition
                special_section.topics = topics2
                special_section.topic_definitions.update(topics2)

                special_section = None


            def finish_section():
                nonlocal special_section
                nonlocal section
                if special_section:
                    finish_special_section()
                else:
                    finish_body_section()

            state = initial_state

            for line in doc.split("\n"):
                line = line.rstrip()
                # print(f">> state={state.__name__.rpartition('.')[2]} line={line}")
                state(line)
            finish_section()

            # print("JUST FINISHED.  SECTIONS:")
            # pprint.pprint(sections)

            if sections:
                if isinstance(sections[0], list):
                    first_section = sections[0]

                    # ignore leading blank lines
                    while first_section:
                        if first_section[0]:
                            break
                        first_section.pop(0)

                    # strip off leading non-blank lines for summary
                    summary_lines = []
                    while first_section:
                        if not first_section[0]:
                            break
                        summary_lines.append(first_section.pop(0))

                    # strip leading blank lines
                    while first_section:
                        if first_section[0]:
                            break
                        first_section.pop(0)

                    # print("processed summary:")
                    # print(f"   summary_lines={summary_lines}")
                    # print(f"   first_section={first_section}")

                    split_summary = text.fancy_text_split("\n".join(summary_lines), allow_code=False)

            if want_prints:
                print(f"[] arguments_topic_names={arguments_topic_names}")
                print(f"[] arguments_topic_values={arguments_topic_values}")
                print(f"[] arguments_topic_definitions={arguments_topic_definitions}")
                # print(f"[] arguments_and_opargs_topic_names={arguments_and_opargs_topic_names}")
                # print(f"[] arguments_and_opargs_topic_values={arguments_and_opargs_topic_values}")
                # print(f"[] arguments_and_opargs_topic_definitions={arguments_and_opargs_topic_definitions}")
                print(f"[] arguments_desired={arguments_desired}")
                print(f"[] options_topic_names={options_topic_names}")
                print(f"[] options_topic_values={options_topic_values}")
                print(f"[] options_topic_definitions={options_topic_definitions}")
                print(f"[] options_desired={options_desired}")

            fn_to_docs[callable] = (
                arguments_topic_definitions,
                arguments_topic_values,
                # arguments_and_opargs_topic_definitions,
                # arguments_and_opargs_topic_values,
                options_topic_definitions,
                options_topic_values,
                positional_children,
                option_children,
                )
            continue

        self.usage_str = usage_str
        self.split_summary = split_summary
        self.doc_sections = sections

        return usage_str, split_summary, sections

    def render_docstring(self, commands=None, override_doc=None):
        """
        returns usage_str, summary_str, doc_str
        """
        if self.doc_str is not None:
            return self.usage_str, self.summary_str, self.doc_str

        usage_str, split_summary, doc_sections = self.compute_usage(commands=commands, override_doc=override_doc)
        # print(f"doc_sections={doc_sections}")

        if split_summary:
            summary_str = text.presplit_textwrap(split_summary)
        else:
            summary_str = ""

        # doc
        lines = []
        usage_sections = {}

        # print("\n\n")
        # print("DOC SECTIONS")
        # pprint.pprint(doc_sections)

        for section_number, section in enumerate(doc_sections):
            if not section:
                continue

            if isinstance(section, list):
                # print(f"section #{section_number}: verbatim\n{section!r}\n")
                for line in section:
                    lines.append(line)
                continue

            assert isinstance(section, SpecialSection)
            # print(f"section #{section_number}: special section: {section.name}")
            # pprint.pprint(section.topics)
            # print()

            shortest_topic = math.inf
            longest_topic = -1
            subsections = []
            for topic, definition in section.topics.items():
                topic = section.topic_values[topic]
                shortest_topic = min(shortest_topic, len(topic))
                longest_topic = max(longest_topic, len(topic))
                words = text.fancy_text_split("\n".join(definition))
                subsections.append((topic, words))

            # print(subsections)

            try:
                columns, rows = os.get_terminal_size()
            except OSError:
                rows = 25
                columns = 80
            columns = min(columns, self.root.usage_max_columns)

            column0width = self.root.usage_indent_definitions

            column1width = min((columns // 4) - 4, max(12, longest_topic))
            column1width += 4

            column2width = columns - (column0width + column1width)

            for topic, words in subsections:
                # print("TOPIC", topic, "WORDS", words)
                column0 = ''
                column1 = topic
                column2 = text.presplit_textwrap(words, margin=column2width)
                final = text.merge_columns(
                    (column0, column0width, column0width),
                    (column1, column1width, column1width),
                    (column2, column2width, column2width),
                    )
                # print("FINAL", repr(final))
                lines.append(final)
            # lines.append('')

        doc_str = "\n".join(lines).rstrip()
        # print(f"render_doctstring returning usage_str={usage_str} summary_str={summary_str} doc_str={doc_str}")

        self.summary_str = summary_str
        self.doc_str = doc_str

        return usage_str, summary_str, doc_str

    def usage(self, *, usage=False, summary=False, doc=False):
        # print(f"yoooo sage: {self} {self._global}")
        if self._global:
            docstring = self._global.__doc__
        else:
            def no_op(): pass
            self._global = no_op
            docstring = ""
        self.analyze(None)
        # print(f"FOO-USAGE self._global={self._global} self._global_program={self._global_program}")
        # usage_str = charm_usage(self._global_program)
        # print(self.name, usage_str)
        # return
        if not docstring:
            docstring = []
            # if self._global_command.args_converters:
            #     docstring.append("Arguments:\n\n[[arguments]]\n[[end]]\n")
            # if self._global_command.kwargs_converters:
            #     docstring.append("Options:\n\n[[options]]\n[[end]]\n")
            if self.commands:
                docstring.append("Commands:\n\n[[commands]]\n[[end]]\n")
            docstring = "\n".join(docstring).rstrip()
            # self._global_command.docstring = docstring
            # print(f"self._global_command.docstring = {docstring!r}")
            # print(f"self.commands={self.commands}")
        usage_str, summary_str, doc_str = self.render_docstring(commands=self.commands, override_doc=docstring)
        if want_prints:
            print(f">> usage from {self}:")
            print(">> usage")
            print(usage_str)
            print(">> summary")
            print(summary_str)
            print(">> doc")
            print(doc_str)
        spacer = False
        if usage:
            print("usage:", self.full_name, usage_str)
            spacer = True
        if summary and summary_str:
            if spacer:
                print()
            print(summary_str)
            spacer = True
        if doc and doc_str:
            if spacer:
                print()
            print(doc_str)

    def error(self, s):
        raise AppealUsageError("error: " + s)
        print("error:", s)
        print()
        return self.usage(usage=True, summary=True, doc=True)

    def version(self):
        print(self.support_version)

    def help(self, *command):
        """
        Print usage documentation on a specific command.
        """
        commands = " ".join(command)
        appeal = self
        for name in command:
            appeal = appeal.commands.get(name)
            if not appeal:
                raise AppealUsageError(f'"{name}" is not a legal command.')
        appeal.usage(usage=True, summary=True, doc=True)

    def _analyze_attribute(self, name):
        if not getattr(self, name):
            return None
        program_attr = name + "_program"
        program = getattr(self, program_attr)
        if not program:
            callable = getattr(self, name)
            program = charm_compile(self, callable)
            if want_prints:
                print()
            setattr(self, program_attr, program)
            # print(f"compiled program for {name}, {program}")
        return program

    def analyze(self, processor):
        if processor:
            callable = getattr(self, "_global")
            if callable:
                name = getattr(callable, "__name__", repr(callable))
            else:
                name = "None"
            processor.log_event(f"analyze start ({name})")
        self._analyze_attribute("_global")

    def _parse_attribute(self, name, processor):
        program = self._analyze_attribute(name)
        if not program:
            return None
        if want_prints:
            charm_print(program)
        # converter = charm_parse(self, program, processor.argi)
        interpreter = CharmInterpreter(processor, program)
        converter = interpreter()
        processor.commands.append(converter)
        return converter

    def parse(self, processor):
        callable = getattr(self, "_global")
        if callable:
            name = getattr(callable, "__name__", repr(callable))
        else:
            name = "None"
        processor.log_event(f"parse start ({name})")

        self._parse_attribute("_global", processor)

        if not processor.argi:
            # if there are no arguments waiting here,
            # then they didn't want to run a command.
            # if any commands are defined, and they didn't specify one,
            # if there's a default command, run it.
            # otherwise, that's an error.
            default_converter = self._parse_attribute("_default", processor)
            if (not default_converter) and self.commands:
                raise AppealUsageError("no command specified.")
            return

        if self.commands:
            # okay, we have arguments waiting, and there are commands defined.
            for command_name in processor.argi:
                sub_appeal = self.commands.get(command_name)
                if not sub_appeal:
                    # partial spelling check would go here, e.g. "sta" being short for "status"
                    self.error(f"unknown command {command_name}")
                # don't append! just parse.
                # the recursive Appeal.parse call will append.
                sub_appeal.analyze(processor)
                sub_appeal.parse(processor)
                if not (self.repeat and processor.argi):
                    break

        if processor.argi:
            leftovers = " ".join(shlex.quote(s) for s in processor.argi)
            raise AppealUsageError(f"leftover cmdline arguments! {leftovers!r}")

    def convert(self, processor):
        processor.log_event("convert start")
        for command in processor.commands:
            command.convert(processor)

    def execute(self, processor):
        processor.log_event("execute start")
        result = None
        for command in processor.commands:
            result = command.execute(processor)
            if result:
                break
        return result

    def processor(self):
        return Processor(self)

    def process(self, args=None):
        processor = self.processor()
        result = processor(args)
        return result

    def main(self, args=None):
        processor = self.processor()
        processor.main(args)


class Processor:
    def __init__(self, appeal):
        self.events = []
        self.log_event("process start")

        self.appeal = appeal

        self.argi = None
        self.preparers = []
        self.commands = []
        self.breadcrumbs = []
        self.result = None

    def push_breadcrumb(self, breadcrumb):
        self.breadcrumbs.append(breadcrumb)

    def pop_breadcrumb(self):
        return self.breadcrumbs.pop()

    def format_breadcrumbs(self):
        return " ".join(self.breadcrumbs)

    def log_event(self, event):
        self.events.append((event, event_clock()))

    def preparer(self, preparer):
        if not callable(preparer):
            raise ValueError(f"{preparer} is not callable")
        # print(f"((( adding preparer={preparer}")
        self.preparers.append(preparer)

    def execute_preparers(self, fn):
        for preparer in self.preparers:
            try:
                fn = preparer(fn)
            except ValueError:
                pass
        return fn

    def print_log(self):
        if not self.events:
            return
        def format_time(t):
            seconds = t // 1000000000
            nanoseconds = t - seconds
            return f"{seconds:02}.{nanoseconds:09}"

        start_time = previous = self.events[0][1]
        formatted = []
        for i, (event, t) in enumerate(self.events):
            elapsed = t - start_time
            if i:
                delta = elapsed - previous
                formatted[-1][-1] = format_time(delta)
            formatted.append([event, format_time(elapsed), "            "])
            previous = elapsed

        print()
        print("[event log]")
        print(f"  start         elapsed       event")
        print(f"  ------------  ------------  -------------")

        for event, start, elapsed in formatted:
            print(f"  {start}  {elapsed}  {event}")

    def __call__(self, args=None):
        if args is None:
            args = sys.argv[1:]
        self.args = args
        self.argi = argi = PushbackIterator(args)

        if want_prints:
            argi.stack.extend(reversed(args))
            argi.i = None

        appeal = self.appeal
        if appeal.support_version:
            if (len(args) == 1) and args[0] in ("-v", "--version"):
                return appeal.version()
            if appeal.commands and (not "version" in appeal.commands):
                appeal.command()(appeal.version)

        if appeal.support_help:
            if (len(args) == 1) and args[0] in ("-h", "--help"):
                return appeal.help()
            if appeal.commands and (not "help" in appeal.commands):
                appeal.command()(appeal.help)

        if appeal.appeal_preparer:
            # print(f"bind appeal.appeal_preparer to self.appeal={self.appeal}")
            self.preparer(appeal.appeal_preparer.bind(self.appeal))
        if appeal.processor_preparer:
            # print(f"bind appeal.processor_preparer to self={self}")
            self.preparer(appeal.processor_preparer.bind(self))

        appeal.analyze(self)
        appeal.parse(self)
        appeal.convert(self)
        result = self.result = appeal.execute(self)
        self.log_event("process complete")
        if want_prints:
            self.print_log()
        return result

    def main(self, args=None):
        try:
            sys.exit(self(args=args))
        except AppealUsageError as e:
            print("Error:", str(e))
            self.appeal.usage(usage=True)
            sys.exit(-1)
