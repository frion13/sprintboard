from django.contrib.auth.models import User
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=2000, default="")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_projects")
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Membership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="project_memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "user"), name="unique_project_member")]


class Task(models.Model):
    PRIORITIES = [("low", "low"), ("medium", "medium"), ("high", "high")]
    STATUSES = [("todo", "todo"), ("in_progress", "in_progress"), ("review", "review"), ("done", "done")]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(default="")
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reported_tasks")
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tasks")
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="medium")
    status = models.CharField(max_length=15, choices=STATUSES, default="todo")
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Comment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    text = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)


class HistoryEvent(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="history_events")
    kind = models.CharField(max_length=30)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
