"""
    pwm
    ~~~

    Expose public APIs.

"""
# pylint: disable=unused-import

__version__ = '0.1.4'

from .core import (
    Domain,
    PWM,
)

from .exceptions import (
    DuplicateDomainException,
    NotReadyException,
    NoSuchDomainException,
)

from .encoding import (
    ceildiv,
    calc_chunklen,
    Encoder,
    lookup_alphabet,
    PRESETS,
)
