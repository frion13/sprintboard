from datetime import date
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from core.http import APIError, body, endpoint, no_content, page, positive_id, query, text
from .models import Project, Membership, Task, Comment, HistoryEvent

STATUSES = {"todo", "in_progress", "review", "done"}
PRIORITIES = {"low", "medium", "high"}
TRANSITIONS = {"todo": {"in_progress"}, "in_progress": {"todo", "review"}, "review": {"in_progress", "done"}, "done": {"todo"}}

def project_data(p):
    return {"id": p.pk, "name": p.name, "description": p.description, "owner_id": p.owner_id, "archived": p.archived, "created_at": p.created_at.isoformat()}
def member_data(m):
    return {"id": m.user_id, "username": m.user.username, "role": "owner" if m.user_id == m.project.owner_id else "member"}
def task_data(t):
    return {"id": t.pk, "project_id": t.project_id, "title": t.title, "description": t.description, "reporter_id": t.reporter_id, "assignee_id": t.assignee_id, "priority": t.priority, "status": t.status, "due_date": t.due_date.isoformat() if t.due_date else None, "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat()}
def comment_data(c):
    return {"id": c.pk, "task_id": c.task_id, "author_id": c.author_id, "text": c.text, "created_at": c.created_at.isoformat()}
def event_data(e):
    return {"id": e.pk, "task_id": e.task_id, "actor_id": e.actor_id, "kind": e.kind, "data": e.data, "created_at": e.created_at.isoformat()}

def get_project(request, project_id):
    try: p = Project.objects.get(pk=positive_id(project_id))
    except (Project.DoesNotExist, APIError): raise APIError("not_found", 404)
    if not Membership.objects.filter(project=p, user=request.user).exists(): raise APIError("not_found", 404)
    return p
def owner_required(request, p):
    if p.owner_id != request.user.pk: raise APIError("forbidden", 403)
def active_project(p):
    if p.archived: raise APIError("project_archived", 409)
def get_task(request, task_id):
    try: t = Task.objects.select_related("project").get(pk=positive_id(task_id))
    except (Task.DoesNotExist, APIError): raise APIError("not_found", 404)
    if not Membership.objects.filter(project=t.project, user=request.user).exists(): raise APIError("not_found", 404)
    return t
def parse_date(value):
    if value is None: return None
    if not isinstance(value, str) or len(value) != 10: raise APIError("invalid_value")
    try: return date.fromisoformat(value)
    except ValueError: raise APIError("invalid_value")
def assignee(value, p):
    if value is None: return None
    positive_id(value)
    if not Membership.objects.filter(project=p, user_id=value).exists(): raise APIError("invalid_assignee")
    return value
def create_event(t, actor, kind, data): return HistoryEvent.objects.create(task=t, actor=actor, kind=kind, data=data)

@endpoint("GET", "POST")
def projects(request):
    if request.method == "GET":
        query(request); return page(request, Project.objects.filter(memberships__user=request.user).order_by("-created_at", "-id"), project_data)
    data = body(request, {"name", "description"}, {"name"}); name = text(data["name"], 100); description = text(data.get("description", ""), 2000, blank=True)
    with transaction.atomic():
        p = Project.objects.create(name=name, description=description, owner=request.user); Membership.objects.create(project=p, user=request.user)
    return JsonResponse(project_data(p), status=201)

@endpoint("GET", "PATCH")
def project_detail(request, project_id):
    p = get_project(request, project_id)
    if request.method == "GET": return JsonResponse(project_data(p))
    owner_required(request, p); data = body(request, {"name", "description", "archived"})
    if not data: raise APIError("invalid_fields")
    if "name" in data: data["name"] = text(data["name"], 100)
    if "description" in data: data["description"] = text(data["description"], 2000, blank=True)
    if "archived" in data and type(data["archived"]) is not bool: raise APIError("invalid_value")
    for key, value in data.items(): setattr(p, key, value)
    p.save(); return JsonResponse(project_data(p))

@endpoint("GET", "POST")
def members(request, project_id):
    p = get_project(request, project_id)
    if request.method == "GET":
        query(request); return page(request, p.memberships.select_related("user").order_by("user_id"), member_data)
    owner_required(request, p); active_project(p); data = body(request, {"username"}, {"username"})
    if not isinstance(data["username"], str): raise APIError("invalid_value")
    try: user = User.objects.get(username=data["username"])
    except User.DoesNotExist: raise APIError("user_not_found", 404)
    if Membership.objects.filter(project=p, user=user).exists(): raise APIError("membership_exists", 409)
    return JsonResponse(member_data(Membership.objects.create(project=p, user=user)), status=201)

@endpoint("DELETE")
def member_detail(request, project_id, user_id):
    p = get_project(request, project_id); owner_required(request, p); active_project(p)
    try: m = Membership.objects.select_related("user").get(project=p, user_id=positive_id(user_id))
    except (Membership.DoesNotExist, APIError): raise APIError("not_found", 404)
    if m.user_id == p.owner_id: raise APIError("owner_required", 409)
    if Task.objects.filter(project=p, assignee_id=m.user_id).exists(): raise APIError("member_in_use", 409)
    m.delete(); return no_content()

def validate_task_data(data, p, partial=False):
    if partial and not data: raise APIError("invalid_fields")
    if "title" in data: data["title"] = text(data["title"], 200)
    if "description" in data: data["description"] = text(data["description"], 10000, blank=True)
    if "priority" in data and (not isinstance(data["priority"], str) or data["priority"] not in PRIORITIES): raise APIError("invalid_value")
    if "assignee_id" in data: data["assignee_id"] = assignee(data["assignee_id"], p)
    if "due_date" in data: data["due_date"] = parse_date(data["due_date"])
    return data

@endpoint("GET", "POST")
def tasks(request, project_id):
    p = get_project(request, project_id)
    if request.method == "GET":
        query(request, {"status", "priority", "assignee_id", "q", "overdue"}); qs = p.tasks.all().order_by("-created_at", "-id")
        if "status" in request.GET and request.GET["status"] not in STATUSES: raise APIError("invalid_query")
        if "priority" in request.GET and request.GET["priority"] not in PRIORITIES: raise APIError("invalid_query")
        if "assignee_id" in request.GET:
            raw = request.GET["assignee_id"]
            if not raw.isascii() or not raw.isdecimal() or len(raw) > 9 or int(raw) < 1: raise APIError("invalid_query")
            qs = qs.filter(assignee_id=int(raw))
        if "q" in request.GET:
            q = request.GET["q"].strip()
            if not q or len(q) > 200: raise APIError("invalid_query")
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
        if "overdue" in request.GET:
            if request.GET["overdue"] not in {"true", "false"}: raise APIError("invalid_query")
            overdue = Q(due_date__lt=timezone.localdate()) & ~Q(status="done")
            qs = qs.filter(overdue if request.GET["overdue"] == "true" else ~overdue)
        if "status" in request.GET: qs = qs.filter(status=request.GET["status"])
        if "priority" in request.GET: qs = qs.filter(priority=request.GET["priority"])
        return page(request, qs, task_data)
    active_project(p); data = body(request, {"title", "description", "priority", "assignee_id", "due_date"}, {"title"}); data = validate_task_data(data, p)
    data.setdefault("description", ""); data.setdefault("priority", "medium"); data.setdefault("assignee_id", None); data.setdefault("due_date", None)
    with transaction.atomic():
        t = Task.objects.create(project=p, reporter=request.user, **data); create_event(t, request.user, "task_created", {})
    return JsonResponse(task_data(t), status=201)

@endpoint("GET")
def summary(request, project_id):
    p = get_project(request, project_id)
    if request.GET: raise APIError("invalid_query")
    qs = p.tasks.all(); statuses = ("todo", "in_progress", "review", "done")
    return JsonResponse({"total": qs.count(), "by_status": {s: qs.filter(status=s).count() for s in statuses}, "overdue": qs.filter(due_date__lt=timezone.localdate()).exclude(status="done").count()})

@endpoint("GET", "PATCH", "DELETE")
def task_detail(request, task_id):
    t = get_task(request, task_id)
    if request.method == "GET": return JsonResponse(task_data(t))
    if request.method == "DELETE":
        if request.user.pk not in {t.project.owner_id, t.reporter_id}: raise APIError("forbidden", 403)
        active_project(t.project)
        t.delete(); return no_content()
    active_project(t.project); data = validate_task_data(body(request, {"title", "description", "priority", "assignee_id", "due_date"}), t.project, True); changes = {}
    for key, value in data.items():
        old = getattr(t, key); old_value = old.isoformat() if isinstance(old, date) else old; new_value = value.isoformat() if isinstance(value, date) else value
        if old_value != new_value:
            changes[key] = {"old": old_value, "new": new_value}; setattr(t, key, value)
    if changes:
        with transaction.atomic(): t.save(); create_event(t, request.user, "task_updated", {"changes": changes})
    return JsonResponse(task_data(t))

@endpoint("POST")
def transition(request, task_id):
    t = get_task(request, task_id); active_project(t.project); data = body(request, {"status"}, {"status"})
    if not isinstance(data["status"], str) or data["status"] not in STATUSES: raise APIError("invalid_value")
    if data["status"] not in TRANSITIONS[t.status]: raise APIError("invalid_transition", 409)
    old = t.status
    with transaction.atomic():
        t.status = data["status"]; t.save(update_fields=["status", "updated_at"]); create_event(t, request.user, "status_changed", {"from": old, "to": data["status"]})
    return JsonResponse(task_data(t))

@endpoint("GET", "POST")
def comments(request, task_id):
    t = get_task(request, task_id)
    if request.method == "GET": query(request); return page(request, t.comments.all().order_by("created_at", "id"), comment_data)
    active_project(t.project); data = body(request, {"text"}, {"text"}); value = text(data["text"], 2000)
    with transaction.atomic(): c = Comment.objects.create(task=t, author=request.user, text=value); create_event(t, request.user, "comment_added", {"comment_id": c.pk})
    return JsonResponse(comment_data(c), status=201)

@endpoint("GET")
def history(request, task_id):
    t = get_task(request, task_id); query(request); return page(request, t.history.all().order_by("created_at", "id"), event_data)
