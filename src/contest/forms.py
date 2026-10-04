from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, StringField, TelField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp, ValidationError

NAME = Regexp(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$", message="Use letters only.")


class EntryForm(FlaskForm):
    first_name = StringField("First name", validators=[DataRequired(), Length(max=60), NAME])
    last_name = StringField("Last name", validators=[DataRequired(), Length(max=60), NAME])
    mobile = TelField(
        "Mobile number", validators=[DataRequired(), Length(max=20)], description="10-digit Indian mobile number"
    )
    email = EmailField("Email", validators=[DataRequired(), Email(check_deliverability=False), Length(max=254)])
    consent = BooleanField(
        "I agree to the contest rules and to being contacted about this contest.",
        validators=[DataRequired(message="Please accept the rules to take part.")],
    )
    # Hidden from people with CSS; bots that fill every field reveal themselves.
    website = StringField("Leave this empty", validators=[Optional()])

    def normalised_mobile(self) -> str:
        digits = re.sub(r"\D", "", self.mobile.data or "")
        return digits[-10:]

    def validate_mobile(self, field) -> None:
        digits = re.sub(r"\D", "", field.data or "")
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        if not re.fullmatch(r"[6-9]\d{9}", digits):
            raise ValidationError("Enter a valid 10-digit mobile number.")
