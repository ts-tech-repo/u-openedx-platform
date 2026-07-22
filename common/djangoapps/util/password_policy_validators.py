"""
This file exposes a number of password validators which can be optionally added to
account creation
"""


from collections import Counter
import json
import logging
import string
import unicodedata

from django.contrib.auth.password_validation import MinimumLengthValidator as DjangoMinimumLengthValidator
from django.contrib.auth.password_validation import get_default_password_validators
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from zxcvbn import zxcvbn

log = logging.getLogger(__name__)

# The following constant contains the assumption that the max password length will never exceed 5000
# characters. The point of this restriction is to restrict the login page password field to prevent
# any sort of attacks involving sending massive passwords.
DEFAULT_MAX_PASSWORD_LENGTH = 5000


def create_validator_config(name, options={}):  # lint-amnesty, pylint: disable=dangerous-default-value
    """
    This function is meant to be used for testing purposes to create validators
    easily. It returns a validator config of the form:
        {
            "NAME": "common.djangoapps.util.password_policy_validators.SymbolValidator",
            "OPTIONS": {"min_symbol": 1}
        }

    Parameters:
        name (str): the path name to the validator class to instantiate
        options (dict): The dictionary of options to pass in to the validator.
            These are used to initialize the validator with parameters.
            If undefined, the default parameters will be used.

    Returns:
        Dictionary containing the NAME and OPTIONS for the validator. These will
            be used to instantiate an instance of the validator using Django.
    """
    if options:
        return {'NAME': name, 'OPTIONS': options}

    return {'NAME': name}


def password_validators_instruction_texts():
    """
    Return a string of instruction texts of all configured validators.
    Expects at least the MinimumLengthValidator to be defined.
    """
    complexity_instructions = []
    # For clarity in the printed instructions, the minimum length instruction
    # is separated from the complexity instructions.
    length_instruction = ''
    password_validators = get_default_password_validators()
    for validator in password_validators:
        if hasattr(validator, 'get_instruction_text'):
            text = validator.get_instruction_text()
            if isinstance(validator, MinimumLengthValidator):
                length_instruction = text
            else:
                complexity_instructions.append(text)
    if complexity_instructions:
        return _('Your password must contain {length_instruction}, including {complexity_instructions}.').format(
            length_instruction=length_instruction,
            complexity_instructions=' & '.join(complexity_instructions)
        )
    else:
        return _(f'Your password must contain {length_instruction}.')  # lint-amnesty, pylint: disable=translation-of-non-string


def password_validators_restrictions():
    """
    Return a dictionary of complexity restrictions to be used by mobile users on
    the registration form
    """
    password_validators = get_default_password_validators()
    complexity_restrictions = dict(validator.get_restriction()
                                   for validator in password_validators
                                   if hasattr(validator, 'get_restriction')
                                   )
    return complexity_restrictions


def normalize_password(password):
    """
    Converts the password to utf-8 if it is not unicode already.
    Normalize all passwords to 'NFKC' across the platform to prevent mismatched hash strings when comparing entered
    passwords on login. See LEARNER-4283 for more context.
    """
    if not isinstance(password, str):
        try:
            # some checks rely on unicode semantics (e.g. length)
            password = str(password, encoding='utf8')
        except UnicodeDecodeError:
            # no reason to get into weeds
            raise ValidationError([_('Invalid password.')])  # lint-amnesty, pylint: disable=raise-missing-from
    return unicodedata.normalize('NFKC', password)


def validate_password(password, user=None):
    """
    EdX's custom password validator for passwords. This function performs the
    following functions:
        1) Normalizes the password according to NFKC unicode standard
        2) Calls Django's validate_password method. This calls the validate function
            in all validators specified in AUTH_PASSWORD_VALIDATORS configuration.

    Parameters:
        password (str or unicode): the user's password to be validated
        user (django.contrib.auth.models.User): The user object to use for validating
        the given password against the username and/or email.

    Returns:
        None

    Raises:
        ValidationError if any of the password validators fail.
    """
    password = normalize_password(password)
    django_validate_password(password, user)


def _validate_condition(password, fn, min_count):
    """
    Validates the password using the given function. This is performed by
    iterating through each character in the password and counting up the number
    of characters that satisfy the function.

    Parameters:
        password (str): the password
        fn: the function to be tested against the string.
        min_count (int): the minimum number of characters that must satisfy the function

    Return:
        True if valid_count >= min_count, else False
    """
    valid_count = len([c for c in password if fn(c)])
    return valid_count >= min_count


class MinimumLengthValidator(DjangoMinimumLengthValidator):  # lint-amnesty, pylint: disable=missing-class-docstring
    def get_instruction_text(self):
        return ngettext(
            'at least %(min_length)d character',
            'at least %(min_length)d characters',
            self.min_length
        ) % {'min_length': self.min_length}

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_length', self.min_length


class MaximumLengthValidator:
    """
    Validate whether the password is shorter than a maximum length.

    Parameters:
        max_length (int): the maximum number of characters to require in the password.
    """
    def __init__(self, max_length=75):
        self.max_length = max_length

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if len(password) > self.max_length:
            raise ValidationError(
                ngettext(
                    'This password is too long. It must contain no more than %(max_length)d character.',
                    'This password is too long. It must contain no more than %(max_length)d characters.',
                    self.max_length
                ),
                code='password_too_long',
                params={'max_length': self.max_length},
            )

    def get_help_text(self):
        return ngettext(
            'Your password must contain no more than %(max_length)d character.',
            'Your password must contain no more than %(max_length)d characters.',
            self.max_length
        ) % {'max_length': self.max_length}

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'max_length', self.max_length


class AlphabeticValidator:
    """
    Validate whether the password contains at least min_alphabetic letters.

    Parameters:
        min_alphabetic (int): the minimum number of alphabetic characters to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_alphabetic=0):
        self.min_alphabetic = min_alphabetic

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: c.isalpha(), self.min_alphabetic):
            return
        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_alphabetic)d letter.',
                'This password must contain at least %(min_alphabetic)d letters.',
                self.min_alphabetic
            ),
            code='too_few_alphabetic_char',
            params={'min_alphabetic': self.min_alphabetic},
        )

    def get_help_text(self):
        return ngettext(
            'Your password must contain at least %(min_alphabetic)d letter.',
            'Your password must contain at least %(min_alphabetic)d letters.',
            self.min_alphabetic
        ) % {'min_alphabetic': self.min_alphabetic}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_alphabetic > 0:
            return ngettext(
                '%(num)d letter',
                '%(num)d letters',
                self.min_alphabetic
            ) % {'num': self.min_alphabetic}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_alphabetic', self.min_alphabetic


class NumericValidator:
    """
    Validate whether the password contains at least min_numeric numbers.

    Parameters:
        min_numeric (int): the minimum number of numeric characters to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_numeric=0):
        self.min_numeric = min_numeric

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: c.isnumeric(), self.min_numeric):
            return
        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_numeric)d number.',
                'This password must contain at least %(min_numeric)d numbers.',
                self.min_numeric
            ),
            code='too_few_numeric_char',
            params={'min_numeric': self.min_numeric},
        )

    def get_help_text(self):
        return ngettext(
            "Your password must contain at least %(min_numeric)d number.",
            "Your password must contain at least %(min_numeric)d numbers.",
            self.min_numeric
        ) % {'min_numeric': self.min_numeric}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_numeric > 0:
            return ngettext(
                '%(num)d number',
                '%(num)d numbers',
                self.min_numeric
            ) % {'num': self.min_numeric}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_numeric', self.min_numeric


class UppercaseValidator:
    """
    Validate whether the password contains at least min_upper uppercase letters.

    Parameters:
        min_upper (int): the minimum number of uppercase characters to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_upper=0):
        self.min_upper = min_upper

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: c.isupper(), self.min_upper):
            return
        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_upper)d uppercase letter.',
                'This password must contain at least %(min_upper)d uppercase letters.',
                self.min_upper
            ),
            code='too_few_uppercase_char',
            params={'min_upper': self.min_upper},
        )

    def get_help_text(self):
        return ngettext(
            "Your password must contain at least %(min_upper)d uppercase letter.",
            "Your password must contain at least %(min_upper)d uppercase letters.",
            self.min_upper
        ) % {'min_upper': self.min_upper}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_upper > 0:
            return ngettext(
                '%(num)d uppercase letter',
                '%(num)d uppercase letters',
                self.min_upper
            ) % {'num': self.min_upper}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_upper', self.min_upper


class LowercaseValidator:
    """
    Validate whether the password contains at least min_lower lowercase letters.

    Parameters:
        min_lower (int): the minimum number of lowercase characters to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_lower=0):
        self.min_lower = min_lower

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: c.islower(), self.min_lower):
            return
        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_lower)d lowercase letter.',
                'This password must contain at least %(min_lower)d lowercase letters.',
                self.min_lower
            ),
            code='too_few_lowercase_char',
            params={'min_lower': self.min_lower},
        )

    def get_help_text(self):
        return ngettext(
            "Your password must contain at least %(min_lower)d lowercase letter.",
            "Your password must contain at least %(min_lower)d lowercase letters.",
            self.min_lower
        ) % {'min_lower': self.min_lower}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_lower > 0:
            return ngettext(
                '%(num)d lowercase letter',
                '%(num)d lowercase letters',
                self.min_lower
            ) % {'num': self.min_lower}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_lower', self.min_lower


class PunctuationValidator:
    """
    Validate whether the password contains at least min_punctuation punctuation marks
    as defined by unicode categories.

    Parameters:
        min_punctuation (int): the minimum number of punctuation marks to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_punctuation=0):
        self.min_punctuation = min_punctuation

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: 'P' in unicodedata.category(c), self.min_punctuation):
            return
        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_punctuation)d punctuation mark.',
                'This password must contain at least %(min_punctuation)d punctuation marks.',
                self.min_punctuation
            ),
            code='too_few_punctuation_characters',
            params={'min_punctuation': self.min_punctuation},
        )

    def get_help_text(self):
        return ngettext(
            "Your password must contain at least %(min_punctuation)d punctuation mark.",
            "Your password must contain at least %(min_punctuation)d punctuation marks.",
            self.min_punctuation
        ) % {'min_punctuation': self.min_punctuation}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_punctuation > 0:
            return ngettext(
                '%(num)d punctuation mark',
                '%(num)d punctuation marks',
                self.min_punctuation
            ) % {'num': self.min_punctuation}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_punctuation', self.min_punctuation


class SymbolValidator:
    """
    Validate whether the password contains at least min_symbol symbols as defined by unicode categories.

    Parameters:
        min_symbol (int): the minimum number of symbols to require
            in the password. Must be >= 0.
    """
    def __init__(self, min_symbol=0):
        self.min_symbol = min_symbol

    def validate(self, password, user=None):  # lint-amnesty, pylint: disable=unused-argument
        if _validate_condition(password, lambda c: 'S' in unicodedata.category(c), self.min_symbol):
            return

        # If symbols fails, fall back to PunctuationValidator check
        if _validate_condition(password, lambda c: 'P' in unicodedata.category(c), self.min_symbol):
            return

        raise ValidationError(
            ngettext(
                'This password must contain at least %(min_symbol)d symbol.',
                'This password must contain at least %(min_symbol)d symbols.',
                self.min_symbol
            ),
            code='too_few_symbols',
            params={'min_symbol': self.min_symbol},
        )

    def get_help_text(self):
        return ngettext(
            "Your password must contain at least %(min_symbol)d symbol.",
            "Your password must contain at least %(min_symbol)d symbols.",
            self.min_symbol
        ) % {'min_symbol': self.min_symbol}

    def get_instruction_text(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if self.min_symbol > 0:
            return ngettext(
                '%(num)d symbol',
                '%(num)d symbols',
                self.min_symbol
            ) % {'num': self.min_symbol}
        else:
            return ''

    def get_restriction(self):
        """
        Returns a key, value pair for the restrictions related to the Validator
        """
        return 'min_symbol', self.min_symbol


class CombinationValidator:
    """
    Ensure the password contains at least one character from three of the four categories:
    - Numeric (0–9)
    - Lowercase (a–z)
    - Uppercase (A–Z)
    - Special characters
    """

    def __init__(self, min_categories=3):
        self.min_categories = min_categories

    def validate(self, password, user=None):
        categories = {
            'numeric': any(c.isdigit() for c in password),
            'lowercase': any(c.islower() for c in password),
            'uppercase': any(c.isupper() for c in password),
            'special': any(c in string.punctuation for c in password),
        }

        if sum(categories.values()) < self.min_categories:
            raise ValidationError(
                _("This password must contain characters from at least three of the four categories: "
                  "lowercase, uppercase, numeric, and special characters."),
                code='password_too_simple',
            )

    def get_help_text(self):
        return _("Your password must contain at least one character from three of the four categories: "
                 "lowercase (a-z), uppercase (A-Z), numeric (0-9), and special characters (!@#$%^&*).")



class PreviousPasswordValidator:
    """
    Ensures that the new password is not the same as the user's last password.
    """

    def validate(self, password, user=None):
        if user and user.password:
            if check_password(password, user.password):
                raise ValidationError(
                    _("Your new password cannot be the same as your last password."),
                    code='password_no_reuse',
                )

    def get_help_text(self):
        return _("You must use a different password than your last one.")


class CommonDictionaryWordsValidator:
    """
    Validate that the password is not a common password.

    The password is rejected if it occurs in a provided list of passwords
    from PasswordValidationDictionary model. It checks if the given
    password (or its reverse) exists in the database.
    """
    def validate(self, password, user=None):
        # Run the zxcvbn password strength estimator
        result = zxcvbn(password)
        score = result.get('score')
        feedback = result.get('feedback', {})

        # Extract warning and suggestions from feedback
        warning = feedback.get('warning', '')
        suggestions = feedback.get('suggestions', [])

        # Log the validation result
        log.info("Password validation result for '%s': %s", password, result)

        # Raise validation error if score is less than or equal to 3
        if score <= 3:
            raise ValidationError({
                'password_policy_violation': json.dumps({
                    'message': _("This password is too similar to a common password and has been blocked for security reasons."),
                    'warning': warning,
                    'suggestions': suggestions
                })
            })


    def get_help_text(self):
        return "Your password cannot be a commonly used password or its reverse."

class EnhancedUserAttributeSimilarityValidator:
    """
    Custom validator that ensures the password does not contain parts of the user's attributes
    (username, first name, last name) even if they are slightly modified or reversed.
    """

    DEFAULT_USER_ATTRIBUTES = ("username", "first_name", "last_name", "email")

    def __init__(self, user_attributes=None):
        self.user_attributes = user_attributes or self.DEFAULT_USER_ATTRIBUTES

    def get_n_length_substrings(self, s, n=4):
        """Generate all possible substrings of length n from the given string."""
        if len(s) < n:
            return set()
        return {s[i:i+n] for i in range(len(s) - n + 1)}

    def validate(self, password, user=None):
        if user:
            password = password.lower()  # Normalize password case
            user_values = list(filter(None, [str(getattr(user, attr, "")).lower() for attr in self.user_attributes]))

            if not user_values:
                return

            four_char_substrings = set()
            for value in user_values:
                    substrings_values = self.get_n_length_substrings(value)
                    four_char_substrings.update(substrings_values)
                    four_char_substrings.update({sub[::-1] for sub in substrings_values})

            if any(sub in password for sub in four_char_substrings):
                        raise ValidationError(
                            _("Your password cannot contain parts of your personal details (forward or reversed)."),
                            code='password_too_similar',
                        )

    def get_help_text(self):
        return _("Your password cannot contain parts of your username, first name, or last name, even with special characters or in reverse order.")


class UniqueCharactersValidator:
    """
    Ensures that the password contains at least a minimum number of unique characters.
    """

    def __init__(self, min_unique=4):
        self.min_unique = min_unique

    def validate(self, password, user=None):
        unique_chars = set(password)
        if len(unique_chars) < self.min_unique:
            raise ValidationError(
                _(f"Your password must contain at least {self.min_unique} unique characters."),
                code="password_too_few_unique_chars",
            )

    def get_help_text(self):
        return _(f"Your password must contain at least {self.min_unique} unique characters.")


class MaxCharacterOccurrenceValidator:
    """
    Ensures that no character in the password appears more than a specified number of times.
    """

    def __init__(self, max_occurrences=4):
        self.max_occurrences = max_occurrences

    def validate(self, password, user=None):
        char_counts = Counter(password)
        for char, count in char_counts.items():
            if count > self.max_occurrences:
                raise ValidationError(
                    _(f"Your password cannot contain any character more than {self.max_occurrences} times."),
                    code="password_too_many_repeated_chars",
                )

    def get_help_text(self):
        return _(f"Your password cannot contain any character more than {self.max_occurrences} times.")

