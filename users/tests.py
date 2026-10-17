from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AuthTests(TestCase):
    def test_first_run_setup_creates_owner_then_closes(self):
        r = self.client.post(reverse("register"), {
            "username": "owner", "email": "o@x.com", "phone_number": "",
            "password1": "S0me-Strong-pass!", "password2": "S0me-Strong-pass!"})
        self.assertRedirects(r, reverse("vendor:dashboard"))
        u = User.objects.get(username="owner")
        self.assertTrue(u.is_staff and u.is_superuser)
        self.client.logout()
        # second visitor can't self-register into the panel
        r = self.client.get(reverse("register"))
        self.assertRedirects(r, reverse("login"))
        r = self.client.post(reverse("register"), {"username": "evil", "password1": "S0me-Strong-pass!", "password2": "S0me-Strong-pass!"})
        self.assertFalse(User.objects.filter(username="evil").exists())

    def test_login_wrong_and_right(self):
        User.objects.create_user("boss", password="pw-12345-x", is_staff=True)
        bad = self.client.post(reverse("login"), {"username": "boss", "password": "nope"})
        self.assertEqual(bad.status_code, 200)
        ok = self.client.post(reverse("login"), {"username": "boss", "password": "pw-12345-x"})
        self.assertRedirects(ok, reverse("vendor:dashboard"))

    def test_login_next_open_redirect_blocked(self):
        User.objects.create_user("boss", password="pw-12345-x", is_staff=True)
        r = self.client.post(reverse("login"), {"username": "boss", "password": "pw-12345-x", "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("vendor:dashboard"))
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "boss", "password": "pw-12345-x", "next": "/vendor/orders/"})
        self.assertRedirects(r, "/vendor/orders/")

    def test_logout_requires_post(self):
        u = User.objects.create_user("c", password="pw-12345-x")
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("profile")).status_code, 302)

    def test_public_pages_render(self):
        for name in ["home", "about", "contact", "products_list", "login"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
