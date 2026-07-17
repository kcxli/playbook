from __future__ import annotations

import unittest
from unittest.mock import Mock

from playbook_runner.engine import Engine
from playbook_runner.parser import Step


class EmailHandlerTests(unittest.TestCase):
    def test_email_link_delegates_to_injected_mailbox_broker(self) -> None:
        requests = []

        def handler(kind, config, started_at):
            requests.append((kind, config, started_at))
            return "https://jobs.example.edu/verify?token=abc"

        engine = Engine(
            {"account": {"generated_email": "person+px123@gmail.com"}},
            email_handler=handler,
        )
        engine.page = Mock()
        engine._settle = Mock()

        engine._do_await_email_link(
            Step(
                kind="await_email_link",
                config={
                    "subject": "Verify {{ account.generated_email }}",
                    "link_pattern": r"https://jobs\.example\.edu/verify\?\S+",
                },
            )
        )

        self.assertEqual(requests[0][0], "link")
        self.assertEqual(
            requests[0][1]["subject"],
            "Verify person+px123@gmail.com",
        )
        engine.page.goto.assert_called_once_with(
            "https://jobs.example.edu/verify?token=abc"
        )

    def test_email_code_delegates_without_logging_the_code(self) -> None:
        logs = []
        control = Mock()
        engine = Engine(
            {},
            email_handler=lambda _kind, _config, _started_at: "482913",
            log=logs.append,
        )
        engine._control = Mock(return_value=control)

        engine._do_await_email_code(
            Step(
                kind="await_email_code",
                config={"field": "Security code", "code_pattern": r"\d{6}"},
            )
        )

        control.fill.assert_called_once_with("482913")
        self.assertNotIn("482913", " ".join(logs))


if __name__ == "__main__":
    unittest.main()
