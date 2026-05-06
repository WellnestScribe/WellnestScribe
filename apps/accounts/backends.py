"""Authentication backend that accepts either username or email."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Allow `username` field on the login form to be either a username or
    an email. Case-insensitive on email, case-insensitive on username only
    if no exact match exists.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        UserModel = get_user_model()
        user = None
        if "@" in username:
            try:
                user = UserModel.objects.get(email__iexact=username)
            except UserModel.DoesNotExist:
                user = None
        if user is None:
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist:
                try:
                    user = UserModel.objects.get(username__iexact=username)
                except UserModel.DoesNotExist:
                    return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
