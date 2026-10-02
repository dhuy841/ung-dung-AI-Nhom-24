import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app


class ClubManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(Path(self.temp_dir.name) / "test.db"),
                "AI_API_KEY": "",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/api/login", json={"username": username, "password": password}
        )

    def test_activity_creation_and_member_permission(self):
        self.assertEqual(self.login().status_code, 200)
        created = self.client.post(
            "/api/activities",
            json={"title": "Ngày hội CLB", "starts_at": "2026-11-02T09:00"},
        )
        self.assertEqual(created.status_code, 201)
        self.client.post("/api/logout")
        self.login("member", "member123")
        forbidden = self.client.post("/api/activities", json={"title": "Không được tạo"})
        self.assertEqual(forbidden.status_code, 403)

    def test_startup_removes_legacy_demo_lead_account(self):
        database = Path(self.temp_dir.name) / "test.db"
        db = sqlite3.connect(database)
        try:
            db.execute(
                """INSERT INTO users
                   (username, password_hash, full_name, email, role, department_id)
                   VALUES ('lead', 'unused-hash', 'Demo lead', 'lead@club.local', 'lead', 1)"""
            )
            db.execute(
                "UPDATE tasks SET assigned_to = 3 WHERE title = 'Chuẩn bị nội dung giới thiệu'"
            )
            db.commit()
        finally:
            db.close()
        upgraded_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(database),
                "AI_API_KEY": "",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        upgraded_client = upgraded_app.test_client()
        self.assertEqual(upgraded_client.post("/api/login", json={"username": "admin", "password": "admin123"}).status_code, 200)
        usernames = [user["username"] for user in upgraded_client.get("/api/members").get_json()]
        self.assertCountEqual(usernames, ["admin", "member", "linh", "minh", "trang"])
        task = upgraded_client.get("/api/tasks").get_json()[0]
        self.assertEqual(task["assignee_name"], "Trần Gia Bảo")

    def test_attendance_upserts_and_history_is_available(self):
        self.login()
        activity = self.client.post("/api/activities", json={"title": "Sinh hoạt"})
        activity_id = activity.get_json()["id"]
        member_id = next(
            member["id"]
            for member in self.client.get("/api/members").get_json()
            if member["username"] == "member"
        )
        self.client.post(
            f"/api/activities/{activity_id}/attendance",
            json={"user_id": member_id, "status": "present"},
        )
        updated = self.client.post(
            f"/api/activities/{activity_id}/attendance",
            json={"user_id": member_id, "status": "excused"},
        )
        self.assertEqual(updated.status_code, 200)
        history = self.client.get(f"/api/members/{member_id}/history").get_json()
        updated_attendance = next(item for item in history if item["title"] == "Sinh hoạt")
        self.assertEqual(updated_attendance["attendance_status"], "excused")

    def test_my_activity_history_includes_location_and_own_attendance_only(self):
        self.login("member", "member123")
        history = self.client.get("/api/my-activities")
        self.assertEqual(history.status_code, 200)
        activities = history.get_json()
        orientation = next(item for item in activities if item["title"] == "Buổi định hướng thành viên mới")
        self.assertEqual(orientation["attendance_status"], "present")
        self.assertEqual(orientation["location"], "Hội trường thư viện cũ")
        recruitment = next(item for item in activities if item["title"] == "Ngày hội tuyển thành viên")
        self.assertEqual(recruitment["location"], "Quảng trường ICTU")
        missed = next(item for item in activities if item["title"] == "Workshop kỹ năng truyền thông")
        self.assertEqual(missed["attendance_status"], "absent")
        club_meeting = next(item for item in activities if item["title"] == "Sinh hoạt CLB đầu năm")
        self.assertIsNone(club_meeting["attendance_status"])
        self.assertEqual(club_meeting["location"], "C2.103")

    def test_demo_data_seeding_is_idempotent_and_includes_task_priorities(self):
        self.login()
        first_members = self.client.get("/api/members").get_json()
        first_activities = self.client.get("/api/activities").get_json()
        first_tasks = self.client.get("/api/tasks").get_json()
        self.assertGreaterEqual(len(first_members), 5)
        self.assertGreaterEqual(len(first_activities), 7)
        priorities = {task["priority"] for task in first_tasks}
        self.assertEqual(priorities, {"normal", "important", "urgent"})

        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(Path(self.temp_dir.name) / "test.db"),
                "AI_API_KEY": "",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        self.assertEqual(len(self.client.get("/api/members").get_json()), len(first_members))
        self.assertEqual(len(self.client.get("/api/activities").get_json()), len(first_activities))
        self.assertEqual(len(self.client.get("/api/tasks").get_json()), len(first_tasks))

    def test_task_priority_can_be_created_and_changed_by_manager(self):
        self.login()
        created = self.client.post(
            "/api/tasks",
            json={"title": "Nhiệm vụ khẩn", "priority": "urgent"},
        )
        self.assertEqual(created.status_code, 201)
        task_id = created.get_json()["id"]
        self.assertEqual(
            next(task for task in self.client.get("/api/tasks").get_json() if task["id"] == task_id)["priority"],
            "urgent",
        )
        updated = self.client.patch(
            f"/api/tasks/{task_id}", json={"priority": "important"}
        )
        self.assertEqual(updated.status_code, 200)
        invalid = self.client.patch(
            f"/api/tasks/{task_id}", json={"priority": "whenever"}
        )
        self.assertEqual(invalid.status_code, 400)

    def test_member_can_update_only_own_assigned_task(self):
        self.login("member", "member123")
        self.assertTrue(self.client.get("/api/tasks").get_json())
        self.client.post("/api/logout")
        self.login()
        member_id = next(
            member["id"]
            for member in self.client.get("/api/members").get_json()
            if member["username"] == "member"
        )
        created = self.client.post(
            "/api/tasks", json={"title": "Chuẩn bị sân khấu", "assigned_to": member_id}
        )
        task_id = created.get_json()["id"]
        self.client.post("/api/logout")
        self.login("member", "member123")
        response = self.client.patch(
            f"/api/tasks/{task_id}", json={"status": "in_progress"}
        )
        self.assertEqual(response.status_code, 200)
        tasks = self.client.get("/api/tasks").get_json()
        self.assertEqual(next(task for task in tasks if task["id"] == task_id)["status"], "in_progress")

    def test_each_role_can_update_its_own_profile(self):
        for username, password in (
            ("admin", "admin123"),
            ("member", "member123"),
        ):
            with self.subTest(role=username):
                self.login(username, password)
                response = self.client.patch(
                    "/api/profile", json={"skills": f"new skill {username}"}
                )
                self.assertEqual(response.status_code, 200)
                self.client.post("/api/logout")

    def test_member_profile_update_cannot_change_role_or_username(self):
        self.login("member", "member123")
        response = self.client.patch(
            "/api/profile",
            json={
                "full_name": "Trần Gia Bảo mới",
                "skills": "thiết kế",
                "availability": "buổi tối",
                "department_id": "1",
                "role": "president",
                "username": "other-account",
            },
        )
        self.assertEqual(response.status_code, 200)
        profile = self.client.get("/api/profile").get_json()
        self.assertEqual(profile["full_name"], "Trần Gia Bảo mới")
        self.assertEqual(profile["skills"], "thiết kế")
        self.assertEqual(profile["department_name"], "Truyền thông")
        self.assertEqual(profile["role"], "member")
        self.assertEqual(profile["username"], "member")

    def test_profile_email_must_be_verified_before_replacement(self):
        self.login("member", "member123")
        direct_change = self.client.patch(
            "/api/profile", json={"email": "new-address@example.com"}
        )
        self.assertEqual(direct_change.status_code, 400)
        sent = self.client.post(
            "/api/profile/email/request", json={"email": "new-address@example.com"}
        )
        self.assertEqual(sent.status_code, 200)
        code = self.app.config["TEST_EMAIL_CODES"][-1][2]
        verified = self.client.post(
            "/api/profile/email/verify",
            json={"email": "new-address@example.com", "code": code},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").get_json()["email"], "new-address@example.com")

    def test_profile_password_change_requires_current_password(self):
        self.login("member", "member123")
        rejected = self.client.patch(
            "/api/profile",
            json={"current_password": "wrong-password", "new_password": "new-pass-123"},
        )
        self.assertEqual(rejected.status_code, 400)
        accepted = self.client.patch(
            "/api/profile",
            json={"current_password": "member123", "new_password": "new-pass-123"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.client.post("/api/logout")
        self.assertEqual(self.login("member", "new-pass-123").status_code, 200)

    def test_ai_reports_missing_configuration_and_rejects_missing_input(self):
        self.login()
        missing_input = self.client.post("/api/ai/announcement", json={"activity": " "})
        self.assertEqual(missing_input.status_code, 400)
        unconfigured = self.client.post(
            "/api/ai/announcement",
            json={"activity": "Sinh hoạt CLB ngày 15/10 tại phòng A1"},
        )
        self.assertEqual(unconfigured.status_code, 502)
        self.assertIn("AI_API_KEY", unconfigured.get_json()["error"])

    def test_registration_requires_complete_valid_data_and_verified_email(self):
        incomplete = self.client.post(
            "/api/auth/register",
            json={"full_name": "Nguyen An", "username": "newmember"},
        )
        self.assertEqual(incomplete.status_code, 400)

        requested = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Nguyen An",
                "username": "newmember",
                "email": "newmember@example.com",
                "password": "secure-pass-123",
            },
        )
        self.assertEqual(requested.status_code, 200)
        code = self.app.config["TEST_EMAIL_CODES"][-1][2]
        wrong = self.client.post(
            "/api/auth/register/verify",
            json={"email": "newmember@example.com", "code": "000000" if code != "000000" else "000001"},
        )
        self.assertEqual(wrong.status_code, 400)
        verified = self.client.post(
            "/api/auth/register/verify",
            json={"email": "newmember@example.com", "code": code},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.get_json()["role"], "member")

    def test_admin_created_account_must_verify_email_before_login(self):
        self.login()
        created = self.client.post(
            "/api/members",
            json={
                "full_name": "Le Thu",
                "username": "thu-member",
                "password": "temporary-pass-123",
                "email": "thu@example.com",
                "role": "member",
            },
        )
        self.assertEqual(created.status_code, 201)
        self.client.post("/api/logout")
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"username": "thu-member", "password": "temporary-pass-123"},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/api/profile").status_code, 200)
        code = self.app.config["TEST_EMAIL_CODES"][-1][2]
        verified = self.client.post(
            "/api/profile/verification/confirm", json={"code": code}
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.get_json()["username"], "thu-member")
        self.assertEqual(self.client.get("/api/dashboard").status_code, 200)

    def test_forgot_password_uses_single_use_email_code(self):
        requested = self.client.post(
            "/api/auth/forgot-password", json={"email": "admin@club.local"}
        )
        self.assertEqual(requested.status_code, 200)
        code = self.app.config["TEST_EMAIL_CODES"][-1][2]
        reset = self.client.post(
            "/api/auth/reset-password",
            json={
                "email": "admin@club.local",
                "code": code,
                "new_password": "replacement-pass-123",
            },
        )
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"username": "admin", "password": "replacement-pass-123"},
            ).status_code,
            200,
        )
        replay = self.client.post(
            "/api/auth/reset-password",
            json={
                "email": "admin@club.local",
                "code": code,
                "new_password": "another-password-123",
            },
        )
        self.assertEqual(replay.status_code, 400)


if __name__ == "__main__":
    unittest.main()
