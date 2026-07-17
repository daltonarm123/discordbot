import os
import unittest
from unittest import mock

from bot import main


class CommandSyncTests(unittest.TestCase):
    def test_test_guild_sync_targets_include_global_and_test_guild(self):
        with mock.patch.dict(os.environ, {"TEST_GUILD_ID": "12345"}, clear=False):
            targets = main.get_command_sync_targets("12345")

        self.assertEqual(targets, [None, 12345])

    def test_no_test_guild_sync_targets_only_global(self):
        targets = main.get_command_sync_targets("")
        self.assertEqual(targets, [None])


if __name__ == "__main__":
    unittest.main()
