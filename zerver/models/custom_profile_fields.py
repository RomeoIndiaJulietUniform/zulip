from typing import Any, Callable, Dict, List, Tuple

import orjson
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CASCADE, QuerySet
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_stubs_ext import StrPromise
from typing_extensions import override

from zerver.lib.types import (
    ExtendedFieldElement,
    ExtendedValidator,
    FieldElement,
    ProfileDataElementBase,
    ProfileDataElementValue,
    RealmUserValidator,
    UserFieldElement,
    Validator,
)
from zerver.lib.validator import (
    check_date,
    check_int,
    check_list,
    check_long_string,
    check_short_string,
    check_url,
    validate_select_field,
)
from zerver.models.realms import Realm
from zerver.models.users import UserProfile, get_user_profile_by_id_in_realm


def check_valid_user_ids(realm_id: int, val: object, allow_deactivated: bool = False) -> List[int]:
    user_ids = check_list(check_int)("User IDs", val)
    realm = Realm.objects.get(id=realm_id)
    for user_id in user_ids:
        # TODO: Structurally, we should be doing a bulk fetch query to
        # get the users here, not doing these in a loop.  But because
        # this is a rarely used feature and likely to never have more
        # than a handful of users, it's probably mostly OK.
        try:
            user_profile = get_user_profile_by_id_in_realm(user_id, realm)
        except UserProfile.DoesNotExist:
            raise ValidationError(_("Invalid user ID: {user_id}").format(user_id=user_id))

        if not allow_deactivated and not user_profile.is_active:
            raise ValidationError(
                _("User with ID {user_id} is deactivated").format(user_id=user_id)
            )

        if user_profile.is_bot:
            raise ValidationError(_("User with ID {user_id} is a bot").format(user_id=user_id))

    return user_ids


class CustomProfileField(models.Model):
    """Defines a form field for the per-realm custom profile fields feature.

    See CustomProfileFieldValue for an individual user's values for one of
    these fields.
    """

    HINT_MAX_LENGTH = 80
    NAME_MAX_LENGTH = 40
    MAX_DISPLAY_IN_PROFILE_SUMMARY_FIELDS = 2

    realm = models.ForeignKey(Realm, on_delete=CASCADE)
    name = models.CharField(max_length=NAME_MAX_LENGTH)
    hint = models.CharField(max_length=HINT_MAX_LENGTH, default="")

    # Sort order for display of custom profile fields.
    order = models.IntegerField(default=0)

    # Whether the field should be displayed in smaller summary
    # sections of a page displaying custom profile fields.
    display_in_profile_summary = models.BooleanField(default=False)

    SHORT_TEXT = 1
    LONG_TEXT = 2
    SELECT = 3
    DATE = 4
    URL = 5
    USER = 6
    EXTERNAL_ACCOUNT = 7
    PRONOUNS = 8

    # These are the fields whose validators require more than var_name
    # and value argument. i.e. SELECT require field_data, USER require
    # realm as argument.
    SELECT_FIELD_TYPE_DATA: List[ExtendedFieldElement] = [
        (SELECT, gettext_lazy("List of options"), validate_select_field, str, "SELECT"),
    ]
    USER_FIELD_TYPE_DATA: List[UserFieldElement] = [
        (USER, gettext_lazy("Users"), check_valid_user_ids, orjson.loads, "USER"),
    ]

    SELECT_FIELD_VALIDATORS: Dict[int, ExtendedValidator] = {
        item[0]: item[2] for item in SELECT_FIELD_TYPE_DATA
    }
    USER_FIELD_VALIDATORS: Dict[int, RealmUserValidator] = {
        item[0]: item[2] for item in USER_FIELD_TYPE_DATA
    }

    FIELD_TYPE_DATA: List[FieldElement] = [
        # Type, display name, validator, converter, keyword
        (SHORT_TEXT, gettext_lazy("Text (short)"), check_short_string, str, "SHORT_TEXT"),
        (LONG_TEXT, gettext_lazy("Text (long)"), check_long_string, str, "LONG_TEXT"),
        (DATE, gettext_lazy("Date"), check_date, str, "DATE"),
        (URL, gettext_lazy("Link"), check_url, str, "URL"),
        (
            EXTERNAL_ACCOUNT,
            gettext_lazy("External account"),
            check_short_string,
            str,
            "EXTERNAL_ACCOUNT",
        ),
        (PRONOUNS, gettext_lazy("Pronouns"), check_short_string, str, "PRONOUNS"),
    ]

    ALL_FIELD_TYPES = sorted(
        [*FIELD_TYPE_DATA, *SELECT_FIELD_TYPE_DATA, *USER_FIELD_TYPE_DATA], key=lambda x: x[1]
    )

    FIELD_VALIDATORS: Dict[int, Validator[ProfileDataElementValue]] = {
        item[0]: item[2] for item in FIELD_TYPE_DATA
    }
    FIELD_CONVERTERS: Dict[int, Callable[[Any], Any]] = {
        item[0]: item[3] for item in ALL_FIELD_TYPES
    }
    FIELD_TYPE_CHOICES: List[Tuple[int, StrPromise]] = [
        (item[0], item[1]) for item in ALL_FIELD_TYPES
    ]

    field_type = models.PositiveSmallIntegerField(
        choices=FIELD_TYPE_CHOICES,
        default=SHORT_TEXT,
    )

    # A JSON blob of any additional data needed to define the field beyond
    # type/name/hint.
    #
    # The format depends on the type.  Field types SHORT_TEXT, LONG_TEXT,
    # DATE, URL, and USER leave this empty.  Fields of type SELECT store the
    # choices' descriptions.
    #
    # Note: There is no performance overhead of using TextField in PostgreSQL.
    # See https://www.postgresql.org/docs/9.0/static/datatype-character.html
    field_data = models.TextField(default="")

    class Meta:
        unique_together = ("realm", "name")

    @override
    def __str__(self) -> str:
        return f"{self.realm!r} {self.name} {self.field_type} {self.order}"

    def as_dict(self) -> ProfileDataElementBase:
        data_as_dict: ProfileDataElementBase = {
            "id": self.id,
            "name": self.name,
            "type": self.field_type,
            "hint": self.hint,
            "field_data": self.field_data,
            "order": self.order,
        }
        if self.display_in_profile_summary:
            data_as_dict["display_in_profile_summary"] = True

        return data_as_dict

    def is_renderable(self) -> bool:
        if self.field_type in [CustomProfileField.SHORT_TEXT, CustomProfileField.LONG_TEXT]:
            return True
        return False


def custom_profile_fields_for_realm(realm_id: int) -> QuerySet[CustomProfileField]:
    return CustomProfileField.objects.filter(realm=realm_id).order_by("order")


class CustomProfileFieldValue(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=CASCADE)
    field = models.ForeignKey(CustomProfileField, on_delete=CASCADE)
    value = models.TextField()
    rendered_value = models.TextField(null=True, default=None)

    class Meta:
        unique_together = ("user_profile", "field")

    @override
    def __str__(self) -> str:
        return f"{self.user_profile!r} {self.field!r} {self.value}"
