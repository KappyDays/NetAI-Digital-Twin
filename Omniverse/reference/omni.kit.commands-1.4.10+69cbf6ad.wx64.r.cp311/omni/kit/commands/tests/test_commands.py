import carb.settings
import omni.kit.test
import omni.kit.commands
import omni.kit.undo
from functools import partial
from ._kit_command_tests import *

_result = []
_command_tests = None


def setUpModule():
    global _command_tests
    _command_tests = acquire_command_tests()


def tearDownModule():
    global _command_tests
    release_command_tests(_command_tests)
    _command_tests = None


class TestAppendCommand(omni.kit.commands.Command):
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def do(self):
        global _result
        _result.append(self._x)
        _result.append(self._y)

    def undo(self):
        global _result
        del _result[-1]
        del _result[-1]

    def modify_callback_info(self, cb_type, cmd_args):
        if cb_type == omni.kit.commands.PRE_DO_CALLBACK:
            cmd_args['pre_do'] = 1
        elif cb_type == omni.kit.commands.POST_DO_CALLBACK:
            cmd_args['post_do'] = 2
        elif cb_type == omni.kit.commands.PRE_UNDO_CALLBACK:
            cmd_args['pre_undo'] = 3
        elif cb_type == omni.kit.commands.POST_UNDO_CALLBACK:
            cmd_args['post_undo'] = 4
        else:
            cmd_args['other'] = 5
        return cmd_args


class TestAppendNoUndoCommand(omni.kit.commands.Command):
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def do(self):
        global _result
        _result.append(self._x)
        _result.append(self._y)


class TestRaiseException(omni.kit.commands.Command):
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def do(self):
        raise Exception("testing an error happening")

        global _result
        _result.append(self._x)
        _result.append(self._y)


class TestNoBaseCommand:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def do(self):
        global _result
        _result.append(self._x)
        _result.append(self._y)


class TestMissingDoMethod(omni.kit.commands.Command):
    def __init__(self, x, y):
        global _result
        _result.append(x)
        _result.append(y)


class TestCommandParameters(omni.kit.commands.Command):
    """
    TestCommandParameters **Command**.

    Args:
        x: x argument doc
        yy: int: yy argument doc slightly longer
        zzz: zzz argument doc but
             on 2 lines

    More info here.
    """

    def __init__(self, x, yy: int, zzz="some default value"):
        self._x = x
        self._y = yy
        self._z = zzz

    def do(self):
        pass

    def undo(self):
        pass


class TestCommands(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        # Cache the command tests interface.
        global _command_tests
        self.command_tests = _command_tests

        # Disable logging for the time of tests to avoid spewing errors
        omni.kit.commands.set_logging_enabled(False)

        # make sure we are starting from a clean state
        omni.kit.undo.clear_stack()

        # Register all commands
        omni.kit.commands.register(TestAppendCommand)
        omni.kit.commands.register(TestAppendNoUndoCommand)
        omni.kit.commands.register(TestRaiseException)
        omni.kit.commands.register(TestNoBaseCommand)
        omni.kit.commands.register(TestMissingDoMethod)
        omni.kit.commands.register(TestCommandParameters)

    async def tearDown(self):
        # Unregister all commands
        omni.kit.commands.unregister(TestAppendCommand)
        omni.kit.commands.unregister(TestAppendNoUndoCommand)
        omni.kit.commands.unregister(TestRaiseException)
        omni.kit.commands.unregister(TestNoBaseCommand)
        omni.kit.commands.unregister(TestMissingDoMethod)
        omni.kit.commands.unregister(TestCommandParameters)

        omni.kit.commands.set_logging_enabled(True)

        # Clear the command tests interface.
        self.command_tests = None

    async def test_commands(self):
        global _result

        # Execute and undo
        _result = []
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(_result, [1, 2])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

        # Execute and undo command with undo
        _result = []
        undo_stack_len = len(omni.kit.undo.get_undo_stack())
        omni.kit.commands.execute("TestAppendNoUndo", x=1, y=2)
        self.assertListEqual(_result, [1, 2])
        self.assertEqual(undo_stack_len, len(omni.kit.undo.get_undo_stack()))

        # Execute command without base, it should not be registered
        _result = []
        omni.kit.commands.execute("TestNoBase", x=1, y=2)
        self.assertListEqual(_result, [])

        # Unregister -> execution does nothing
        omni.kit.commands.unregister(TestAppendCommand)
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(_result, [])

        # Register twice works fine
        omni.kit.commands.register(TestAppendCommand)
        omni.kit.commands.register(TestAppendCommand)
        omni.kit.commands.execute("omni.kit.builtin.tests.core.test_commands.TestAppendCommand", x=1, y=2)
        self.assertListEqual(_result, [1, 2])

        # Automatically register command from a module
        _result = []
        omni.kit.commands.unregister(TestAppendCommand)
        omni.kit.commands.register_all_commands_in_module(__name__)
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        _result = []
        omni.kit.commands.execute("TestAppendNoUndo", x=1, y=2)
        self.assertListEqual(_result, [1, 2])
        _result = []
        omni.kit.commands.execute("TestNoBase", x=1, y=2)
        self.assertListEqual(_result, [])

    async def test_multiple_calls(self):
        global _result

        # make sure that Undo/Redo work properly when called on multiple commands
        _result = []

        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(_result, [1, 2])
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertListEqual(_result, [1, 2, 3, 4])

        # first call should do actual work and return True
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2])
        self.assertTrue(res)

        # same for second since 2 commands were run
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # third call should do nothing and return False
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertFalse(res)

        # now do the same for Redo
        # first call should do actual work and return True
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2])
        self.assertTrue(res)

        # test undo while there are still commands on the redo stack
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # now redo both of the original commands
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2])
        self.assertTrue(res)

        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        self.assertTrue(res)

        # third call should do nothing and return False
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        self.assertFalse(res)

    def test_group(self):
        global _result

        # Group multiple commands
        _result = []
        omni.kit.undo.begin_group()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.end_group()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

        # Context manager version
        _result = []
        with omni.kit.undo.group():
            omni.kit.commands.execute("TestAppend", x=1, y=2)
            omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

        # Nested groups do nothing different:
        _result = []
        omni.kit.undo.begin_group()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.begin_group()
        omni.kit.commands.execute("TestAppend", x=5, y=6)
        omni.kit.commands.execute("TestAppend", x=7, y=8)
        omni.kit.undo.end_group()
        omni.kit.undo.end_group()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

        # test redo/undo multiple times with groups
        omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

        # Group multiple commands from C++
        _result = []
        self.command_tests.test_begin_undo_group_from_cpp()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.command_tests.test_end_undo_group_from_cpp()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [])

    def test_disabled(self):
        global _result

        # Disable undo
        _result = []
        omni.kit.undo.begin_disabled()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.end_disabled()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])

        # Context manager version
        _result = []
        with omni.kit.undo.disabled():
            omni.kit.commands.execute("TestAppend", x=1, y=2)
            omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.commands.execute("TestAppend", x=5, y=6)
        omni.kit.commands.execute("TestAppend", x=7, y=8)
        omni.kit.undo.undo()
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])

        # Disable undo then enable
        _result = []
        omni.kit.undo.begin_disabled()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.end_disabled()
        omni.kit.commands.execute("TestAppend", x=5, y=6)
        omni.kit.commands.execute("TestAppend", x=7, y=8)
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])

        # Nested calls to disable undo
        _result = []
        omni.kit.undo.begin_disabled()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.begin_disabled()
        omni.kit.commands.execute("TestAppend", x=5, y=6)
        omni.kit.commands.execute("TestAppend", x=7, y=8)
        omni.kit.undo.end_disabled()
        omni.kit.undo.end_disabled()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])

        # Disable undo then enable from C++
        _result = []
        self.command_tests.test_begin_undo_disabled_from_cpp()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.command_tests.test_end_undo_disabled_from_cpp()
        omni.kit.commands.execute("TestAppend", x=5, y=6)
        omni.kit.commands.execute("TestAppend", x=7, y=8)
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6, 7, 8])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4, 5, 6])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])

    async def test_error(self):
        global _result

        # test command raising and exception during `do()`
        _result = []
        res = omni.kit.commands.execute("TestRaiseException", x=1, y=2)
        self.assertEqual(res, (False, None))
        self.assertListEqual(_result, [])

        # test command TypeError exception because `do()` is missing
        _result = [1, 2]
        try:
            omni.kit.commands.execute("TestMissingDoMethod", x=3, y=4)
        except TypeError:
            _result = []
        self.assertListEqual(_result, [])


    async def test_command_parameters(self):
        params = omni.kit.commands.get_command_parameters("TestCommandParameters")

        # test parameters
        self.assertEqual(len(params), 3)
        self.assertEqual(params[0].name, "x")
        self.assertEqual(params[1].name, "yy")
        self.assertEqual(params[2].name, "zzz")
        self.assertEqual(params[0].type_str, "")
        self.assertEqual(params[1].type_str, "int")
        self.assertEqual(params[2].type_str, "")
        self.assertEqual(params[0].default_str, "")
        self.assertEqual(params[1].default_str, "")
        self.assertEqual(params[2].default_str, "some default value")

        # test documentation in parameters
        self.assertEqual(params[0].doc, "x argument doc")
        self.assertEqual(params[1].doc, "yy argument doc slightly longer")
        self.assertEqual(params[2].doc, "zzz argument doc but on 2 lines")

    async def test_callbacks(self):
        self.x = None
        self.y = None
        self.pre_do_count = 0
        self.post_do_count = 0
        self.pre_undo_count = 0
        self.post_undo_count = 0
        self.cmd_specific_pre_do_count = 0
        self.cmd_specific_post_do_count = 0
        self.cmd_specific_pre_undo_count = 0
        self.cmd_specific_post_undo_count = 0
        self.cmd_specific_other_count = 0

        def pre_do_callback(self, info):
            self.pre_do_count += 1
            self.x = info.get('x', None)
            if info.get('pre_do', None):
                self.cmd_specific_pre_do_count += 1
            if info.get('post_do', None):
                self.cmd_specific_post_do_count += 1
            if info.get('pre_undo', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_undo', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('other', None):
                self.cmd_specific_other_count += 1

        def post_do_callback(self, info):
            self.post_do_count += 1
            self.y = info.get('y', None)
            if info.get('pre_do', None):
                self.cmd_specific_pre_do_count += 1
            if info.get('post_do', None):
                self.cmd_specific_post_do_count += 1
            if info.get('pre_undo', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_undo', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('other', None):
                self.cmd_specific_other_count += 1

        def pre_undo_callback(self, info):
            self.pre_undo_count += 1
            self.x = info.get('x', None)
            if info.get('pre_do', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_do', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('pre_undo', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_undo', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('other', None):
                self.cmd_specific_other_count += 1

        def post_undo_callback(self, info):
            self.post_undo_count += 1
            self.y = info.get('y', None)
            if info.get('pre_do', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_do', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('pre_undo', None):
                self.cmd_specific_pre_undo_count += 1
            if info.get('post_undo', None):
                self.cmd_specific_post_undo_count += 1
            if info.get('other', None):
                self.cmd_specific_other_count += 1

        # With no callbacks registered, nothing should change.
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertEqual(self.x, None)
        self.assertEqual(self.y, None)
        self.assertEqual(self.pre_do_count, 0)
        self.assertEqual(self.post_do_count, 0)
        self.assertEqual(self.cmd_specific_pre_do_count, 0)
        self.assertEqual(self.cmd_specific_post_do_count, 0)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With only the pre- callback registered only x, pre_do_count and cmd_specific_pre_do_count should
        # change.
        pre_do_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.PRE_DO_CALLBACK, partial(pre_do_callback, self))

        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertEqual(self.x, 3)
        self.assertEqual(self.y, None)
        self.assertEqual(self.pre_do_count, 1)
        self.assertEqual(self.post_do_count, 0)
        self.assertEqual(self.cmd_specific_pre_do_count, 1)
        self.assertEqual(self.cmd_specific_post_do_count, 0)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With both callbacks registered, everything except cmd_specific_other_count and various *_undo_counts should change.
        post_do_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.POST_DO_CALLBACK, partial(post_do_callback, self))

        omni.kit.commands.execute("TestAppend", x=5, y=6)
        self.assertEqual(self.x, 5)
        self.assertEqual(self.y, 6)
        self.assertEqual(self.pre_do_count, 2)
        self.assertEqual(self.post_do_count, 1)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With callbacks removed, nothing should change.
        omni.kit.commands.unregister_callback(pre_do_cb)
        omni.kit.commands.unregister_callback(post_do_cb)

        omni.kit.commands.execute("TestAppend", x=7, y=8)
        self.assertEqual(self.x, 5)
        self.assertEqual(self.y, 6)
        self.assertEqual(self.pre_do_count, 2)
        self.assertEqual(self.post_do_count, 1)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # TestAppendNoUndoCommand doesn't provide any special callback info
        # so none of the 'specific' data counts should change.
        pre_do_cb = omni.kit.commands.register_callback("TestAppendNoUndoCommand", omni.kit.commands.PRE_DO_CALLBACK, partial(pre_do_callback, self))
        post_do_cb = omni.kit.commands.register_callback("TestAppendNoUndoCommand", omni.kit.commands.POST_DO_CALLBACK, partial(post_do_callback, self))

        omni.kit.commands.execute("TestAppendNoUndoCommand", x=9, y=10)
        self.assertEqual(self.x, 9)
        self.assertEqual(self.y, 10)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        omni.kit.commands.unregister_callback(pre_do_cb)
        omni.kit.commands.unregister_callback(post_do_cb)

        # With no undo callbacks registered, nothing should change.
        omni.kit.undo.undo()
        self.assertEqual(self.x, 9)
        self.assertEqual(self.y, 10)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 0)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 0)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With only the pre-undo callback registered only x, pre_undo_count and cmd_specific_pre_undo_count should change.
        pre_undo_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.PRE_UNDO_CALLBACK, partial(pre_undo_callback, self))

        omni.kit.undo.undo()
        self.assertEqual(self.x, 5)
        self.assertEqual(self.y, 10)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 1)
        self.assertEqual(self.post_undo_count, 0)
        self.assertEqual(self.cmd_specific_pre_undo_count, 1)
        self.assertEqual(self.cmd_specific_post_undo_count, 0)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With both callbacks registered, everything except cmd_specific_other_count and various *_do_counts should change.
        post_undo_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.POST_UNDO_CALLBACK, partial(post_undo_callback, self))

        omni.kit.undo.undo()
        self.assertEqual(self.x, 3)
        self.assertEqual(self.y, 4)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 2)
        self.assertEqual(self.post_undo_count, 1)
        self.assertEqual(self.cmd_specific_pre_undo_count, 2)
        self.assertEqual(self.cmd_specific_post_undo_count, 1)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With callbacks removed, nothing should change.
        omni.kit.commands.unregister_callback(pre_undo_cb)
        omni.kit.commands.unregister_callback(post_undo_cb)

        omni.kit.undo.undo()
        self.assertEqual(self.x, 3)
        self.assertEqual(self.y, 4)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 2)
        self.assertEqual(self.post_undo_count, 1)
        self.assertEqual(self.cmd_specific_pre_undo_count, 2)
        self.assertEqual(self.cmd_specific_post_undo_count, 1)
        self.assertEqual(self.cmd_specific_other_count, 0)

        # With callbacks registered again but nothing left to undo, nothing should change.
        pre_undo_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.PRE_UNDO_CALLBACK, partial(pre_undo_callback, self))
        post_undo_cb = omni.kit.commands.register_callback("TestAppend", omni.kit.commands.POST_UNDO_CALLBACK, partial(post_undo_callback, self))

        omni.kit.undo.undo()
        self.assertEqual(self.x, 3)
        self.assertEqual(self.y, 4)
        self.assertEqual(self.pre_do_count, 3)
        self.assertEqual(self.post_do_count, 2)
        self.assertEqual(self.cmd_specific_pre_do_count, 2)
        self.assertEqual(self.cmd_specific_post_do_count, 1)
        self.assertEqual(self.pre_undo_count, 2)
        self.assertEqual(self.post_undo_count, 1)
        self.assertEqual(self.cmd_specific_pre_undo_count, 2)
        self.assertEqual(self.cmd_specific_post_undo_count, 1)
        self.assertEqual(self.cmd_specific_other_count, 0)

    async def test_subscribe_on_undo_stack_change(self):
        self.command_names = []
        self.command_entries = []

        def on_undo_stack_change(command_names):
            self.command_names += command_names

        def on_undo_stack_change_detailed(command_entries):
            self.command_entries += command_entries

        # Execute a command before subscribing to on_change callbacks.
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(self.command_names, [])
        self.assertListEqual(self.command_entries, [])

        # Subscribe to on_change callbacks.
        omni.kit.undo.subscribe_on_change(on_undo_stack_change)
        omni.kit.undo.subscribe_on_change_detailed(on_undo_stack_change_detailed)

        # Execute a command.
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(self.command_names, ["TestAppend"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[0].level, 0)
        self.assertEqual(self.command_entries[0].error, False)

        # Undo the command.
        self.command_names = []
        self.command_entries = []
        omni.kit.undo.undo()
        self.assertListEqual(self.command_names, ["TestAppend"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[0].level, 0)
        self.assertEqual(self.command_entries[0].error, False)

        # Redo the command.
        self.command_names = []
        self.command_entries = []
        omni.kit.undo.redo()
        self.assertListEqual(self.command_names, ["TestAppend"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[0].level, 0)
        self.assertEqual(self.command_entries[0].error, False)

        # Group multiple commands
        omni.kit.undo.begin_group()

        self.command_names = []
        self.command_entries = []
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(self.command_names, ["TestAppend"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[0].level, 1)
        self.assertEqual(self.command_entries[0].error, False)

        self.command_names = []
        self.command_entries = []
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        self.assertListEqual(self.command_names, ["TestAppend"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":3, "y":4})
        self.assertEqual(self.command_entries[0].level, 1)
        self.assertEqual(self.command_entries[0].error, False)

        self.command_names = []
        self.command_entries = []
        omni.kit.undo.end_group()
        self.assertListEqual(self.command_names, ["Group"])
        self.assertEqual(len(self.command_entries), 1)
        self.assertEqual(self.command_entries[0].name, "Group")
        self.assertDictEqual(self.command_entries[0].kwargs, {})
        self.assertEqual(self.command_entries[0].level, 0)
        self.assertEqual(self.command_entries[0].error, False)

        # Undo the grouped commands (the callback will only be invoked once for the whole group).
        self.command_names = []
        self.command_entries = []
        omni.kit.undo.undo()
        self.assertListEqual(self.command_names, ["TestAppend", "TestAppend", "Group"])

        self.assertEqual(len(self.command_entries), 3)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":3, "y":4})
        self.assertEqual(self.command_entries[0].level, 1)
        self.assertEqual(self.command_entries[0].error, False)

        self.assertEqual(self.command_entries[1].name, "TestAppend")
        self.assertDictEqual(self.command_entries[1].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[1].level, 1)
        self.assertEqual(self.command_entries[1].error, False)

        self.assertEqual(self.command_entries[2].name, "Group")
        self.assertDictEqual(self.command_entries[2].kwargs, {})
        self.assertEqual(self.command_entries[2].level, 0)
        self.assertEqual(self.command_entries[2].error, False)

        # Redo the grouped commands (the callback will be invoked once for each command being redone).
        self.command_names = []
        self.command_entries = []
        omni.kit.undo.redo()
        self.assertListEqual(self.command_names, ["TestAppend", "TestAppend", "Group"])

        self.assertEqual(len(self.command_entries), 3)
        self.assertEqual(self.command_entries[0].name, "TestAppend")
        self.assertDictEqual(self.command_entries[0].kwargs, {"x":1, "y":2})
        self.assertEqual(self.command_entries[0].level, 1)
        self.assertEqual(self.command_entries[0].error, False)

        self.assertEqual(self.command_entries[1].name, "TestAppend")
        self.assertDictEqual(self.command_entries[1].kwargs, {"x":3, "y":4})
        self.assertEqual(self.command_entries[1].level, 1)
        self.assertEqual(self.command_entries[1].error, False)

        self.assertEqual(self.command_entries[2].name, "Group")
        self.assertDictEqual(self.command_entries[2].kwargs, {})
        self.assertEqual(self.command_entries[2].level, 0)
        self.assertEqual(self.command_entries[2].error, False)

        # Unsubscribe from on_change callbacks.
        omni.kit.undo.unsubscribe_on_change_detailed(on_undo_stack_change_detailed)
        omni.kit.undo.unsubscribe_on_change(on_undo_stack_change)

    async def test_cpp_commands(self):
        global _result
        _result = []

        # Give the C++ test code access to the global test result list
        self.command_tests.set_test_result_list(_result)

        # Register a new command type from C++
        self.command_tests.test_register_cpp_command("omni.kit.command_tests", "TestCppAppendCommand")

        # Execute the C++ command from Python
        res = omni.kit.commands.execute("TestCppAppend", x=7, y=9)
        self.assertListEqual(_result, [7, 9])
        self.assertEqual(res, (True, None))

        # Undo the C++ command from C++
        res = self.command_tests.test_undo_command_from_cpp()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # Redo the C++ command from Python
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [7, 9])
        self.assertTrue(res)

        # Execute the C++ command from C++
        res = self.command_tests.test_execute_command_from_cpp("TestCppAppend", x=99, y=0)
        self.assertListEqual(_result, [7, 9, 99, 0])
        self.assertTrue(res)

        # Undo the C++ command from Python
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [7,9])
        self.assertTrue(res)

        # Execute the C++ command from C++ with a default argument
        res = self.command_tests.test_execute_command_from_cpp("TestCppAppend", x=99)
        self.assertListEqual(_result, [7, 9, 99, -1])
        self.assertTrue(res)

        # Execute the C++ command from Python with a default argument
        res = omni.kit.commands.execute("TestCppAppend", y=-9)
        self.assertListEqual(_result, [7, 9, 99, -1, 9, -9])
        self.assertEqual(res, (True, None))

        # Undo the C++ command from C++
        res = self.command_tests.test_undo_command_from_cpp()
        self.assertListEqual(_result, [7, 9, 99, -1])
        self.assertTrue(res)

        # Undo the C++ command from Python
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [7,9])
        self.assertTrue(res)

        # Execute an existng Python command from C++
        res = self.command_tests.test_execute_command_from_cpp("TestAppend", x=1, y=2)
        self.assertListEqual(_result, [7, 9, 1, 2])
        self.assertTrue(res)

        # Undo the Python command from C++
        res = self.command_tests.test_undo_command_from_cpp()
        self.assertListEqual(_result, [7,9])
        self.assertTrue(res)

        # Redo the Python command from C++
        res = self.command_tests.test_redo_command_from_cpp()
        self.assertListEqual(_result, [7,9, 1, 2])
        self.assertTrue(res)

        # Undo the Python command from Python
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [7,9])
        self.assertTrue(res)

        # Deregister the C++ command from C++
        self.command_tests.test_deregister_cpp_command("omni.kit.command_tests", "TestCppAppendCommand")

        # Undo the C++ command from Python after it has been deregistered
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # Execute the C++ command from C++ after it has been deregistered (does nothing)
        res = self.command_tests.test_execute_command_from_cpp("TestCppAppend", x=10, y=20)
        self.assertListEqual(_result, [])
        self.assertFalse(res)

        # Execute the C++ command from Python after it has been deregistered (does nothing)
        res = omni.kit.commands.execute("TestCppAppend", x=10, y=20)
        self.assertListEqual(_result, [])
        self.assertEqual(res, (False, None))

        # Redo the C++ command from C++ after it has been deregistered
        res = self.command_tests.test_redo_command_from_cpp()
        self.assertListEqual(_result, [7, 9])
        self.assertTrue(res)

        # Undo the C++ command from C++ after it has been deregistered
        res = self.command_tests.test_undo_command_from_cpp()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # Release the C++ reference to the global test result list
        self.command_tests.clear_test_result_list()

    def test_repeat(self):
        global _result
        _result = []

        # Execute a command
        res = omni.kit.commands.execute("TestAppend", x=1, y=2)
        self.assertListEqual(_result, [1, 2])
        self.assertEqual(res, (True, None))

        # Repeat the command
        res = omni.kit.undo.repeat()
        self.assertListEqual(_result, [1, 2, 1, 2])
        self.assertTrue(res)

        # Undo the repeated command
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2])
        self.assertTrue(res)

        # Redo the repeated command
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 1, 2])
        self.assertTrue(res)

        # Repeat the command from C++
        res = self.command_tests.test_repeat_command_from_cpp()
        self.assertListEqual(_result, [1, 2, 1, 2, 1, 2])
        self.assertTrue(res)

        # Undo the repeated and original commands
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 1, 2])
        self.assertTrue(res)
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2])
        self.assertTrue(res)
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

        # Group multiple commands
        omni.kit.undo.begin_group()
        omni.kit.commands.execute("TestAppend", x=1, y=2)
        omni.kit.commands.execute("TestAppend", x=3, y=4)
        omni.kit.undo.end_group()
        self.assertListEqual(_result, [1, 2, 3, 4])

        # Repeat the grouped commands
        res = omni.kit.undo.repeat()
        self.assertListEqual(_result, [1, 2, 3, 4, 1, 2, 3, 4])
        self.assertTrue(res)

        # Undo the repeated grouped commands
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        self.assertTrue(res)

        # Redo the repeated grouped commands
        res = omni.kit.undo.redo()
        self.assertListEqual(_result, [1, 2, 3, 4, 1, 2, 3, 4])
        self.assertTrue(res)

        # Repeat the grouped commands from C++
        res = self.command_tests.test_repeat_command_from_cpp()
        self.assertListEqual(_result, [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4])
        self.assertTrue(res)

        # Undo the repeated and original grouped commands
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4, 1, 2, 3, 4])
        self.assertTrue(res)
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [1, 2, 3, 4])
        self.assertTrue(res)
        res = omni.kit.undo.undo()
        self.assertListEqual(_result, [])
        self.assertTrue(res)

    def test_change_setting_command(self):
        # Set the default value of our draggable setting
        test_setting_default_value = -1
        test_setting_path = "/test/some/setting"
        settings = carb.settings.get_settings()
        settings.set_default(test_setting_path, test_setting_default_value)
        self.assertEqual(settings.get(test_setting_path), test_setting_default_value)

        # Execute a change setting command
        test_setting_new_value = 9
        res = omni.kit.commands.execute("ChangeSetting", path=test_setting_path, value=test_setting_new_value)
        self.assertEqual(settings.get(test_setting_path), test_setting_new_value)

        # Verify that undoing the change setting command resets the setting to the default value
        omni.kit.undo.undo()
        self.assertEqual(settings.get(test_setting_path), test_setting_default_value)

    def test_change_draggable_setting_command(self):
        # Set the default value of our draggable setting
        test_draggable_setting_default_value = -1
        test_draggable_setting_path = "/test/draggable/setting"
        settings = carb.settings.get_settings()
        settings.set_default(test_draggable_setting_path, test_draggable_setting_default_value)
        self.assertEqual(settings.get(test_draggable_setting_path), test_draggable_setting_default_value)

        # Execute a change draggable setting command
        test_draggable_setting_new_value = 9
        res = omni.kit.commands.execute("ChangeDraggableSetting", path=test_draggable_setting_path, value=test_draggable_setting_new_value)
        self.assertEqual(settings.get(test_draggable_setting_path), test_draggable_setting_new_value)

        # Verify that undoing the change draggable setting command does nothing
        omni.kit.undo.undo()
        self.assertEqual(settings.get(test_draggable_setting_path), test_draggable_setting_new_value)

    def test_last_command(self):
        # Set the current and default values of a test setting
        test_setting_default_value = -1
        test_setting_path = "/test/some/setting"
        settings = carb.settings.get_settings()
        settings.set(test_setting_path, test_setting_default_value)
        settings.set_default(test_setting_path, test_setting_default_value)
        self.assertEqual(settings.get(test_setting_path), test_setting_default_value)

        # Execute a change draggable setting command
        test_setting_new_value = 9
        res = omni.kit.commands.execute("ChangeDraggableSetting", path=test_setting_path, value=test_setting_new_value)
        self.assertEqual(settings.get(test_setting_path), test_setting_new_value)

        # Verify that the 'last command' was set
        last_command_setting_path = "/crashreporter/data/lastCommand"
        last_command = settings.get(last_command_setting_path)
        self.assertEqual(last_command, "ChangeDraggableSetting(path=/test/some/setting,value=9)")

        # Execute a change setting command
        test_setting_new_value = 99
        res = omni.kit.commands.execute("ChangeSetting", path=test_setting_path, value=test_setting_new_value)
        self.assertEqual(settings.get(test_setting_path), test_setting_new_value)

        # Verify that the 'last command' was set
        last_command = settings.get(last_command_setting_path)
        self.assertEqual(last_command, "ChangeSetting(path=/test/some/setting,value=99)")
