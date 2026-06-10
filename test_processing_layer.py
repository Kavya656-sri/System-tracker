import unittest

from activity_store import normalize_project_name_for_storage, normalize_task_name_for_storage


class ProcessingLayerTests(unittest.TestCase):

    def test_email_sender_and_browser_support_group_to_email_automation(self):
        self.assertEqual(
            normalize_task_name_for_storage(
                "Productivity Tracker",
                "email_sender.py - Productivity Tracker - Visual Studio Code",
                "email_sender.py",
                "",
            ),
            "Email Automation Module",
        )
        self.assertEqual(
            normalize_task_name_for_storage(
                "Productivity Tracker",
                "Inbox - Google Chrome",
                "email_sender.py",
                "",
            ),
            "Email Automation Module",
        )

    def test_email_verification_grouping(self):
        self.assertEqual(
            normalize_task_name_for_storage(
                "Productivity Tracker",
                "Email Verification - Microsoft Edge",
                "email_verification.html",
                "",
            ),
            "Email Verification Module",
        )

    def test_auto_start_feature_grouping(self):
        self.assertEqual(
            normalize_task_name_for_storage(
                "Productivity Tracker",
                "Task Scheduler Auto Start - Google Chrome",
                "Task Scheduler Auto Start - Google Chrome",
                "",
            ),
            "Auto Start Feature",
        )

    def test_system_activity_stays_unassigned(self):
        self.assertEqual(
            normalize_project_name_for_storage("Other", "Snipping Tool Overlay", ""),
            "Unassigned Activities",
        )
        self.assertEqual(
            normalize_task_name_for_storage("Other", "Search", "Search", ""),
            "Search",
        )


if __name__ == "__main__":
    unittest.main()
