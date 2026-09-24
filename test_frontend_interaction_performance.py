import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class FrontendInteractionPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ux = (ROOT / "ux.js").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_draft_capture_is_deferred_out_of_input_handler(self):
        self.assertIn("overlay.addEventListener('input',scheduleCapture)", self.ux)
        self.assertIn("requestIdleCallback", self.ux)
        self.assertNotIn("overlay.addEventListener('input',capture)", self.ux)

    def test_conflict_preview_does_not_fetch_remote_weeks(self):
        marker = "function attachConflictPreview"
        section = self.ux[self.ux.index(marker):]
        section = section[:section.index("// The single-event action")]
        self.assertIn("cachedWeekSchedule(key)", section)
        self.assertNotIn("fetchWeekSchedule(", section)

    def test_payment_toggle_is_single_click_and_optimistic(self):
        group = self.app[self.app.index("async function setGroupMemberPaidState"):]
        group = group[:group.index("function closeActionMenu")]
        self.assertNotIn("confirm(", group)
        self.assertLess(group.index("applyReturnedLesson("), group.index("apiFetch('/mark_paid'"))

        direct = self.app[self.app.index("document.getElementById('btn-action-paid').onclick"):]
        direct = direct[:direct.index("document.getElementById('btn-action-subscription').onclick")]
        self.assertNotIn("confirm(", direct)
        self.assertLess(direct.index("applyReturnedLesson("), direct.index("apiFetch('/mark_paid'"))

        finance = self.app[self.app.index("async function changeStudentLessonPayment"):]
        finance = finance[:finance.index("let inviteView")]
        self.assertIn("descriptions[action] && !confirm", finance)
        self.assertNotIn("direct: 'Отметить занятие оплаченным'", finance)
        self.assertNotIn("reverse: 'Снять оплату'", finance)


if __name__ == "__main__":
    unittest.main()
