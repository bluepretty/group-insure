# Stage 3 — Member Enrollment

- [ ] Create Member model (members table)
- [ ] Register Member in app/models/__init__.py
- [ ] Extend RBAC permissions (view_members, manage_members)
- [ ] Create service (members.py): list, get, enroll, terminate
- [ ] Create products.py service if missing (referenced in plan)
- [ ] Create API (members.py): JSON list, list partial, enroll, terminate
- [ ] Wire router into main.py
- [ ] Create template (partials/member_list.html)
- [ ] Update dashboard nav (Enrollment link)
- [ ] Extend smoke test (enroll, list, terminate, broker 403)
- [ ] Run smoke test & fix issues
- [ ] Commit
