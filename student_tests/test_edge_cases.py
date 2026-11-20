from acceptance.base import APICase


class EdgeCaseTests(APICase):
    def test_empty_project_patch_and_summary_query_are_rejected(self):
        project = self.project()
        self.api("PATCH", f'/api/projects/{project["id"]}/', {}, status=400, error="invalid_fields")
        self.api("GET", f'/api/projects/{project["id"]}/summary/', {"page": 1}, status=400, error="invalid_query")

    def test_noop_due_date_patch_does_not_add_history(self):
        project = self.project()
        task = self.task(project, due_date="2030-05-20")
        self.api("PATCH", self.task_url(task), {"due_date": "2030-05-20"})
        self.assertEqual(len(self.events(task)), 1)
        self.assertEqual(self.api("GET", self.task_url(task))["updated_at"], task["updated_at"])
