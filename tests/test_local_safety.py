"""Static checks for local safety controls. Does not run the remote application."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "app.py"

def method(tree, class_name, method_name):
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)

def calls(node, name):
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == name]

class LocalSafetyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    def test_no_automatic_receiving_at_start(self):
        self.assertFalse(calls(method(self.tree, "App", "__init__"), "start"))

    def test_local_activation_has_confirmation(self):
        node = method(self.tree, "App", "enable_local_support")
        self.assertTrue(calls(node, "askyesno"))
        self.assertTrue(calls(node, "start"))

    def test_emergency_exit_closes_window(self):
        self.assertTrue(calls(method(self.tree, "App", "emergency_exit"), "destroy"))

    def test_visible_indicator_checks_authenticated_channels(self):
        node = method(self.tree, "App", "_refresh_access_indicator")
        self.assertTrue(calls(node, "active_channel_count"))
        self.assertTrue(calls(node, "set"))
        self.assertTrue(calls(node, "after"))

    def test_channel_cleanup_is_in_finally(self):
        node = method(self.tree, "Host", "_run_handler")
        self.assertTrue(any(isinstance(n, ast.Try) and n.finalbody for n in ast.walk(node)))
        self.assertTrue(calls(node, "discard"))

if __name__ == "__main__":
    unittest.main()
